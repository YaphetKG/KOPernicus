import asyncio
import json
import logging
import traceback
import sys
from pathlib import Path
from langfuse.langchain import CallbackHandler
from langchain_mcp_adapters.client import MultiServerMCPClient

from .llm import LLMFactory
from .workflow import create_agent_graph
from .nodes import validate_query
from .intro import kopernicus_intro

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
        # Fallback to src root if running from there
        config_path = Path(__file__).parent.parent / 'mcp-config.json'

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

    llm = LLMFactory.get_llm(provider="openai")
    app = create_agent_graph(llm, tools)
    
    kopernicus_intro()
    print(" Architecture: Decomposed Single-Responsibility Nodes")
    print("="*60 + "\n")

    first_run = True
    while True:
        try:
            if query and first_run:
                user_input = query
            else:
                if query:
                    break
                # Only ask for input if not running a single query from CLI
                user_input = input("Query> ")
            
            first_run = False
            if user_input.lower() in ["quit", "exit"]:
                break

            validation = await validate_query(user_input, llm)
            if not validation.is_valid:
                print(f"⚠️  {validation.feedback}")
                continue

            print(f"\n🔬 Researching...\n")
            
            initial_state = {
                "input": user_input,
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
                "max_iterations": 15
            }
            
            langfuse_handler = CallbackHandler()
            
            async for event in app.astream(initial_state, config={"recursion_limit": 100, "callbacks": [langfuse_handler]}):
                for k, v in event.items():
                    if k == "planner":
                        print(f"📋 Strategy: {v.get('exploration_strategy')}")
                    elif k == "executor":
                        step = v.get('past_steps', [])[-1] if v.get('past_steps') else ("", "")
                        print(f"🔨 Executed: {step[1]}")
                    elif k == "schema_analyzer":
                        patterns = v.get('schema_patterns', [])
                        if patterns:
                            print(f"🔍 Found {len(patterns)} schema patterns")
                    elif k == "coverage_analyzer":
                        data = json.loads(v.get('coverage_assessment', '{}'))
                        score = data.get('density_score', 0)
                        print(f"📊 Coverage: {score}/10")
                    elif k == "loop_detector":
                        data = json.loads(v.get('loop_detection', '{}'))
                        if data.get('is_looping'):
                            print(f"⚠️  Loop detected: {data.get('repeated_pattern')}")
                    elif k == "decision_maker":
                        explore = v.get('should_explore_more', False)
                        synth = v.get('should_transition_to_synthesis', False)
                        iteration = v.get('iteration_count', 0)
                        if synth:
                            print(f"✨ Iteration {iteration}: Transitioning to synthesis")
                        else:
                            print(f"🔄 Iteration {iteration}: Continue exploration")
                    elif k == "exploration_planner":
                        plan = v.get('plan', [])
                        if plan:
                            print(f"➡️  Next: {plan[0][:80]}...")
                    elif k == "synthesis_planner":
                        print(f"📝 Planning answer structure...")
                    elif k == "answer_generator":
                        if v.get("response"):
                            print(f"\n{'='*20} FINAL ANSWER {'='*20}")
                            print(v.get("response"))
                            print(f"{'='*54}\n")

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
