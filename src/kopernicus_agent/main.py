import asyncio
import json
import logging
import traceback
import sys
import os
from pathlib import Path
from pathlib import Path
from langchain_mcp_adapters.client import MultiServerMCPClient

from .llm import LLMFactory
from .workflow import create_agent_graph
from .nodes import validate_query
from .intro import kopernicus_intro
from .utils import setup_langfuse_tracing

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

async def main(query: str = None):
    
    try:
        mcp_client = get_mcp_client()
        tools = await mcp_client.get_tools()
        logger.info(f"Loaded {len(tools)} tools")
    except Exception as e:
        logger.error(f"MCP connection failed: {e}")
        return

    llm = LLMFactory.get_llm(provider=os.getenv("LLM_PROVIDER", "openai"))
    app = create_agent_graph(llm, tools)
    
    kopernicus_intro()
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
                
                prompt_prefix = "Query" if not current_state.get("plan_proposal") else "Plan Feedback/Approval"
                user_input = input(f"{prompt_prefix}> ")
            
            first_run = False
            if user_input.lower() in ["quit", "exit"]:
                break

            # Update input in current state
            current_state["input"] = user_input

            # Only validate if we don't have a plan yet (initial query)
            if not current_state.get("plan_proposal"):
                validation = await validate_query(user_input, llm)
                if not validation.is_valid:
                    print(f"⚠️  {validation.feedback}")
                    continue

            if not current_state.get("is_plan_approved"):
                print(f"\n📝 Processing Plan...\n")
            else:
                print(f"\n🔬 Researching...\n")
            
            langfuse_handler = setup_langfuse_tracing()
            callbacks = [langfuse_handler] if langfuse_handler else []
            
            config = {"recursion_limit": 1000, "callbacks": callbacks, "configurable": {"thread_id": "cli_session"}}
            
            # Iterate through stream for progress
            async for event in app.astream(current_state, config=config, stream_mode="updates"):
                for node_name, state_update in event.items():
                    if node_name == "plan_proposer":
                        plan = state_update.get("plan_proposal")
                        if plan:
                            print(f"\n{'='*20} PROPOSED NORTH STAR PLAN {'='*20}")
                            print(plan)
                            print(f"{'='*66}\n")
                            print("Instructions: Type 'Proceed' to start or provide feedback to refine the plan.")
                    elif node_name == "planner":
                        print(f"📋 Initial Strategy: {state_update.get('exploration_strategy')}")
                    elif node_name == "executor":
                        # In updates mode, state_update has ONLY the new steps added in this turn
                        steps = state_update.get('past_steps', [])
                        if steps:
                            print(f"🔨 Executed: {steps[-1][1]}")
                    elif node_name == "schema_analyzer":
                        print(f"🔍 Analyzing schema patterns...")
                    elif node_name == "coverage_analyzer":
                        data = json.loads(state_update.get('coverage_assessment', '{}'))
                        score = data.get('density_score', 0)
                        print(f"📊 Coverage: {score}/10")
                    elif node_name == "decision_maker":
                        synth = state_update.get('should_transition_to_synthesis', False)
                        if synth:
                            print(f"✨ Transitioning to synthesis...")
                    elif node_name == "exploration_planner":
                        plan_steps = state_update.get('plan', [])
                        if plan_steps:
                            print(f"➡️  Next idea: {plan_steps[0][:80]}...")
                    elif node_name == "answer_generator":
                        response = state_update.get("response")
                        if response:
                            print(f"\n{'='*20} FINAL SCIENTIFIC ANSWER {'='*20}")
                            print(response)
                            print(f"{'='*64}\n")

            # GET FINAL PERSISTED STATE
            final_snapshot = await app.aget_state(config)
            current_state = final_snapshot.values

            # If we just got an answer, reset for a clean next query
            if current_state.get("ready_to_answer"):
                current_state["plan_proposal"] = None
                current_state["is_plan_approved"] = False
                current_state["input"] = ""
                current_state["past_steps"] = []
                current_state["evidence"] = []
                current_state["iteration_count"] = 0

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            break
        except Exception as e:
            logger.error(f"ERROR: {e}", exc_info=True)
            print(f"\n❌ ERROR: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = sys.argv[1]
        asyncio.run(main(query=query))
    else:
        asyncio.run(main())
