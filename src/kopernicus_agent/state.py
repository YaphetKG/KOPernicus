import operator
from typing import Annotated, List, Tuple, Dict, Literal
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

class AgentState(TypedDict):
    input: str
    plan: List[str]
    past_steps: Annotated[List[Tuple], operator.add]
    evidence: Annotated[List[Dict], operator.add]
    
    # NEW: Separate tracking for different analysis tasks
    schema_patterns: Annotated[List[str], operator.add]  # What patterns exist?
    coverage_assessment: str  # How well have we explored?
    loop_detection: str  # Are we repeating ourselves?
    
    # Decision signals
    should_explore_more: bool
    should_transition_to_synthesis: bool
    ready_to_answer: bool
    
    # Planning
    exploration_strategy: str  # Current exploration approach
    
    # Final output
    response: str
    iteration_count: int
    max_iterations: int

class Plan(BaseModel):
    """Initial exploration plan"""
    steps: List[str] = Field(description="Ordered steps for initial exploration")
    strategy: str = Field(description="High-level strategy (e.g., 'depth-first on treats relation')")

class ExplorationStep(BaseModel):
    """Next step in exploration"""
    action: str = Field(description="Single, specific action to take next")
    rationale: str = Field(description="Why this step (1 sentence)")

class SchemaAnalysis(BaseModel):
    """Pure schema extraction - NO decision making"""
    patterns: List[str] = Field(
        description="Concrete patterns found (e.g., 'ChemicalEntity -[biolink:treats]-> Disease')"
    )
    new_predicates_discovered: List[str] = Field(
        description="New predicate types discovered in latest evidence",
        default_factory=list
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
    """PURE decision logic based on analyses"""
    should_explore_more: bool = Field(
        description="True if we need more data coverage"
    )
    should_transition_to_synthesis: bool = Field(
        description="True if we have enough to answer"
    )
    reasoning: str = Field(
        description="1-2 sentence explanation of decision"
    )

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

class QueryValidation(BaseModel):
    is_valid: bool
    feedback: str
