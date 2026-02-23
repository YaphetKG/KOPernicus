import asyncio
import json
import logging
import re
from typing import Type
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel

from .state import (
    AgentState, Plan, ExplorationStep, SchemaAnalysis, CoverageAnalysis,
    LoopDetector, DecisionMaker, SynthesisPlan, AnswerOutput, QueryValidation,
    CommunityLog, AlignmentOutput, AnswerContract, InterpretedEvidence,
    InterpretedEvidenceList, NegativeKnowledge, HardConstraints,
    QueryClassification, PlanningPhase
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


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class LLMNode:
    """Base class for nodes that make a single structured LLM call.

    Subclasses declare three class attributes and implement ``__call__``:

    * ``prompt_template`` – the raw prompt string (with ``{format_instructions}``
      always injected automatically)
    * ``output_model``    – a Pydantic model class for structured output parsing
    * ``role``            – human-readable label (informational)

    Call ``await self._invoke(llm, key=val, ...)`` from ``__call__`` to build
    the chain, inject ``format_instructions``, and invoke.
    """

    role: str = ""
    prompt_template: str = ""
    output_model: Type[BaseModel] = None

    async def _invoke(self, llm, **kwargs) -> BaseModel:
        """Build chain, auto-inject format_instructions, and invoke."""
        parser = PydanticOutputParser(pydantic_object=self.output_model)
        chain = ChatPromptTemplate.from_template(self.prompt_template) | llm | parser
        return await chain.ainvoke({**kwargs, "format_instructions": parser.get_format_instructions()})

    async def _invoke_structured(self, llm, **kwargs) -> BaseModel:
        """Use with_structured_output(method="function_calling") — bypasses
        PydanticOutputParser format instructions without requiring strict JSON schema.

        Preferred for complex/nested models (AlignmentOutput, AnswerOutput) where
        the verbose PydanticOutputParser format instructions overflow the prompt, or
        where the model returns null when given large JSON format instructions.

        Uses function_calling mode explicitly to avoid OpenAI's strict-schema check
        which rejects Pydantic models with Optional/default fields.

        Raises ValueError if the LLM returns None (e.g. model doesn't support
        function calling or times out), so the calling node's except block handles
        it instead of crashing with a NoneType attribute error.
        """
        structured_llm = llm.with_structured_output(
            self.output_model, method="function_calling"
        )
        chain = ChatPromptTemplate.from_template(self.prompt_template) | structured_llm
        result = await chain.ainvoke({**kwargs, "format_instructions": ""})
        if result is None:
            raise ValueError(
                f"{self.role}: LLM returned None for structured output "
                "(function_calling mode). Model may not support tool calling."
            )
        return result

    async def __call__(self, state: AgentState, llm) -> dict:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# QueryValidatorNode  (not a graph node — called directly from main.py)
# ---------------------------------------------------------------------------

class QueryValidatorNode:
    """Validate user input before the graph runs.  Call ``.validate()`` directly."""

    role = "Input Validator"

    async def validate(self, user_input: str, llm) -> QueryValidation:
        parser = PydanticOutputParser(pydantic_object=QueryValidation)
        chain = ChatPromptTemplate.from_template(VALIDATION_PROMPT) | llm | parser
        try:
            result = await chain.ainvoke({
                "input": user_input,
                "format_instructions": parser.get_format_instructions()
            })
            logger.info(f"Query validation: {'VALID' if result.is_valid else 'INVALID'}")
            return result
        except Exception as e:
            logger.warning(f"Validation error: {e}")
            return QueryValidation(is_valid=True, feedback=user_input)


# ---------------------------------------------------------------------------
# Category A: Pure LLM nodes (minimal orchestration)
# ---------------------------------------------------------------------------

# Programmatic guard: allowlist of valid predicates per query type.
# Only "treatment" is restricted here — both its predicates are confirmed
# to exist in RoboKOP (see classifier prompt). Mechanism/association/hypothesis
# queries are NOT restricted because the valid predicate set is broader and
# less precisely known; the prompt's guidance is sufficient for those.
_VALID_PREDICATES_BY_TYPE = {
    "treatment": {
        "biolink:treats",
        "biolink:treats_or_applied_or_studied_to_treat",
    },
}


class QueryClassifierNode(LLMNode):
    """Define the Answer Contract for the query."""

    role = "Scientific Architect"
    prompt_template = QUERY_CLASSIFIER_PROMPT
    output_model = QueryClassification

    async def __call__(self, state: AgentState, llm) -> dict:
        try:
            result = await self._invoke(
                llm,
                input=state["input"],
                # Bug fix: QUERY_CLASSIFIER_PROMPT uses {approved_plan} but the old
                # function never passed it, causing a latent KeyError at runtime.
                approved_plan=state.get("plan_proposal", "None"),
            )
            contract_dict = result.contract.dict()

            # Programmatic predicate validation: remove predicates that don't belong
            # to the detected query type, preventing LLM from crossing category lines.
            query_type = contract_dict.get("query_type", "association")
            if query_type in _VALID_PREDICATES_BY_TYPE:
                allowed = _VALID_PREDICATES_BY_TYPE[query_type]
                original = contract_dict.get("required_predicates", [])
                filtered = [p for p in original if p in allowed]
                if not filtered:
                    # LLM gave no valid predicates — use first allowed as default
                    filtered = [next(iter(allowed))]
                if set(filtered) != set(original):
                    logger.warning(
                        f"Predicate validation removed invalid predicates "
                        f"{set(original) - set(filtered)} for {query_type} query"
                    )
                    contract_dict["required_predicates"] = filtered

            logger.info(f"Answer Contract Defined: {query_type} | predicates: {contract_dict['required_predicates']}")
            logger.debug(f"Full Answer Contract: {contract_dict}")
            return {
                # Preserve the original query captured by plan_proposer; don't
                # overwrite with "Proceed" / feedback text that arrives at approval time.
                "original_query": state.get("original_query") or state["input"],
                "answer_contract": contract_dict,
                "hard_constraints": HardConstraints().dict(),
            }
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            default_contract = AnswerContract(
                query_type="association",
                required_entity_types=["Entity"],
                required_predicates=["biolink:related_to"],
            )
            return {
                "answer_contract": default_contract.dict(),
                "hard_constraints": HardConstraints().dict(),
            }


class PlanGatekeeperNode(LLMNode):
    """Determine if the user approved the plan or provided feedback."""

    role = "Protocol Officer"
    prompt_template = PLAN_GATEKEEPER_PROMPT
    output_model = PlanningPhase

    async def __call__(self, state: AgentState, llm) -> dict:
        if not state.get("plan_proposal"):
            return {"is_plan_approved": False}

        try:
            result = await self._invoke(llm, input=state["input"])
            logger.info(f"Planning decision: {result.decision}")
            if result.decision == "approved":
                return {
                    "is_plan_approved": True,
                    "planning_feedback": "",
                    "response": "",  # Clear plan from response to allow research to proceed
                }
            else:
                return {
                    "is_plan_approved": False,
                    "planning_feedback": state["input"],
                }
        except Exception as e:
            logger.error(f"Plan gatekeeping failed: {e}")
            return {"is_plan_approved": False}


class PlannerNode(LLMNode):
    """Initial planner — creates exploration strategy."""

    role = "Principal Investigator"
    prompt_template = PLANNER_PROMPT
    output_model = Plan

    async def __call__(self, state: AgentState, llm) -> dict:
        try:
            result = await self._invoke(
                llm,
                input=state.get("original_query", state["input"]),
                north_star_plan=state.get("plan_proposal", "Follow general research principles."),
                contract=json.dumps(state.get("answer_contract", {}), indent=2),
            )
            logger.info(f"Initial step: {result.steps[0] if result.steps else 'None'}")
            logger.debug(f"Planner strategy: {result.strategy}")
            return {
                "plan": result.steps[:1],  # FORCED SINGLE STEP
                "exploration_strategy": result.strategy,
            }
        except Exception as e:
            logger.error(f"Planning failed (likely JSON error): {e}")
            return {
                "plan": [],
                "exploration_strategy": (
                    f"I encountered an error while planning: {e}. "
                    "Please try checking your input or rephrasing your request."
                ),
            }


class SchemaAnalyzerNode(LLMNode):
    """Extract schema patterns ONLY — no decisions."""

    role = "Data Structure Analyst"
    prompt_template = SCHEMA_EXTRACTOR_PROMPT
    output_model = SchemaAnalysis

    async def __call__(self, state: AgentState, llm) -> dict:
        last_evidence = state["evidence"][-1] if state["evidence"] else {}

        if last_evidence.get("tool") in ["name-resolver", "nodenormalizer"]:
            return {"schema_patterns": []}

        evidence_str = json.dumps(last_evidence, indent=2)
        if len(evidence_str) > 10000:
            evidence_str = evidence_str[:10000] + "...(truncated)"

        try:
            result = await self._invoke(llm, last_evidence=evidence_str)
            logger.info(f"Found {len(result.patterns)} schema patterns")
            logger.debug(f"Schema patterns: {result.patterns}")
            return {"schema_patterns": result.patterns}
        except Exception as e:
            logger.error(f"Schema analysis failed: {e}")
            return {"schema_patterns": []}


class CoverageAnalyzerNode(LLMNode):
    """Assess coverage ONLY — no decisions."""

    role = "Research Auditor"
    prompt_template = COVERAGE_ASSESSOR_PROMPT
    output_model = CoverageAnalysis

    async def __call__(self, state: AgentState, llm) -> dict:
        try:
            result = await self._invoke(
                llm,
                schema_patterns="\n".join(get_unique_schema(state.get("schema_patterns", []))),
                past_steps=str(state.get("past_steps", [])[-5:]),
                input=state["input"],
            )
            logger.info(f"Coverage score: {result.density_score}/10")
            return {"coverage_assessment": json.dumps(result.dict())}
        except Exception as e:
            logger.error(f"Coverage analysis failed: {e}")
            return {"coverage_assessment": json.dumps({"density_score": 5, "explored_predicates": []})}


class LoopDetectorNode(LLMNode):
    """Detect loops ONLY — no decisions."""

    role = "Methods Reviewer"
    prompt_template = LOOP_DETECTOR_PROMPT
    output_model = LoopDetector

    async def __call__(self, state: AgentState, llm) -> dict:
        recent_steps = state.get("past_steps", [])[-5:]
        try:
            result = await self._invoke(
                llm,
                recent_steps=str(recent_steps),
                schema_patterns="\n".join(get_unique_schema(state.get("schema_patterns", []))),
            )
            if result.is_looping:
                logger.warning(f"Loop detected: {result.repeated_pattern}")
            return {"loop_detection": json.dumps(result.dict())}
        except Exception as e:
            logger.error(f"Loop detection failed: {e}")
            return {"loop_detection": json.dumps({"is_looping": False, "recommendation": "Continue"})}


class SynthesisPlannerNode(LLMNode):
    """Plan how to answer the question."""

    role = "Senior Author"
    prompt_template = SYNTHESIS_PLANNER_PROMPT
    output_model = SynthesisPlan

    async def __call__(self, state: AgentState, llm) -> dict:
        pruned_evidence = prune_evidence(state.get("evidence", []))
        evidence_summary = "\n".join([
            f"- {e.get('tool', 'N/A')}: {str(e.get('data', ''))[:100]}..."
            for e in pruned_evidence
            if e.get("status") == "success"
        ])
        try:
            result = await self._invoke(
                llm,
                input=state["input"],
                evidence_summary=evidence_summary,
                schema_patterns="\n".join(get_unique_schema(state.get("schema_patterns", []))),
            )
            logger.info("Synthesis plan created")
            return {"plan": [f"Generate answer: {result.answer_structure}"]}
        except Exception as e:
            logger.error(f"Synthesis planning failed: {e}")
            return {"plan": ["Generate answer with available evidence"]}


class DecisionMakerNode(LLMNode):
    """Make phase decision based on Answer Contract satisfaction."""

    role = "Research Director"
    prompt_template = DECISION_MAKER_PROMPT
    output_model = DecisionMaker

    async def __call__(self, state: AgentState, llm) -> dict:
        contract = state.get("answer_contract", {})
        interpreted = state.get("interpreted_evidence", [])

        # Fix 3 + Fix 4: count trailing steps with no productive output.
        # A step is productive only if it starts with ✓ AND the tool returned
        # non-empty results. "No edges found" / "Found 0 results" count as failures
        # even though the tool itself didn't error — they yield zero evidence.
        _EMPTY_MARKERS = (
            "No edges found",
            "Found 0 results",
            "Found 0 edge",
            "--[unknown]--> Unknown",   # phantom edges with no resolved subject/object
        )
        def _is_productive(output: str) -> bool:
            if not isinstance(output, str) or not output.startswith("✓"):
                return False
            return not any(m in output for m in _EMPTY_MARKERS)

        past_steps = state.get("past_steps", [])
        consecutive_failures = 0
        for _, output in reversed(past_steps):
            if _is_productive(output):
                break
            consecutive_failures += 1

        # Hard override: if stuck for 3+ consecutive failures, stop regardless of LLM
        FRUSTRATION_THRESHOLD = 3
        if consecutive_failures >= FRUSTRATION_THRESHOLD and state.get("iteration_count", 0) > 2:
            decision = "synthesize" if interpreted else "stop"
            msg = (
                f"Forced {decision}: {consecutive_failures} consecutive steps produced no evidence. "
                "Escalating to avoid infinite loop."
            )
            logger.warning(msg)
            return {
                "should_explore_more": False,
                "should_transition_to_synthesis": decision == "synthesize",
                "ready_to_answer": True,
                "decision_reasoning": msg,
            }

        # N1: Count unique treatment entities already found so that the LLM can
        # compare against the contract's min_unique_entities threshold.
        required_preds = set(contract.get("required_predicates", []))
        unique_entities = len({
            e.get("subject_curie") or e.get("object_curie", "")
            for e in interpreted
            if e.get("predicate") in required_preds
        })
        min_unique = contract.get("min_unique_entities", 1)

        try:
            result = await self._invoke(
                llm,
                input=state.get("input", "Unknown Query"),
                contract=json.dumps(contract, indent=2),
                interpreted_evidence=json.dumps(interpreted, indent=2),
                consecutive_failures=consecutive_failures,
                unique_entities=unique_entities,
                min_unique_entities=min_unique,
            )
            ctrl = getattr(result, "control_decision", "explore")
            state_esc = getattr(result, "epistemic_state", "insufficient")
            reasoning = getattr(result, "reasoning", "Proceeding with exploration.")
            logger.info(f"Decision: {ctrl} (State: {state_esc})")
            logger.debug(f"Decision reasoning: {reasoning}")
            return {
                "should_explore_more": ctrl == "explore",
                "should_transition_to_synthesis": ctrl == "synthesize",
                "ready_to_answer": ctrl != "explore",
                "decision_reasoning": reasoning,
            }
        except Exception as e:
            logger.error(f"Decision making failed: {e}")
            at_limit = state.get("iteration_count", 0) >= state.get("max_iterations", 15)
            return {
                "should_explore_more": not at_limit,
                "should_transition_to_synthesis": at_limit,
                "ready_to_answer": at_limit,
                "decision_reasoning": (
                    f"Error in decision making: {e}. "
                    f"Defaulting to {'stop' if at_limit else 'continue'}."
                ),
            }


# ---------------------------------------------------------------------------
# Category B: LLM nodes with significant orchestration
# ---------------------------------------------------------------------------

class EvidenceInterpreterNode(LLMNode):
    """Interpret raw tool output and assign strength/type."""

    role = "Evidence Analyst"
    prompt_template = EVIDENCE_INTERPRETER_PROMPT
    output_model = InterpretedEvidenceList

    async def __call__(self, state: AgentState, llm) -> dict:
        if not state.get("evidence"):
            return {}

        last_raw = state["evidence"][-1]

        if last_raw.get("status") != "success":
            # Convert failures to negative knowledge
            neg = NegativeKnowledge(
                entity=str(last_raw.get("args", {}).get("curie", "unknown")),
                predicate=str(last_raw.get("args", {}).get("predicate", "unknown")),
                failure_reason=last_raw.get("data") or "Timeout/Error",
                iteration=state.get("iteration_count", 0),
            )
            return {"negative_knowledge": [neg.dict()]}

        try:
            # Only interpret edge tools — skip name-resolution as contract evidence
            if last_raw.get("tool") not in ["get_edges", "get_edges_between"]:
                return {}

            result = await self._invoke(
                llm,
                raw_evidence=json.dumps(last_raw, indent=2)[:5000],
                contract=json.dumps(state.get("answer_contract", {}), indent=2),
            )
            # result is InterpretedEvidenceList — return all items
            return {"interpreted_evidence": [item.dict() for item in result.items]}
        except Exception as e:
            logger.error(f"Evidence interpretation failed: {e}")
            return {}


def _extract_curies_from_evidence(evidence: list) -> dict:
    """Extract entity name→CURIE mappings from successful tool results.

    Used as a fallback when the alignment node hasn't run or has failed,
    so the exploration planner has real CURIEs to reference instead of
    hallucinating them from parametric memory.
    """
    curies = {}
    for item in evidence:
        if item.get("status") != "success":
            continue
        data = item.get("data")
        if not data:
            continue
        # Edge results (get_edges / get_edges_between): list of edge dicts
        if isinstance(data, list):
            for edge in data[:5]:
                if not isinstance(edge, dict):
                    continue
                for role in ("subject", "object"):
                    node = edge.get(role, {})
                    if isinstance(node, dict) and node.get("id"):
                        name = node.get("name", node["id"])
                        curies[name] = node["id"]
        # Edge summary results: dict with top-level curie
        elif isinstance(data, dict) and data.get("curie"):
            name = data.get("name", data["curie"])
            curies[name] = data["curie"]
    return curies


class ExplorationPlannerNode(LLMNode):
    """Plan the next exploration step."""

    role = "Exploration Strategist"
    prompt_template = EXPLORATION_PLANNER_PROMPT
    output_model = ExplorationStep

    async def __call__(self, state: AgentState, llm) -> dict:
        pruned_evidence = prune_evidence(state.get("evidence", []))
        evidence_summary = "\n".join([
            f"- {e.get('tool', 'N/A')}: {str(e.get('data', ''))[:400]}..."
            for e in pruned_evidence
            if e.get("status") == "success"
        ])

        log_data = state.get("community_log", {})
        if isinstance(log_data, str):
            try:
                log_data = json.loads(log_data)
            except Exception:
                log_data = {}

        novelty_budget = log_data.get("novelty_budget", 5)
        resolved = log_data.get("resolved_entities", {})

        # If alignment hasn't run or failed, extract CURIEs directly from evidence
        # to prevent the LLM from hallucinating entity identifiers.
        if not resolved:
            resolved = _extract_curies_from_evidence(state.get("evidence", []))
            if resolved:
                logger.info(
                    f"ExplorationPlanner: using {len(resolved)} CURIEs extracted "
                    "from evidence (alignment fallback)"
                )

        constraints = state.get("hard_constraints", {})
        failures = state.get("negative_knowledge", [])

        # Fix 2: surface the loop detector's concrete recommendation to the planner
        loop_data = json.loads(state.get("loop_detection", "{}"))
        loop_recommendation = loop_data.get("recommendation", "Continue")

        try:
            result = await self._invoke(
                llm,
                input=state.get("input", "Unknown Query"),
                evidence_summary=evidence_summary,
                contract=json.dumps(state.get("answer_contract", {}), indent=2),
                resolved_entities=json.dumps(resolved, indent=2),
                hard_constraints=json.dumps(constraints, indent=2),
                negative_knowledge=json.dumps(failures, indent=2),
                novelty_budget=novelty_budget,
                epistemic_status=state.get("decision_reasoning", "Starting exploration"),
                missing_fact="N/A",
                loop_recommendation=loop_recommendation,
            )
            action = getattr(result, "action", "Get edge summary for main entity")
            rationale = getattr(result, "rationale", "Exploring missing knowledge.")
            logger.info(f"Next exploration: {action}")
            logger.debug(f"Exploration rationale: {rationale}")
            return {"plan": [action], "planning_rationale": rationale}
        except Exception as e:
            logger.error(f"Exploration planning failed: {e}")
            return {
                "plan": ["Get edge summary for primary concept"],
                "planning_rationale": f"Defaulting to scouting due to planning error: {e}",
            }


class AlignmentNode(LLMNode):
    """Steward the Community Log (Shared Epistemology)."""

    role = "Alignment Coordinator"
    prompt_template = ALIGNMENT_PROMPT
    output_model = AlignmentOutput

    async def __call__(self, state: AgentState, llm) -> dict:
        current_log = state.get("community_log", {})
        if isinstance(current_log, str):
            try:
                current_log = json.loads(current_log)
            except Exception:
                current_log = {}

        step_count = len(state.get("past_steps", []))
        loop_data = json.loads(state.get("loop_detection", "{}"))
        is_looping = loop_data.get("is_looping", False)

        # Run at step 0, every 3 steps, or whenever looping is detected
        should_run = (step_count == 0) or (step_count % 3 == 0) or is_looping
        if not should_run and step_count > 0:
            logger.info("Alignment node skipping this turn (not triggered)")
            return {}

        pruned_evidence = prune_evidence(state.get("evidence", []))
        evidence_summary = "\n".join([
            f"- {e.get('tool', 'N/A')}: {str(e.get('data', ''))[:200]}..."
            for e in pruned_evidence
            if e.get("status") == "success"
        ])
        recent_steps = state.get("past_steps", [])[-5:]

        # Pass a compact summary of the log to avoid overwhelming the prompt
        compact_log = {
            "resolved_entities": current_log.get("resolved_entities", {}),
            "trajectory": current_log.get("trajectory", [])[-5:],
            "novelty_budget": current_log.get("novelty_budget", 5),
            "open_questions": current_log.get("open_questions", [])[-3:],
            "hypotheses": [h.get("statement", "") for h in current_log.get("hypotheses", [])[-3:]],
            "deprioritized_paths": current_log.get("deprioritized_paths", [])[-3:],
        }

        try:
            result = await self._invoke_structured(
                llm,
                community_log=json.dumps(compact_log, indent=2),
                recent_steps=str(recent_steps),
                evidence_summary=evidence_summary,
                loop_detection=state.get("loop_detection", "{}"),
            )
            logger.info(f"Alignment Update: {result.updates_made}")
            return {
                "community_log": result.updated_log.dict(),
                "hard_constraints": result.hard_constraints.dict(),
            }
        except Exception as e:
            logger.error(f"Alignment failed: {e}")
            return {}


class AnswerGeneratorNode(LLMNode):
    """Generate final answer with proper citations."""

    role = "Scientific Writer"
    prompt_template = ANSWER_GENERATOR_PROMPT
    output_model = AnswerOutput

    async def __call__(self, state: AgentState, llm) -> dict:
        successful_evidence = [
            e for e in state.get("evidence", [])
            if e.get("status") == "success"
        ]

        # Fix 5: cap evidence to the 15 most recent items and truncate each
        # item's data field so the payload stays within LLM context limits.
        MAX_EVIDENCE_ITEMS = 15
        MAX_DATA_CHARS = 2000
        MAX_TOTAL_CHARS = 30_000
        if len(successful_evidence) > MAX_EVIDENCE_ITEMS:
            logger.info(
                f"Capping evidence from {len(successful_evidence)} to "
                f"{MAX_EVIDENCE_ITEMS} items for answer generation"
            )
            successful_evidence = successful_evidence[-MAX_EVIDENCE_ITEMS:]

        def _truncate_item(e: dict) -> dict:
            if "data" in e and e["data"] is not None:
                return {**e, "data": str(e["data"])[:MAX_DATA_CHARS]}
            return e

        full_evidence = "\n\n".join([
            f"Evidence {i+1}:\n{json.dumps(_truncate_item(e), indent=2)}"
            for i, e in enumerate(successful_evidence)
        ])
        if len(full_evidence) > MAX_TOTAL_CHARS:
            full_evidence = full_evidence[:MAX_TOTAL_CHARS] + "\n...(truncated)"

        # Extract subgraph from edge lists
        nodes = {}
        edges = []
        for item in successful_evidence:
            tool = item.get("tool")
            data = item.get("data")
            if not data:
                continue
            try:
                if tool in ["get_edges", "get_edges_between"] and isinstance(data, list):
                    for edge in data:
                        if "subject" in edge:
                            s = edge["subject"]
                            if isinstance(s, dict) and "id" in s:
                                nodes[s["id"]] = {
                                    "id": s["id"],
                                    "name": s.get("name", s["id"]),
                                    "type": s.get("category", ["Entity"])[0],
                                }
                        if "object" in edge:
                            o = edge["object"]
                            if isinstance(o, dict) and "id" in o:
                                nodes[o["id"]] = {
                                    "id": o["id"],
                                    "name": o.get("name", o["id"]),
                                    "type": o.get("category", ["Entity"])[0],
                                }
                        if "predicate" in edge and "subject" in edge and "object" in edge:
                            edges.append({
                                "source": edge["subject"]["id"],
                                "target": edge["object"]["id"],
                                "label": edge["predicate"],
                                "id": edge.get(
                                    "id",
                                    f"{edge['subject']['id']}-{edge['predicate']}-{edge['object']['id']}",
                                ),
                            })
                elif tool == "get_node" and isinstance(data, dict):
                    if "id" in data:
                        nodes[data["id"]] = {
                            "id": data["id"],
                            "name": data.get("name", data["id"]),
                            "type": data.get("category", ["Entity"])[0],
                        }
            except Exception as ex:
                logger.warning(f"Error extracting subgraph from {tool}: {ex}")

        critical_subgraph = {"nodes": list(nodes.values()), "edges": edges}
        # Use the LAST plan entry — SynthesisPlannerNode appends its plan to the list,
        # so plan[-1] is the synthesis outline, not plan[0] which is an exploration step.
        plan_list = state.get("plan", ["Answer the question"])
        synthesis_plan = plan_list[-1] if plan_list else "Answer the question"

        try:
            result = await self._invoke_structured(
                llm,
                input=state["input"],
                synthesis_plan=synthesis_plan,
                full_evidence=full_evidence,
            )
            logger.info(f"Answer generated (confidence: {result.confidence})")
            response = f"{result.answer}\n\n"
            if result.confidence != "high":
                response += f"**Confidence**: {result.confidence}\n"
            if result.limitations != "None":
                response += f"**Limitations**: {result.limitations}"
            return {"response": response, "plan": [], "critical_subgraph": critical_subgraph}
        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return {
                "response": f"Based on collected evidence: {str(successful_evidence[:2])[:500]}...",
                "plan": [],
                "critical_subgraph": {"nodes": [], "edges": []},
            }


# ---------------------------------------------------------------------------
# Category C: Standalone nodes (do not extend LLMNode)
# ---------------------------------------------------------------------------

class PlanProposerNode:
    """Generate or update the 'North Star' plan proposal.

    Uses raw ``llm.ainvoke()`` (no Pydantic parser) — the output is free-form
    markdown returned directly to the user.
    """

    role = "Research Planner"

    async def __call__(self, state: AgentState, llm) -> dict:
        prompt = ChatPromptTemplate.from_template(PLAN_PROPOSAL_PROMPT)
        proposer = prompt | llm

        logger.info(f"Generating plan. Feedback: {state.get('planning_feedback', 'None')}")
        try:
            response = await proposer.ainvoke({
                "original_query": state.get("original_query", state.get("input", "Unknown Query")),
                "previous_plan": state.get("plan_proposal", "None"),
                "feedback": state.get("planning_feedback", "Initial proposal"),
            })

            plan = response.content.strip()
            if not plan:
                logger.warning("LLM returned empty plan proposal!")
                plan = state.get("plan_proposal", "Error generating updated plan.")

            logger.info(f"Plan proposal generated (length: {len(plan)})")
            result = {"plan_proposal": plan, "response": plan}
            # Capture original_query on first run so it survives the plan-approval
            # round-trip (where state["input"] becomes "Proceed" / feedback text).
            if not state.get("original_query"):
                result["original_query"] = state.get("input", "Unknown Query")
            return result
        except Exception as e:
            logger.error(f"Plan proposal failed: {e}")
            error_msg = (
                f"I encountered an error generating the plan: {e}. "
                "Please try giving a simpler instruction."
            )
            return {"plan_proposal": state.get("plan_proposal", "Error"), "response": error_msg}


class ExecutorNode:
    """Execute a single step from the plan.

    Uses ``llm.bind_tools()`` rather than a prompt template, so it does not
    extend ``LLMNode``.  All constraint enforcement logic lives here.
    """

    role = "Tool Executor"

    async def __call__(self, state: AgentState, llm, tools) -> dict:
        plan = state["plan"]
        if not plan:
            logger.error("Empty plan in executor")
            return {
                "past_steps": [("ERROR", "No plan")],
                "evidence": [{"step": "ERROR", "status": "failed", "data": "No plan"}],
            }

        task = plan[0]
        logger.info(f"Executing: {task}")
        logger.debug(f"Executor received task: {task}. Plan length: {len(plan)}")

        llm_with_tools = llm.bind_tools(tools)
        system_msg = SystemMessage(content=f"Execute this task using available tools: {task}")

        try:
            response = await llm_with_tools.ainvoke([system_msg])
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return {
                "past_steps": [(task, f"LLM Error: {e}")],
                "evidence": [{"step": task, "status": "error", "error_type": "llm_failed", "data": str(e)}],
            }

        evidence_item = {"step": task, "status": "failed", "data": None}
        output_text = ""

        if response.tool_calls:
            tool_call = response.tool_calls[0]
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            selected_tool = next((t for t in tools if t.name == tool_name), None)

            if selected_tool:
                # --- Hard Constraint Enforcement ---
                constraints = state.get("hard_constraints", {})
                forbidden_preds = constraints.get("forbidden_predicates", [])
                forbidden_entities = constraints.get("forbidden_entities", [])
                forbidden_continuations = constraints.get("forbidden_continuations", [])

                if tool_name in ["get_edges", "get_edge_summary"]:
                    pred = tool_args.get("predicate")
                    source = (
                        tool_args.get("curie")        # primary MCP parameter name
                        or tool_args.get("source_node")
                        or tool_args.get("subject")
                        or tool_args.get("source")
                    )

                    # 1. Global predicate ban
                    if pred and pred in forbidden_preds:
                        error_msg = f"Action blocked: The predicate '{pred}' is globally forbidden."
                        logger.warning(error_msg)
                        return {
                            "past_steps": [(task, error_msg)],
                            "evidence": [{"step": task, "status": "failed", "data": error_msg}],
                        }

                    # 2. Granular triple ban (source + predicate)
                    if pred and source:
                        for fc in forbidden_continuations:
                            if fc.get("source") == source and fc.get("predicate") == pred:
                                error_msg = (
                                    f"Action blocked: The path {source} --[{pred}]--> * "
                                    "is forbidden due to loops."
                                )
                                logger.warning(error_msg)
                                return {
                                    "past_steps": [(task, error_msg)],
                                    "evidence": [{"step": task, "status": "failed", "data": error_msg}],
                                }

                # Entity ban (source or target)
                for arg_val in tool_args.values():
                    if isinstance(arg_val, str) and arg_val in forbidden_entities:
                        error_msg = f"Action blocked: The entity '{arg_val}' is globally forbidden."
                        logger.warning(error_msg)
                        return {
                            "past_steps": [(task, error_msg)],
                            "evidence": [{"step": task, "status": "failed", "data": error_msg}],
                        }
                # -----------------------------------

                try:
                    tool_result = await self._invoke_tool(selected_tool, tool_name, tool_args)
                    evidence_item = {
                        "step": task,
                        "tool": tool_name,
                        "args": tool_args,
                        "status": "success",
                        "data": tool_result,
                    }
                    if isinstance(tool_result, list):
                        text_parts = []
                        for item in tool_result:
                            if isinstance(item, dict) and "text" in item:
                                text_parts.append(item["text"])
                            else:
                                text_parts.append(str(item))
                        result_str = "\n".join(text_parts)
                    else:
                        result_str = str(tool_result)

                    result_snippet = result_str[:2000].replace("\n", " ")
                    output_text = f"✓ {tool_name}: {result_snippet}..."
                    logger.info("Tool executed successfully")
                    logger.debug(f"Tool {tool_name} returned data length: {len(str(tool_result))}")

                    # Auto-normalization: after a successful lookup (name-resolver),
                    # immediately normalize the returned CURIEs in code rather than
                    # relying on the LLM to schedule a follow-up nodenormalizer call.
                    if tool_name == "lookup":
                        norm_evidence, norm_text = await self._auto_normalize(
                            tools, result_str, task
                        )
                        if norm_evidence:
                            return {
                                "past_steps": [(task, output_text), (task, norm_text)],
                                "evidence": [evidence_item, norm_evidence],
                            }
                except Exception as e:
                    err_str = str(e)
                    err_type_name = type(e).__name__
                    error_type = "timeout" if "timeout" in err_str.lower() else "execution_error"
                    evidence_item = {
                        "step": task,
                        "tool": tool_name,
                        "args": tool_args,
                        "status": "error",
                        "error_type": error_type,
                        "data": f"{err_type_name}: {err_str}",
                    }
                    output_text = f"✗ {tool_name}: {err_type_name}: {err_str}"
                    logger.error(f"Tool error ({err_type_name}): {err_str}")
            else:
                evidence_item = {
                    "step": task,
                    "status": "error",
                    "error_type": "tool_not_found",
                    "data": f"Tool {tool_name} not available",
                }
                output_text = f"Tool not found: {tool_name}"
        else:
            evidence_item["data"] = response.content
            output_text = "No tool call generated"

        return {"past_steps": [(task, output_text)], "evidence": [evidence_item]}

    async def _invoke_tool(self, tool, tool_name: str, tool_args: dict):
        """Invoke a tool with one automatic retry for the lookup (name-resolver) tool.

        Network timeouts on lookup are common and transient; a single retry
        recovers most cases without wasting a full exploration step.
        """
        try:
            return await tool.ainvoke(tool_args)
        except Exception as first_err:
            if tool_name != "lookup":
                raise
            err_type = type(first_err).__name__
            logger.warning(
                f"lookup failed ({err_type}: {first_err}), retrying in 3 s..."
            )
            await asyncio.sleep(3)
            return await tool.ainvoke(tool_args)   # let the caller handle a second failure

    async def _auto_normalize(self, tools, lookup_result_str: str, task: str):
        """After a successful lookup, extract CURIEs and call get_normalized_nodes.

        Returns (evidence_item, output_text) if normalization succeeded, else (None, "").
        The caller is responsible for injecting both into the state return.
        """
        # Extract CURIE-like tokens: PREFIX:DIGITS (e.g. MONDO:0005148, CHEBI:6801)
        raw_curies = re.findall(r'\b([A-Z][A-Z0-9]+:\d+)\b', lookup_result_str)
        # Deduplicate while preserving order; take top 5 to avoid oversized payloads
        seen = set()
        curies = []
        for c in raw_curies:
            if c not in seen:
                seen.add(c)
                curies.append(c)
            if len(curies) >= 5:
                break

        if not curies:
            return None, ""

        normalizer = next((t for t in tools if t.name == "get_normalized_nodes"), None)
        if not normalizer:
            return None, ""

        try:
            norm_result = await normalizer.ainvoke({"curies": curies})
            if isinstance(norm_result, list):
                norm_str = "\n".join(
                    item["text"] if isinstance(item, dict) and "text" in item else str(item)
                    for item in norm_result
                )
            else:
                norm_str = str(norm_result)

            norm_evidence = {
                "step": task,
                "tool": "get_normalized_nodes",
                "args": {"curies": curies},
                "status": "success",
                "data": norm_result,
            }
            norm_text = f"✓ get_normalized_nodes (auto): {norm_str[:500].replace(chr(10), ' ')}..."
            logger.info(f"Auto-normalized {len(curies)} CURIE(s): {curies}")
            return norm_evidence, norm_text
        except Exception as e:
            logger.warning(f"Auto-normalization failed: {e}")
            return None, ""

