import json
import logging
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

from .state import (
    AgentState, Plan, ExplorationStep, SchemaAnalysis, CoverageAnalysis, 
    LoopDetector, DecisionMaker, SynthesisPlan, AnswerOutput, QueryValidation,
    CommunityLog, AlignmentOutput, AnswerContract, InterpretedEvidence,
    NegativeKnowledge, HardConstraints, QueryClassification, PlanningPhase
)
from .prompts import (
    VALIDATION_PROMPT, PLANNER_PROMPT, SCHEMA_EXTRACTOR_PROMPT, 
    COVERAGE_ASSESSOR_PROMPT, LOOP_DETECTOR_PROMPT, DECISION_MAKER_PROMPT, 
    EXPLORATION_PLANNER_PROMPT, SYNTHESIS_PLANNER_PROMPT, ANSWER_GENERATOR_PROMPT,
    ALIGNMENT_PROMPT, QUERY_CLASSIFIER_PROMPT, EVIDENCE_INTERPRETER_PROMPT,
    PLAN_PROPOSAL_PROMPT, PLAN_GATEKEEPER_PROMPT
)
from .utils import prune_evidence, get_unique_schema

logger = logging.getLogger(__name__)

async def validate_query(user_input: str, llm):
    parser = PydanticOutputParser(pydantic_object=QueryValidation)
    prompt = ChatPromptTemplate.from_template(VALIDATION_PROMPT)
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

async def query_classifier_node(state: AgentState, llm):
    """Define the Answer Contract for the query"""
    parser = PydanticOutputParser(pydantic_object=QueryClassification)
    prompt = ChatPromptTemplate.from_template(QUERY_CLASSIFIER_PROMPT)
    classifier = prompt | llm | parser
    try:
        result = await classifier.ainvoke({
            "input": state["input"],
            "format_instructions": parser.get_format_instructions()
        })
        logger.info(f"Answer Contract Defined: {result.contract.query_type}")
        return {
            "original_query": state["input"],
            "answer_contract": result.contract.dict(),
            "hard_constraints": HardConstraints().dict()
        }
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        # Default to association contract
        default_contract = AnswerContract(
            query_type="association", 
            required_entity_types=["Entity"], 
            required_predicates=["biolink:related_to"]
        )
        return {"answer_contract": default_contract.dict(), "hard_constraints": HardConstraints().dict()}

async def plan_proposer_node(state: AgentState, llm):
    """Generate or update the 'North Star' plan proposal"""
    prompt = ChatPromptTemplate.from_template(PLAN_PROPOSAL_PROMPT)
    proposer = prompt | llm
    
    logger.info(f"Generating plan. Feedback: {state.get('planning_feedback', 'None')}")
    try:
        response = await proposer.ainvoke({
            "original_query": state.get("original_query", state.get("input", "Unknown Query")),
            "previous_plan": state.get("plan_proposal", "None"),
            "feedback": state.get("planning_feedback", "Initial proposal")
        })
        
        plan = response.content.strip()
        if not plan:
            logger.warning("LLM returned empty plan proposal!")
            plan = state.get("plan_proposal", "Error generating updated plan.")
        
        logger.info(f"Plan proposal generated (length: {len(plan)})")
        
        return {
            "plan_proposal": plan,
            "response": plan  # Return to user
        }
    except Exception as e:
        logger.error(f"Plan proposal failed: {e}")
        error_msg = f"I encountered an error generating the plan: {e}. Please try giving a simpler instruction."
        return {
            "plan_proposal": state.get("plan_proposal", "Error"),
            "response": error_msg
        }

async def plan_gatekeeper_node(state: AgentState, llm):
    """Determine if user approved the plan or provided feedback"""
    # If the plan was just proposed in THIS turn, we don't check approval yet
    # We only check approval if the user input is responding TO a previous proposal
    if not state.get("plan_proposal"):
        return {"is_plan_approved": False}

    parser = PydanticOutputParser(pydantic_object=PlanningPhase)
    prompt = ChatPromptTemplate.from_template(PLAN_GATEKEEPER_PROMPT)
    gatekeeper = prompt | llm | parser
    
    try:
        result = await gatekeeper.ainvoke({            
            "input": state["input"],
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Planning decision: {result.decision}")
        
        if result.decision == "approved":
            return {
                "is_plan_approved": True, 
                "planning_feedback": "",
                "response": ""  # Clear the plan from the response field to allow research to proceed
            }
        else:
            return {
                "is_plan_approved": False, 
                "planning_feedback": state["input"]
            }
    except Exception as e:
        logger.error(f"Plan gatekeeping failed: {e}")
        return {"is_plan_approved": False}

async def planner_node(state: AgentState, llm):
    """Initial planner - creates exploration strategy"""
    parser = PydanticOutputParser(pydantic_object=Plan)
    prompt = ChatPromptTemplate.from_template(PLANNER_PROMPT)
    planner = prompt | llm | parser
    
    try:
        result = await planner.ainvoke({
            "input": state.get("original_query", state["input"]),
            "north_star_plan": state.get("plan_proposal", "Follow general research principles."),
            "contract": json.dumps(state.get("answer_contract", {}), indent=2),
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Initial step: {result.steps[0] if result.steps else 'None'}")
        return {
            "plan": result.steps[:1], # FORCED SINGLE STEP
            "exploration_strategy": result.strategy
        }
    except Exception as e:
        logger.error(f"Planning failed (likely JSON error): {e}")
        return {
            "plan": [],
            "exploration_strategy": f"I encountered an error while planning: {e}. Please try checking your input or rephrasing your request."
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
                # Improved text handling for lists (MCP content blocks)
                if isinstance(tool_result, list):
                    # extract text from blocks if they are dicts with 'text'
                    text_parts = []
                    for item in tool_result:
                        if isinstance(item, dict) and "text" in item:
                            text_parts.append(item["text"])
                        else:
                            text_parts.append(str(item))
                    result_str = "\n".join(text_parts)
                else:
                    result_str = str(tool_result)

                # Include truncated result in history so planner sees the CURIEs
                # increased limit to allow for edge summary visibility
                result_snippet = result_str[:2000].replace('\n', ' ') 
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

async def evidence_interpreter_node(state: AgentState, llm):
    """Interpret raw tool output and assign strength/type"""
    if not state.get("evidence"):
        return {}
        
    parser = PydanticOutputParser(pydantic_object=InterpretedEvidence)
    prompt = ChatPromptTemplate.from_template(EVIDENCE_INTERPRETER_PROMPT)
    interpreter = prompt | llm | parser
    
    last_raw = state["evidence"][-1]
    if last_raw.get("status") != "success":
        # Handle failures as negative knowledge
        neg = NegativeKnowledge(
            entity=str(last_raw.get("args", {}).get("curie", "unknown")),
            predicate=str(last_raw.get("args", {}).get("predicate", "unknown")),
            failure_reason=last_raw.get("data") or "Timeout/Error",
            iteration=state.get("iteration_count", 0)
        )
        return {"negative_knowledge": [neg.dict()]}

    try:
        # Interpret ONLY if it's an edge (list of results or single edge)
        # Avoid interpreting name-resolution as evidence for the contract
        if last_raw.get("tool") not in ["get_edges", "get_edges_between"]:
            return {}

        result = await interpreter.ainvoke({
            "raw_evidence": json.dumps(last_raw, indent=2)[:5000],
            "contract": json.dumps(state.get("answer_contract", {}), indent=2),
            "format_instructions": parser.get_format_instructions()
        })
        
        return {"interpreted_evidence": [result.dict()]}
    except Exception as e:
        logger.error(f"Evidence interpretation failed: {e}")
        return {}

async def schema_analyzer_node(state: AgentState, llm):
    """Extract schema patterns ONLY - no decisions"""
    parser = PydanticOutputParser(pydantic_object=SchemaAnalysis)
    prompt = ChatPromptTemplate.from_template(SCHEMA_EXTRACTOR_PROMPT)
    analyzer = prompt | llm | parser
    
    last_evidence = state["evidence"][-1] if state["evidence"] else {}
    
    # If last evidence is not from a graph tool, skip analysis
    if last_evidence.get("tool") in ["name-resolver", "nodenormalizer"]:
        return {"schema_patterns": []}

    # If last evidence is a summary, use it. If it's a huge edge list, we might want to truncate or summarize.
    evidence_str = json.dumps(last_evidence, indent=2)
    if len(evidence_str) > 10000:
        evidence_str = evidence_str[:10000] + "...(truncated)"
    
    try:
        result = await analyzer.ainvoke({
            "last_evidence": evidence_str,
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
    prompt = ChatPromptTemplate.from_template(COVERAGE_ASSESSOR_PROMPT)
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
    prompt = ChatPromptTemplate.from_template(LOOP_DETECTOR_PROMPT)
    detector = prompt | llm | parser
    
    recent_steps = state.get("past_steps", [])[-5:]
    
    try:
        result = await detector.ainvoke({
            "recent_steps": str(recent_steps),
            "schema_patterns": "\n".join(get_unique_schema(state.get("schema_patterns", []))),
            "format_instructions": parser.get_format_instructions()
        })
        
        if result.is_looping:
            logger.warning(f"Loop detected: {result.repeated_pattern}")
        
        return {"loop_detection": json.dumps(result.dict())}
    except Exception as e:
        logger.error(f"Loop detection failed: {e}")
        return {"loop_detection": json.dumps({"is_looping": False, "recommendation": "Continue"})}

async def alignment_node(state: AgentState, llm):
    """Steward the Community Log (Shared Epistemology)"""
    parser = PydanticOutputParser(pydantic_object=AlignmentOutput)
    prompt = ChatPromptTemplate.from_template(ALIGNMENT_PROMPT)
    aligner = prompt | llm | parser

    # Default log if missing
    current_log = state.get("community_log", {})
    if isinstance(current_log, str):
        try:
           current_log = json.loads(current_log)
        except:
           current_log = {}

    # Only run every 3 steps OR if looping is detected
    step_count = len(state.get("past_steps", []))
    loop_data = json.loads(state.get("loop_detection", "{}"))
    is_looping = loop_data.get("is_looping", False)
    
    # We run alignment:
    # 1. At the very beginning (step_count == 0)
    # 2. Every 3 steps (step_count % 3 == 0)
    # 3. If looping is detected
    should_run = (step_count == 0) or (step_count % 3 == 0) or is_looping
    
    if not should_run and step_count > 0:
        logger.info("Alignment node skipping this turn (not triggered)")
        return {} # No update

    # Prepare evidence summary
    pruned_evidence = prune_evidence(state.get("evidence", []))
    evidence_summary = "\\n".join([
        f"- {e.get('tool', 'N/A')}: {str(e.get('data', ''))[:200]}..."
        for e in pruned_evidence
        if e.get("status") == "success"
    ])
    
    recent_steps = state.get("past_steps", [])[-5:]

    try:
        result = await aligner.ainvoke({
            "community_log": current_log,
            "recent_steps": str(recent_steps),
            "evidence_summary": evidence_summary,
            "loop_detection": state.get("loop_detection", "{}"),
            "format_instructions": parser.get_format_instructions()
        })
        
        logger.info(f"Alignment Update: {result.updates_made}")
        return {
            "community_log": result.updated_log.dict(),
            "hard_constraints": result.hard_constraints.dict()
        }
    except Exception as e:
        logger.error(f"Alignment failed: {e}")
        return {} # No update

async def decision_maker_node(state: AgentState, llm):
    """Make phase decision based on Answer Contract satisfaction"""
    parser = PydanticOutputParser(pydantic_object=DecisionMaker)
    prompt = ChatPromptTemplate.from_template(DECISION_MAKER_PROMPT)
    decider = prompt | llm | parser
    
    contract = state.get("answer_contract", {})
    interpreted = state.get("interpreted_evidence", [])
    
    try:
        result = await decider.ainvoke({
            "input": state.get("input", "Unknown Query"),
            "contract": json.dumps(contract, indent=2),
            "interpreted_evidence": json.dumps(interpreted, indent=2),
            "format_instructions": parser.get_format_instructions()
        })
        
        # Defensive check for attributes
        ctrl = getattr(result, "control_decision", "explore")
        state_esc = getattr(result, "epistemic_state", "insufficient")
        reasoning = getattr(result, "reasoning", "Proceeding with exploration.")
        
        logger.info(f"Decision: {ctrl} (State: {state_esc})")
        
        return {
            "should_explore_more": ctrl == "explore",
            "should_transition_to_synthesis": ctrl == "synthesize",
            "ready_to_answer": ctrl != "explore",
            "decision_reasoning": reasoning
        }
    except Exception as e:
        logger.error(f"Decision making failed: {e}")
        # Default: continue exploring if under iteration limit
        at_limit = state.get("iteration_count", 0) >= state.get("max_iterations", 15)
        return {
            "should_explore_more": not at_limit,
            "should_transition_to_synthesis": at_limit,
            "ready_to_answer": at_limit,
            "decision_reasoning": f"Error in decision making: {e}. Defaulting to {'stop' if at_limit else 'continue'}."
        }

async def exploration_planner_node(state: AgentState, llm):
    """Plan next exploration step"""
    parser = PydanticOutputParser(pydantic_object=ExplorationStep)
    prompt = ChatPromptTemplate.from_template(EXPLORATION_PLANNER_PROMPT)
    planner = prompt | llm | parser
    
    coverage_data = json.loads(state.get("coverage_assessment", "{}"))
    loop_data = json.loads(state.get("loop_detection", "{}"))
    
    # Provide pruned evidence summary so planner knows what we found
    pruned_evidence = prune_evidence(state.get("evidence", []))
    evidence_summary = "\n".join([
        f"- {e.get('tool', 'N/A')}: {str(e.get('data', ''))[:400]}..." # Show more context
        for e in pruned_evidence
        if e.get("status") == "success"
    ])

    # Parse Log
    log_data = state.get("community_log", {})
    if isinstance(log_data, str):
        try: log_data = json.loads(log_data)
        except: log_data = {}

    novelty_budget = log_data.get("novelty_budget", 5)
    resolved = log_data.get("resolved_entities", {})
    constraints = state.get("hard_constraints", {})
    failures = state.get("negative_knowledge", [])

    try:
        result = await planner.ainvoke({
            "input": state.get("input", "Unknown Query"),
            "evidence_summary": evidence_summary,
            "contract": json.dumps(state.get("answer_contract", {}), indent=2),
            "resolved_entities": json.dumps(resolved, indent=2),
            "hard_constraints": json.dumps(constraints, indent=2),
            "negative_knowledge": json.dumps(failures, indent=2),
            "novelty_budget": novelty_budget,
            "epistemic_status": state.get("decision_reasoning", "Starting exploration"),
            "missing_fact": "N/A", # Will be used if DM provides it
            "format_instructions": parser.get_format_instructions()
        })
        
        action = getattr(result, "action", "Get edge summary for main entity")
        rationale = getattr(result, "rationale", "Exploring missing knowledge.")
        
        logger.info(f"Next exploration: {action}")
        return {
            "plan": [action],
            "planning_rationale": rationale
        }
    except Exception as e:
        logger.error(f"Exploration planning failed: {e}")
        # Return a safe default action
        return {
            "plan": ["Get edge summary for primary concept"],
            "planning_rationale": f"Defaulting to scouting due to planning error: {e}"
        }

async def synthesis_planner_node(state: AgentState, llm):
    """Plan how to answer the question"""
    parser = PydanticOutputParser(pydantic_object=SynthesisPlan)
    prompt = ChatPromptTemplate.from_template(SYNTHESIS_PLANNER_PROMPT)
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
    prompt = ChatPromptTemplate.from_template(ANSWER_GENERATOR_PROMPT)
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

    # Extract subgraph from evidence
    nodes = {}
    edges = []
    
    for item in successful_evidence:
        tool = item.get("tool")
        data = item.get("data")
        
        if not data:
            continue
            
        try:
            # Handle edge lists
            if tool in ["get_edges", "get_edges_between"] and isinstance(data, list):
                for edge in data:
                    # Capture nodes
                    if "subject" in edge:
                        s = edge["subject"]
                        if isinstance(s, dict) and "id" in s:
                            nodes[s["id"]] = {"id": s["id"], "name": s.get("name", s["id"]), "type": s.get("category", ["Entity"])[0]}
                    
                    if "object" in edge:
                        o = edge["object"]
                        if isinstance(o, dict) and "id" in o:
                            nodes[o["id"]] = {"id": o["id"], "name": o.get("name", o["id"]), "type": o.get("category", ["Entity"])[0]}
                            
                    # Capture edge
                    if "predicate" in edge and "subject" in edge and "object" in edge:
                        edges.append({
                            "source": edge["subject"]["id"],
                            "target": edge["object"]["id"],
                            "label": edge["predicate"],
                            "id": edge.get("id", f"{edge['subject']['id']}-{edge['predicate']}-{edge['object']['id']}")
                        })
                        
            # Handle single node lookup
            elif tool == "get_node" and isinstance(data, dict):
                if "id" in data:
                    nodes[data["id"]] = {
                        "id": data["id"], 
                        "name": data.get("name", data["id"]), 
                        "type": data.get("category", ["Entity"])[0]
                    }

        except Exception as ex:
            logger.warning(f"Error extracting subgraph from {tool}: {ex}")

    critical_subgraph = {
        "nodes": list(nodes.values()),
        "edges": edges
    }
    
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
        
        return {
            "response": response, 
            "plan": [],
            "critical_subgraph": critical_subgraph
        }
    except Exception as e:
        logger.error(f"Answer generation failed: {e}")
        # Fallback: simple summary
        return {
            "response": f"Based on collected evidence: {str(successful_evidence[:2])[:500]}...",
            "plan": [],
            "critical_subgraph": {"nodes": [], "edges": []}
        }
