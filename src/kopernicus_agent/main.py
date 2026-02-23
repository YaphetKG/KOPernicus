import asyncio
import json
import logging
import traceback
import sys
import os
import argparse
from pathlib import Path
from langchain_mcp_adapters.client import MultiServerMCPClient

from .llm import LLMFactory
from .workflow import create_agent_graph
from .nodes import QueryValidatorNode
from .utils import setup_langfuse_tracing
from .logging_config import setup_logging

# --- Setup Logging ---
logger = setup_logging()

def get_mcp_client():
    # Try current directory first, then package directory
    config_path = Path('mcp-config.json')
    if not config_path.exists():
        config_path = Path(__file__).parent / 'mcp-config.json'
    
    if not config_path.exists():
        # Fallback to src if running from there
        config_path = Path(__file__).parent.parent / 'mcp-config.json'

    if not config_path.exists():
        # Fallback to project root (src/../)
        config_path = Path(__file__).parent.parent.parent / 'mcp-config.json'

    if not config_path.exists():
        raise FileNotFoundError("Could not find mcp-config.json")

    with open(config_path, 'r') as file:
        mcp_config = json.load(file)
    return MultiServerMCPClient(mcp_config["mcpServers"])

async def main(query: str = None, auto_approve: bool = False):
    
    try:
        mcp_client = get_mcp_client()
        tools = await mcp_client.get_tools()
        logger.info(f"Loaded {len(tools)} tools")
    except Exception as e:
        logger.error(f"MCP connection failed: {e}")
        return

    llm = LLMFactory.get_llm(provider=os.getenv("LLM_PROVIDER", "openai"))
    app = create_agent_graph(llm, tools)
    validator = QueryValidatorNode()
    
    # kopernicus_intro()
    print(" Architecture: Decomposed Single-Responsibility Nodes")
    print("="*60 + "\n")

    first_run = True
    current_state = {
        "plan": [],
        "past_steps": [],
        "evidence": [],
        "schema_patterns": [],
        "coverage_assessment": "{}",
        "loop_detection": "{}",
        "should_explore_more": True,
        "should_transition_to_synthesis": False,
        "ready_to_answer": False,
        "exploration_strategy": "",
        "response": "",
        "iteration_count": 0,
        "max_iterations": 15,
        "is_plan_approved": False
    }

    while True:
        try:
            if query and first_run:
                user_input = query
            else:
                if query and current_state.get("ready_to_answer"):
                    break
                
                # Auto-approve logic: if we just got a plan and auto_approve is on, proceed.
                # Guard: only auto-approve if the plan is non-empty and not an error placeholder.
                plan_text = current_state.get("plan_proposal", "") or ""
                plan_ok = plan_text and plan_text.strip().lower() not in ("error", "")
                if auto_approve and plan_ok and not current_state.get("is_plan_approved"):
                    print("Plan Feedback/Approval> Proceed (Auto-approved)")
                    user_input = "Proceed"
                else:
                    prompt_prefix = "Query" if not current_state.get("plan_proposal") else "Plan Feedback/Approval"
                    user_input = input(f"{prompt_prefix}> ")
            
            first_run = False
            if user_input.lower() in ["quit", "exit"]:
                break

            # Update input in current state
            current_state["input"] = user_input

            # Only validate if we don't have a plan yet (initial query)
            if not current_state.get("plan_proposal"):
                validation = await validator.validate(user_input, llm)
                if not validation.is_valid:
                    print(f"⚠️  {validation.feedback}")
                    continue

            if not current_state.get("is_plan_approved"):
                print(f"\n📝 Processing Plan...\n")
            else:
                print(f"\n🔬 Researching...\n")
            
            langfuse_handler = setup_langfuse_tracing()
            callbacks = [] # [langfuse_handler] if langfuse_handler else []
            
            config = {"recursion_limit": 1000, "callbacks": callbacks, "configurable": {"thread_id": "cli_session"}}
            
            # Iterate through stream for progress
            async for event in app.astream(current_state, config=config, stream_mode="updates"):
                for node_name, state_update in event.items():
                    if node_name == "plan_proposer":
                        plan = state_update.get("plan_proposal")
                        if plan:
                            logger.info(f"\n{'='*20} PROPOSED NORTH STAR PLAN {'='*20}")
                            logger.info(plan)
                            logger.info(f"{'='*66}\n")
                            if not auto_approve:
                                print("Instructions: Type 'Proceed' to start or provide feedback to refine the plan.")
                    elif node_name == "planner":
                        logger.info(f"📋 Initial Strategy: {state_update.get('exploration_strategy')}")
                    elif node_name == "executor":
                        # In updates mode, state_update has ONLY the new steps added in this turn
                        steps = state_update.get('past_steps', [])
                        if steps:
                            logger.info(f"🔨 Executed: {steps[-1][1]}")
                    elif node_name == "schema_analyzer":
                        logger.info(f"🔍 Analyzing schema patterns...")
                    elif node_name == "coverage_analyzer":
                        data = json.loads(state_update.get('coverage_assessment', '{}'))
                        score = data.get('density_score', 0)
                        logger.info(f"📊 Coverage: {score}/10")
                    elif node_name == "decision_maker":
                        synth = state_update.get('should_transition_to_synthesis', False)
                        if synth:
                            logger.info(f"✨ Transitioning to synthesis...")
                    elif node_name == "exploration_planner":
                        plan_steps = state_update.get('plan', [])
                        if plan_steps:
                            logger.info(f"➡️  Next idea: {plan_steps[0][:80]}...")
                    elif node_name == "answer_generator":
                        response = state_update.get("response")
                        if response:
                            logger.info(f"\n{'='*20} FINAL SCIENTIFIC ANSWER {'='*20}")
                            logger.info(response)
                            logger.info(f"{'='*64}\n")

            # GET FINAL PERSISTED STATE
            final_snapshot = await app.aget_state(config)
            current_state = final_snapshot.values

            # If we just got an answer:
            # - In single-query mode (query arg provided), exit immediately.
            # - In interactive mode, reset state for the next question.
            if current_state.get("ready_to_answer"):
                if query:
                    break
                current_state["plan_proposal"] = None
                current_state["is_plan_approved"] = False
                current_state["ready_to_answer"] = False
                current_state["input"] = ""
                current_state["past_steps"] = []
                current_state["evidence"] = []
                current_state["iteration_count"] = 0

        except EOFError:
            logger.info("stdin closed (EOF), exiting")
            break
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            break
        except Exception as e:
            logger.error(f"ERROR: {e}", exc_info=True)
            print(f"\n❌ ERROR: {e}")
            traceback.print_exc()
            # Recover checkpoint state so ready_to_answer / is_plan_approved are accurate
            try:
                final_snapshot = await app.aget_state(config)
                current_state = final_snapshot.values
            except Exception:
                pass  # keep current_state as-is

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KOPernicus Research Agent CLI")
    parser.add_argument("query", nargs="?", help="Initial research query")
    parser.add_argument("--auto-approve", action="store_true", help="Automatically approve proposed research plans")
    
    args = parser.parse_args()
    
    asyncio.run(main(query=args.query, auto_approve=args.auto_approve))
