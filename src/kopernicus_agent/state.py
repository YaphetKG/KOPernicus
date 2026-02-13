import operator
from typing import Annotated, List, Tuple, Dict, Literal
from pydantic import BaseModel, Field
from typing_extensions import TypedDict, NotRequired

class InputState(TypedDict):
    input: str

class AgentState(TypedDict):
    input: str
    original_query: NotRequired[str]
    plan: NotRequired[List[str]]
    past_steps: NotRequired[Annotated[List[Tuple], operator.add]]
    evidence: NotRequired[Annotated[List[Dict], operator.add]]
    
    # NEW: Separate tracking for different analysis tasks
    schema_patterns: NotRequired[Annotated[List[str], operator.add]]  # What patterns exist?
    coverage_assessment: NotRequired[str]  # How well have we explored?
    loop_detection: NotRequired[str]  # Are we repeating ourselves?
    
    # Decision signals
    should_explore_more: NotRequired[bool]
    should_transition_to_synthesis: NotRequired[bool]
    ready_to_answer: NotRequired[bool]
    
    # Reasons/Rationales
    decision_reasoning: NotRequired[str]
    planning_rationale: NotRequired[str]
    
    # Planning
    exploration_strategy: NotRequired[str]  # Current exploration approach
    
    # Final output
    response: NotRequired[str]
    iteration_count: NotRequired[int]
    max_iterations: NotRequired[int]
    
    # v5 Epistemic Control
    answer_contract: NotRequired[Dict]
    interpreted_evidence: NotRequired[Annotated[List[Dict], operator.add]]
    negative_knowledge: NotRequired[Annotated[List[Dict], operator.add]]
    hard_constraints: NotRequired[Dict]
    
    # v4 Shared Artifact (Normalized)
    community_log: NotRequired[Dict] 

    # Interactive Planning
    plan_proposal: NotRequired[str]
    is_plan_approved: NotRequired[bool]
    planning_feedback: NotRequired[str]

class Plan(BaseModel):
    """Initial exploration plan"""
    steps: List[str] = Field(description="Ordered steps for initial exploration")
    strategy: str = Field(description="High-level strategy (e.g., 'depth-first on treats relation')")

class ExplorationStep(BaseModel):
    """Next step in exploration"""
    action: str = Field(description="Single, specific action to take next")
    rationale: str = Field(description="Why this step (1 sentence)")

class SchemaAnalysis(BaseModel):
    """Extraction of relationship patterns"""
    patterns: List[str] = Field(
        description="Patterns found (e.g., 'Type -[pred]-> Type')"
    )

class CoverageAnalysis(BaseModel):
    """Assess exploration coverage - NO decision making"""
    explored_predicates: List[str] = Field(description="All predicates we've tried")
    unexplored_promising_predicates: List[str] = Field(
        description="Predicates we should try based on schema",
        default_factory=list
    )
    density_score: int = Field(
        description="0-10: How much data have we collected?",
        ge=0, le=10
    )
    
class LoopDetector(BaseModel):
    """Detect if we're stuck - NO decision making"""
    is_looping: bool = Field(description="Are we repeating the same failed steps?")
    repeated_pattern: str = Field(
        description="Description of what's repeating (or 'None')",
        default="None"
    )
    recommendation: str = Field(
        description="If looping, what should change? (or 'Continue')"
    )

class DecisionMaker(BaseModel):
    """Decision logic for graph navigation"""
    epistemic_state: Literal["insufficient", "mechanistic", "direct"]
    publication_tier: Literal["Gold", "Silver", "Bronze"]
    control_decision: Literal["explore", "synthesize", "stop"]
    reasoning: str
    missing_explanatory_fact: str = Field(default="None")

class SynthesisPlan(BaseModel):
    """How to formulate the answer"""
    answer_structure: str = Field(
        description="Outline: what sections/points to cover"
    )
    evidence_needed: List[str] = Field(
        description="Which evidence items to cite"
    )

class AnswerOutput(BaseModel):
    """Final answer with proper citations"""
    answer: str = Field(
        description="Complete answer to user query. MUST cite CURIEs for every entity mentioned."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence in answer based on evidence quality"
    )
    limitations: str = Field(
        description="What's missing or uncertain",
        default="None"
    )
    critical_subgraph: Dict = Field(
        description="The subgraph of evidence used for the answer, containing nodes and edges",
        default_factory=dict
    )

class QueryValidation(BaseModel):
    is_valid: bool
    feedback: str

class BiologicalHypothesis(BaseModel):
    id: str # e.g., "H1"
    statement: str # "We suspect Metformin modulates AMPK pathway"
    status: Literal["Provisional", "Validated", "Refuted"]
    support: str # Brief citation of evidence step

class HardConstraints(BaseModel):
    """Enforceable constraints for the planner"""
    forbidden_entities: List[str] = Field(default_factory=list)
    forbidden_predicates: List[str] = Field(default_factory=list)
    locked_anchor_entities: List[str] = Field(default_factory=list)

class CommunityLog(BaseModel):
    # Resolved Anchors: Immutable once set
    resolved_entities: Dict[str, str] = Field(default_factory=dict, description="Name -> CURIE map. e.g. {'Diabetes': 'MONDO:123'}")
    
    # Exploration Trajectory
    trajectory: List[str] = Field(default_factory=list, description="High-level summary of directions tried")
    deprioritized_paths: List[str] = Field(default_factory=list, description="Directions we explicitly gave up on")
    
    # Hypotheses
    hypotheses: List[BiologicalHypothesis] = Field(default_factory=list)
    
    # State of Belief
    open_questions: List[str] = Field(default_factory=list)
    novelty_budget: int = Field(default=5, description="1-10 scale. 1=Conservative/Verification, 10=Wild Speculation")
    
    # Narrative Reframing
    global_goal_reframed: str = Field(default="", description="The current evolving story/goal")

class AlignmentOutput(BaseModel):
    """Output from Alignment Node (Steward) to update the log"""
    updated_log: CommunityLog
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    updates_made: str = Field(description="Description of what changed in the log")

class AnswerContract(BaseModel):
    """The 'Definition of Done' for the current query"""
    query_type: Literal["treatment", "mechanism", "association", "hypothesis"]
    required_entity_types: List[str]
    required_predicates: List[str]
    min_path_length: int = 1
    max_path_length: int = 3
    requires_direct_evidence: bool = False

class InterpretedEvidence(BaseModel):
    """Evidence with scientific weight and interpretation"""
    subject_curie: str
    predicate: str
    object_curie: str
    evidence_type: Literal["direct", "mechanistic", "associative"]
    strength_score: int = Field(ge=1, le=5)
    source_step: str
    rationale: str

class NegativeKnowledge(BaseModel):
    """Knowledge of what DOES NOT work or exist"""
    entity: str
    predicate: str
    failure_reason: str
    iteration: int


class QueryClassification(BaseModel):
    """Output of the query classifier"""
    contract: AnswerContract
    reasoning: str

class PlanningPhase(BaseModel):
    """Decision from the gatekeeper"""
    decision: Literal["approved", "feedback"]
