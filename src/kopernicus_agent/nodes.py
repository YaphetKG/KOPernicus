import json
import logging
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

from .state import (
    AgentState, Plan, ExplorationStep, SchemaAnalysis, CoverageAnalysis, 
    LoopDetector, DecisionMaker, SynthesisPlan, AnswerOutput, QueryValidation
)
from .prompts import (
    VALIDATION_PROMPT, PLANNER_PROMPT, SCHEMA_EXTRACTOR_PROMPT, 
    COVERAGE_ASSESSOR_PROMPT, LOOP_DETECTOR_PROMPT, DECISION_MAKER_PROMPT, 
    EXPLORATION_PLANNER_PROMPT, SYNTHESIS_PLANNER_PROMPT, ANSWER_GENERATOR_PROMPT
)
from .utils import prune_evidence, get_unique_schema

logger = logging.getLogger(__name__)

async def validate_query(user_input: str, llm):
    parser = PydanticOutputParser(pydantic_object=QueryValidation)
    prompt = ChatPromptTemplate.from_template(VALIDATION_PROMPT + "\n{format_instructions}")
    validator = prompt | llm | parser
    try:
        result = await validator.ainvoke({
            "input": user_input,
            "format_instructions": parser.get_format_instructions()
        })
        logger.info(f"Query validation: {'VALID' if result.is_valid else 'INVALID'}")
        return result
    except Exception as e:
        logger.warning(f"Validation error: {e}")
        return QueryValidation(is_valid=True, feedback=user_input)

async def planner_node(state: AgentState, llm):
    """Initial planner - creates exploration strategy"""
    parser = PydanticOutputParser(pydantic_object=Plan)
    prompt = ChatPromptTemplate.from_template(PLANNER_PROMPT + "\n{format_instructions}")
    planner = prompt | llm | parser
    
    result = await planner.ainvoke({
        "input": state["input"],
        "format_instructions": parser.get_format_instructions()
    })
    
    logger.info(f"Initial plan: {result.strategy}")
    return {
        "plan": result.steps,
        "exploration_strategy": result.strategy
    }

async def executor_node(state: AgentState, llm, tools):
    """Execute single step from plan"""
    plan = state["plan"]
    if not plan:
        logger.error("Empty plan in executor")
        return {
            "past_steps": [("ERROR", "No plan")],
            "evidence": [{"step": "ERROR", "status": "failed", "data": "No plan"}]
        }
    
    task = plan[0]
    logger.info(f"Executing: {task}")
    
    llm_with_tools = llm.bind_tools(tools)
    system_msg = SystemMessage(content=f"Execute this task using available tools: {task}")
    
    try:
        response = await llm_with_tools.ainvoke([system_msg])
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return {
            "past_steps": [(task, f"LLM Error: {e}")],
            "evidence": [{"step": task, "status": "error", "error_type": "llm_failed", "data": str(e)}]
        }
    
    evidence_item = {"step": task, "status": "failed", "data": None}
    output_text = ""
    
    if response.tool_calls:
        tool_call = response.tool_calls[0]
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        
        selected_tool = next((t for t in tools if t.name == tool_name), None)
        
        if selected_tool:
            try:
                tool_result = await selected_tool.ainvoke(tool_args)
                evidence_item = {
                    "step": task,
                    "tool": tool_name,
                    "args": tool_args,
                    "status": "success",
                    "data": tool_result
                }
                # Include truncated result in history so planner sees the CURIEs
                result_snippet = str(tool_result)[:200].replace('\n', ' ')
                output_text = f"✓ {tool_name}: {result_snippet}..."
                logger.info("Tool executed successfully")
            except Exception as e:
                error_type = "timeout" if "timeout" in str(e).lower() else "execution_error"
                evidence_item = {
                    "step": task,
                    "tool": tool_name,
                    "args": tool_args,
                    "status": "error",
                    "error_type": error_type,
                    "data": str(e)
                }
                output_text = f"✗ {tool_name}: {e}"
                logger.error(f"Tool error: {e}")
        else:
            evidence_item = {
                "step": task,
                "status": "error",
                "error_type": "tool_not_found",
                "data": f"Tool {tool_name} not available"
            }
            output_text = f"Tool not found: {tool_name}"
    else:
        evidence_item["data"] = response.content
        output_text = "No tool call generated"
    
    return {
        "past_steps": [(task, output_text)],
        "evidence": [evidence_item]
    }

async def schema_analyzer_node(state: AgentState, llm):
    """Extract schema patterns ONLY - no decisions"""
    parser = PydanticOutputParser(pydantic_object=SchemaAnalysis)
    prompt = ChatPromptTemplate.from_template(SCHEMA_EXTRACTOR_PROMPT + "\n{format_instructions}")
    analyzer = prompt | llm | parser
    
    last_evidence = state["evidence"][-1] if state["evidence"] else {}
    
    try:
        result = await analyzer.ainvoke({
            "last_evidence": json.dumps(last_evidence, indent=2),
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Found {len(result.patterns)} schema patterns")
        return {"schema_patterns": result.patterns}
    except Exception as e:
        logger.error(f"Schema analysis failed: {e}")
        return {"schema_patterns": []}

async def coverage_analyzer_node(state: AgentState, llm):
    """Assess coverage ONLY - no decisions"""
    parser = PydanticOutputParser(pydantic_object=CoverageAnalysis)
    prompt = ChatPromptTemplate.from_template(COVERAGE_ASSESSOR_PROMPT + "\n{format_instructions}")
    analyzer = prompt | llm | parser
    
    try:
        result = await analyzer.ainvoke({
            "schema_patterns": "\n".join(get_unique_schema(state.get("schema_patterns", []))),
            "past_steps": str(state.get("past_steps", [])[-5:]),  # Recent steps only
            "input": state["input"],
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Coverage score: {result.density_score}/10")
        return {"coverage_assessment": json.dumps(result.dict())}
    except Exception as e:
        logger.error(f"Coverage analysis failed: {e}")
        return {"coverage_assessment": json.dumps({"density_score": 5, "explored_predicates": []})}

async def loop_detector_node(state: AgentState, llm):
    """Detect loops ONLY - no decisions"""
    parser = PydanticOutputParser(pydantic_object=LoopDetector)
    prompt = ChatPromptTemplate.from_template(LOOP_DETECTOR_PROMPT + "\n{format_instructions}")
    detector = prompt | llm | parser
    
    recent_steps = state.get("past_steps", [])[-5:]
    
    try:
        result = await detector.ainvoke({
            "recent_steps": str(recent_steps),
            "format_instructions": parser.get_format_instructions()
        })
        
        if result.is_looping:
            logger.warning(f"Loop detected: {result.repeated_pattern}")
        
        return {"loop_detection": json.dumps(result.dict())}
    except Exception as e:
        logger.error(f"Loop detection failed: {e}")
        return {"loop_detection": json.dumps({"is_looping": False, "recommendation": "Continue"})}

async def decision_maker_node(state: AgentState, llm):
    """Make phase decision based on analyses"""
    parser = PydanticOutputParser(pydantic_object=DecisionMaker)
    prompt = ChatPromptTemplate.from_template(DECISION_MAKER_PROMPT + "\n{format_instructions}")
    decider = prompt | llm | parser
    
    coverage_data = json.loads(state.get("coverage_assessment", "{}"))
    loop_data = json.loads(state.get("loop_detection", "{}"))
    
    # Provide pruned evidence summary so decision maker knows what we have
    pruned_evidence = prune_evidence(state.get("evidence", []))
    evidence_summary = "\n".join([
        f"- {e.get('tool', 'N/A')}: {str(e.get('data', ''))[:200]}..."
        for e in pruned_evidence
        if e.get("status") == "success"
    ])
    
    try:
        result = await decider.ainvoke({
            "coverage_score": coverage_data.get("density_score", 5),
            "loop_status": "LOOPING" if loop_data.get("is_looping") else "OK",
            "iteration": state.get("iteration_count", 0),
            "max_iterations": state.get("max_iterations", 15),
            "input": state["input"],
            "evidence_summary": evidence_summary,
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Decision: explore={result.should_explore_more}, synthesize={result.should_transition_to_synthesis}")
        
        return {
            "should_explore_more": result.should_explore_more,
            "should_transition_to_synthesis": result.should_transition_to_synthesis,
            "ready_to_answer": not result.should_explore_more
        }
    except Exception as e:
        logger.error(f"Decision making failed: {e}")
        # Default: continue exploring if under iteration limit
        at_limit = state.get("iteration_count", 0) >= state.get("max_iterations", 15)
        return {
            "should_explore_more": not at_limit,
            "should_transition_to_synthesis": at_limit,
            "ready_to_answer": at_limit
        }

async def exploration_planner_node(state: AgentState, llm):
    """Plan next exploration step"""
    parser = PydanticOutputParser(pydantic_object=ExplorationStep)
    prompt = ChatPromptTemplate.from_template(EXPLORATION_PLANNER_PROMPT + "\n{format_instructions}")
    planner = prompt | llm | parser
    
    coverage_data = json.loads(state.get("coverage_assessment", "{}"))
    loop_data = json.loads(state.get("loop_detection", "{}"))
    
    try:
        result = await planner.ainvoke({
            "input": state["input"],
            "past_steps": str(state.get("past_steps", [])[-5:]),
            "coverage": state.get("coverage_assessment", ""),
            "schema": "\n".join(get_unique_schema(state.get("schema_patterns", []))),
            "loop_detection": state.get("loop_detection", ""),
            "unexplored_predicates": str(coverage_data.get("unexplored_promising_predicates", [])),
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Next exploration: {result.action}")
        return {"plan": [result.action]}
    except Exception as e:
        logger.error(f"Exploration planning failed: {e}")
        return {"plan": ["Get edge summary for main entity"]}

async def synthesis_planner_node(state: AgentState, llm):
    """Plan how to answer the question"""
    parser = PydanticOutputParser(pydantic_object=SynthesisPlan)
    prompt = ChatPromptTemplate.from_template(SYNTHESIS_PLANNER_PROMPT + "\n{format_instructions}")
    planner = prompt | llm | parser
    
    # Provide pruned evidence summary
    pruned_evidence = prune_evidence(state.get("evidence", []))
    evidence_summary = "\n".join([
        f"- {e.get('tool', 'N/A')}: {str(e.get('data', ''))[:100]}..."
        for e in pruned_evidence
        if e.get("status") == "success"
    ])
    
    try:
        result = await planner.ainvoke({
            "input": state["input"],
            "evidence_summary": evidence_summary,
            "schema_patterns": "\n".join(get_unique_schema(state.get("schema_patterns", []))),
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info("Synthesis plan created")
        return {"plan": [f"Generate answer: {result.answer_structure}"]}
    except Exception as e:
        logger.error(f"Synthesis planning failed: {e}")
        return {"plan": ["Generate answer with available evidence"]}

async def answer_generator_node(state: AgentState, llm):
    """Generate final answer with proper citations"""
    parser = PydanticOutputParser(pydantic_object=AnswerOutput)
    prompt = ChatPromptTemplate.from_template(ANSWER_GENERATOR_PROMPT + "\n{format_instructions}")
    generator = prompt | llm | parser
    
    # Get successful evidence with full detail
    successful_evidence = [
        e for e in state.get("evidence", [])
        if e.get("status") == "success"
    ]
    
    # Format evidence clearly
    full_evidence = "\n\n".join([
        f"Evidence {i+1}:\n{json.dumps(e, indent=2)}"
        for i, e in enumerate(successful_evidence)
    ])
    
    synthesis_plan = state.get("plan", ["Answer the question"])[0]
    
    try:
        result = await generator.ainvoke({
            "input": state["input"],
            "synthesis_plan": synthesis_plan,
            "full_evidence": full_evidence,
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Answer generated (confidence: {result.confidence})")
        
        # Format final response
        response = f"{result.answer}\n\n"
        if result.confidence != "high":
            response += f"**Confidence**: {result.confidence}\n"
        if result.limitations != "None":
            response += f"**Limitations**: {result.limitations}"
        
        return {"response": response, "plan": []}
    except Exception as e:
        logger.error(f"Answer generation failed: {e}")
        # Fallback: simple summary
        return {
            "response": f"Based on collected evidence: {str(successful_evidence[:2])[:500]}...",
            "plan": []
        }
