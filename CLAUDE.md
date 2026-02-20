# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KOPernicus is an AI-powered biomedical research agent that explores knowledge graphs (RoboKOP) to answer complex research questions. It uses a decomposed, multi-specialist node architecture built on LangGraph with MCP (Model Context Protocol) servers for accessing biomedical knowledge graph services.

## Commands

### Python (uses `uv` for package management)

```bash
uv sync                          # Install/sync dependencies
uv run -m src.kopernicus_agent.main          # Interactive CLI mode
uv run -m src.kopernicus_agent.main "query"  # Single-query mode
uv run python -m kopernicus_agent.server     # Start FastAPI backend (port 8822)
```

### Testing

```bash
python test_nodes.py              # Unit tests for node constraint enforcement
python verify_planning_flow.py    # Test plan approval flow
python verify_json_hardening.py   # Test JSON parsing resilience
```

### Frontend (React + Vite)

```bash
cd ui && npm install   # Install dependencies
cd ui && npm run dev   # Dev server (port 5173)
cd ui && npm run lint  # ESLint
cd ui && npm run build # Production build
```

## Architecture

### LangGraph State Machine (workflow.py)

The agent is a directed graph of 14 specialist nodes. Execution flow:

```
plan_gatekeeper
  ├─→ plan_proposer → END (wait for user plan approval, then re-enter)
  └─→ planner → executor → evidence_interpreter → schema_analyzer
                        → coverage_analyzer → loop_detector
                        → alignment (every 3 steps or on loop)
                        → decision_maker
                              ├─→ explore: exploration_planner → executor (loop)
                              ├─→ synthesize: synthesis_planner → answer_generator → END
                              └─→ stop: END
```

The graph uses LangGraph's `MemorySaver` for stateful multi-turn interactions. The `plan_gatekeeper` node is the entry point that routes based on whether a plan has been approved.

### State (state.py)

`AgentState` is a `TypedDict` where list fields use `operator.add` for accumulation across node executions. Key fields:
- `evidence`: Accumulated tool results, pruned to 20 most relevant items
- `schema_patterns`: Discovered `SubjectType -[predicate]-> ObjectType` relationships
- `community_log`: Shared context (resolved CURIEs, trajectory, hypotheses, hard constraints)
- `hard_constraints`: Forbidden predicates/entities/continuations enforced in executor
- `past_steps`: Tuple list of `(task, output_text)` for history
- `plan_approved`: Boolean gate controlling the gatekeeper routing

All structured node outputs are Pydantic models (20+ defined in `state.py`) parsed via `llm.with_structured_output()`.

### Nodes (nodes.py)

Each node receives the full `AgentState` and returns a dict with only the fields it updates. Key behaviors:
- **executor_node**: Enforces `hard_constraints` before tool calls; blocked tools raise an error instead of executing
- **alignment_node**: Runs every 3 executor steps or when a loop is detected; updates `community_log` and sets `hard_constraints`
- **plan_proposer_node**: Interactive — emits a plan and pauses; user feedback is fed back in as the next message

### Prompts (prompts.py)

Each node has a domain-specific system prompt assigning a "role" (e.g., "Scientific Intake Officer", "Research Director"). All prompts share `MISSION_CONTEXT` preamble establishing the community ethos. Prompts are the primary way to tune node behavior.

### LLM Configuration (llm.py)

`LLMFactory.get_llm(provider)` supports `openai` (default), `gemini`, `azure`. Temperature is 0 for deterministic structured outputs. Default points to a local vLLM instance at `localhost:9777`.

### MCP Integration

MCP servers are defined in `mcp-config.json` (stdio transport). The `langchain-mcp-adapters` package loads them at startup in `main.py` and `server.py`. Four servers: `biolink`, `name-resolver`, `nodenormalizer`, `robokop`.

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai`, `gemini`, or `azure` | `openai` |
| `OPENAI_BASE_URL` | LLM endpoint | `http://localhost:9777/v1` |
| `OPENAI_MODEL` | Model ID | `openai/gpt-oss-20b` |
| `OPENAI_API_KEY` | API key | `EMPTY` |
| `GOOGLE_API_KEY` | For Gemini | — |
| `LANGFUSE_*` | Observability (optional) | — |

## Key Design Decisions

- **Hard constraints in executor**: The executor checks `community_log.hard_constraints` before every tool call and raises a descriptive error (not silently skips) when a forbidden predicate/entity/continuation is attempted. This surfaces constraint violations in `past_steps` for the decision maker to see.
- **Evidence pruning**: `prune_evidence()` in `utils.py` keeps only the 20 highest-relevance evidence items to prevent context bloat.
- **Plan gate**: The workflow is designed to pause at `plan_proposer` and resume from `plan_gatekeeper` when the user provides feedback or approval. The `plan_approved` field in state controls this routing.
- **Alignment cadence**: `alignment_node` is triggered by `decision_maker` on a counter or loop signal, not after every step, to avoid re-running expensive LLM calls unnecessarily.
- **Python version**: Requires Python 3.13+ (enforced via `.python-version`).
