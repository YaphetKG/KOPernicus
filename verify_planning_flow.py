
import asyncio
import json
import logging
from unittest.mock import MagicMock, AsyncMock
from langchain_core.messages import AIMessage
from src.kopernicus_agent.nodes import plan_proposer_node, plan_gatekeeper_node
from src.kopernicus_agent.state import AgentState

# Fix logging to avoid noise
logging.basicConfig(level=logging.ERROR)

async def verify_planning_flow():
    print("--- Verifying Planning Flow (Groundedness & Gatekeeping) ---")
    
    # Simple Mock that mimics LLM invoke behavior without coroutine issues
    class MockLLM:
        def __init__(self, content):
            self.content = content
        async def ainvoke(self, *args, **kwargs):
            return AIMessage(content=self.content)
        def bind_tools(self, *args, **kwargs):
            return self

    # Mock for Gatekeeper that mimics parser behavior if needed
    # (Actually plan_gatekeeper_node uses a PydanticOutputParser)
    
    # Initial state
    state: AgentState = {
        "input": "What treats Type 2 Diabetes?",
        "original_query": "What treats Type 2 Diabetes?",
        "iteration_count": 0
    }
    
    print("\nRound 1: Initial Proposal")
    mock_llm1 = MockLLM("# North Star Plan: Type 2 Diabetes Treatments\n1. Resolve Type 2 Diabetes\n2. Search for chemicals that TREAT Type 2 Diabetes")
    try:
        result1 = await plan_proposer_node(state, mock_llm1)
        plan = result1.get('plan_proposal', '')
        print(f"Plan Proposal Generated (length: {len(plan)})")
        state.update(result1)
    except Exception as e:
        print(f"✗ Proposer failed: {e}")
        return
    
    # Simulate Round 2: User provides feedback
    state["input"] = "Also look for side effects of Metformin"
    print("\nRound 2: User Feedback ('Also look for side effects of Metformin')")
    
    # For Gatekeeper, we need something that passes through the PydanticOutputParser
    # gatekeeper_node: result = await (prompt | llm | parser).ainvoke(...)
    # So we need mock_llm.ainvoke to return an AIMessage with JSON content
    mock_gatekeeper_llm = MockLLM('{"decision": "feedback"}')
    
    try:
        gate_result = await plan_gatekeeper_node(state, mock_gatekeeper_llm)
        is_approved = gate_result.get('is_plan_approved')
        print(f"Gatekeeper Decision (expected False): {is_approved}")
        
        if is_approved == False:
            state["planning_feedback"] = state["input"]
            mock_llm2 = MockLLM("# Updated Plan\n1. Resolve Diabetes\n2. Check Metformin side effects")
            result2 = await plan_proposer_node(state, mock_llm2)
            print(f"Updated Plan Proposal Generated (length: {len(result2.get('plan_proposal', ''))})")
            state.update(result2)
        else:
            print("✗ Gatekeeper incorrectly approved feedback.")
            return
    except Exception as e:
        print(f"✗ Gatekeeper/Proposer round 2 failed: {e}")
        return

    # Simulate Round 3: User approves
    state["input"] = "Proceed"
    print("\nRound 3: User Approval ('Proceed')")
    mock_gatekeeper_llm_final = MockLLM('{"decision": "approved"}')
    
    try:
        gate_result_final = await plan_gatekeeper_node(state, mock_gatekeeper_llm_final)
        is_approved_final = gate_result_final.get('is_plan_approved')
        print(f"Gatekeeper Decision (expected True): {is_approved_final}")
        
        if is_approved_final:
            print("✓ Planning Flow Verification Successful.")
        else:
            print("✗ Planning Flow Verification Failed at approval stage.")
    except Exception as e:
        print(f"✗ Gatekeeper round 3 failed: {e}")

if __name__ == "__main__":
    asyncio.run(verify_planning_flow())
