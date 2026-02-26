from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from .state import AgentState, InputState
from .nodes import (
    QueryClassifierNode, PlannerNode, ExecutorNode, EvidenceInterpreterNode,
    SchemaAnalyzerNode, CoverageAnalyzerNode, LoopDetectorNode, AlignmentNode,
    DecisionMakerNode, ExplorationPlannerNode, SynthesisPlannerNode,
    AnswerGeneratorNode, PlanProposerNode, PlanGatekeeperNode,
)
from .llm import LLMFactory

def create_agent_graph(llm, tools):
    # Instantiate node classes
    _query_classifier  = QueryClassifierNode()
    _planner           = PlannerNode()
    _executor          = ExecutorNode()
    _evidence_interp   = EvidenceInterpreterNode()
    _schema_analyzer   = SchemaAnalyzerNode()
    _coverage_analyzer = CoverageAnalyzerNode()
    _loop_detector     = LoopDetectorNode()
    _alignment         = AlignmentNode()
    _decision_maker    = DecisionMakerNode()
    _exploration_plan  = ExplorationPlannerNode()
    _synthesis_plan    = SynthesisPlannerNode()
    _answer_gen        = AnswerGeneratorNode()
    _plan_proposer     = PlanProposerNode()
    _plan_gatekeeper   = PlanGatekeeperNode()

    # Bind node instances to the graph (same lambda pattern as before)
    async def planner(state):            return await _planner(state, llm)
    async def executor(state):           return await _executor(state, llm, tools)
    async def schema_analyzer(state):    return await _schema_analyzer(state, llm)
    async def coverage_analyzer(state):  return await _coverage_analyzer(state, llm)
    async def loop_detector(state):      return await _loop_detector(state, llm)
    async def alignment(state):          return await _alignment(state, llm)
    async def decision_maker(state):
        result = await _decision_maker(state, llm)
        result["iteration_count"] = state.get("iteration_count", 0) + 1
        return result
    async def exploration_planner(state): return await _exploration_plan(state, llm)
    async def synthesis_planner(state):   return await _synthesis_plan(state, llm)
    async def answer_generator(state):    return await _answer_gen(state, llm)
    async def query_classifier(state):    return await _query_classifier(state, llm)
    async def evidence_interpreter(state): return await _evidence_interp(state, llm)
    async def plan_proposer(state):       return await _plan_proposer(state, llm)
    async def plan_gatekeeper(state):     return await _plan_gatekeeper(state, llm)

    # Build graph with clear flow
    workflow = StateGraph(AgentState, input=InputState, output=AgentState)

    # Add all nodes
    workflow.add_node("planner", planner)
    workflow.add_node("executor", executor)
    workflow.add_node("schema_analyzer", schema_analyzer)
    workflow.add_node("coverage_analyzer", coverage_analyzer)
    workflow.add_node("loop_detector", loop_detector)
    workflow.add_node("alignment", alignment)
    workflow.add_node("decision_maker", decision_maker)
    workflow.add_node("exploration_planner", exploration_planner)
    workflow.add_node("synthesis_planner", synthesis_planner)
    workflow.add_node("answer_generator", answer_generator)
    workflow.add_node("query_classifier", query_classifier)
    workflow.add_node("evidence_interpreter", evidence_interpreter)
    workflow.add_node("plan_proposer", plan_proposer)
    workflow.add_node("plan_gatekeeper", plan_gatekeeper)

    workflow.set_entry_point("plan_gatekeeper")

    # Gatekeeper decision
    def route_planning(state: AgentState):
        if not state.get("plan_proposal"):
            # First turn: no plan yet — propose one directly, no contract needed yet
            return "plan_proposer"
        if state.get("is_plan_approved"):
            # Plan approved: now generate the answer contract informed by the plan
            return "query_classifier"
        # Plan exists but not approved: user gave feedback — revise it
        return "plan_proposer"

    workflow.add_conditional_edges(
        "plan_gatekeeper",
        route_planning,
        {
            "query_classifier": "query_classifier",
            "plan_proposer": "plan_proposer",
        }
    )

    # Plan Proposal -> END (Wait for user)
    workflow.add_edge("plan_proposer", END)

    # Classification (post-approval) -> planner
    workflow.add_edge("query_classifier", "planner")

    # Approved plan → execute opening
    workflow.add_edge("planner", "executor")

    # After execution → Interpretation → Analysis
    workflow.add_edge("executor", "evidence_interpreter")
    workflow.add_edge("evidence_interpreter", "schema_analyzer")
    workflow.add_edge("schema_analyzer", "coverage_analyzer")
    workflow.add_edge("coverage_analyzer", "loop_detector")
    workflow.add_edge("loop_detector", "alignment")
    workflow.add_edge("alignment", "decision_maker")

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
            "end": END,
        }
    )

    # Exploration loop
    workflow.add_edge("exploration_planner", "executor")

    # Synthesis → answer
    workflow.add_edge("synthesis_planner", "answer_generator")
    workflow.add_edge("answer_generator", END)

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)
