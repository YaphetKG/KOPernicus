from langgraph.graph import StateGraph, END
from .state import AgentState
from .nodes import (
    planner_node, executor_node, schema_analyzer_node, 
    coverage_analyzer_node, loop_detector_node, decision_maker_node, 
    exploration_planner_node, synthesis_planner_node, answer_generator_node
)
from .llm import LLMFactory

def create_agent_graph(llm, tools):
    # Define nodes with cleaner separation
    async def planner(state): return await planner_node(state, llm)
    async def executor(state): return await executor_node(state, llm, tools)
    async def schema_analyzer(state): return await schema_analyzer_node(state, llm)
    async def coverage_analyzer(state): return await coverage_analyzer_node(state, llm)
    async def loop_detector(state): return await loop_detector_node(state, llm)
    async def decision_maker(state):
        result = await decision_maker_node(state, llm)
        result["iteration_count"] = state.get("iteration_count", 0) + 1
        return result
    async def exploration_planner(state): return await exploration_planner_node(state, llm)
    async def synthesis_planner(state): return await synthesis_planner_node(state, llm)
    async def answer_generator(state): return await answer_generator_node(state, llm)
    
    # Build graph with clear flow
    workflow = StateGraph(AgentState)
    
    # Add all nodes
    workflow.add_node("planner", planner)
    workflow.add_node("executor", executor)
    workflow.add_node("schema_analyzer", schema_analyzer)
    workflow.add_node("coverage_analyzer", coverage_analyzer)
    workflow.add_node("loop_detector", loop_detector)
    workflow.add_node("decision_maker", decision_maker)
    workflow.add_node("exploration_planner", exploration_planner)
    workflow.add_node("synthesis_planner", synthesis_planner)
    workflow.add_node("answer_generator", answer_generator)
    
    workflow.set_entry_point("planner")
    
    # Initial plan → execute
    workflow.add_edge("planner", "executor")
    
    # After execution → parallel analysis
    workflow.add_edge("executor", "schema_analyzer")
    workflow.add_edge("schema_analyzer", "coverage_analyzer")
    workflow.add_edge("coverage_analyzer", "loop_detector")
    workflow.add_edge("loop_detector", "decision_maker")
    
    # Decision → exploration or synthesis
    def route_after_decision(state: AgentState):
        if state.get("response"):
            return "end"
        if state.get("should_transition_to_synthesis"):
            return "synthesis"
        if state.get("iteration_count", 0) >= state.get("max_iterations", 15):
            return "synthesis"
        return "exploration"
    
    workflow.add_conditional_edges(
        "decision_maker",
        route_after_decision,
        {
            "exploration": "exploration_planner",
            "synthesis": "synthesis_planner",
            "end": END
        }
    )
    
    # Exploration loop
    workflow.add_edge("exploration_planner", "executor")
    
    # Synthesis → answer
    workflow.add_edge("synthesis_planner", "answer_generator")
    workflow.add_edge("answer_generator", END)
    
    return workflow.compile()
