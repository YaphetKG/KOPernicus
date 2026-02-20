
import asyncio
import json
from langchain_community.chat_models.fake import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, SystemMessage
from src.kopernicus_agent.nodes import plan_proposer_node, plan_gatekeeper_node, planner_node, executor_node
from src.kopernicus_agent.state import AgentState

# Mock Tools
class MockTool:
    def __init__(self, name):
        self.name = name
    async def ainvoke(self, args):
        return f"Result from {self.name} with args {args}"

async def test_nodes():
    print("--- Running Formal Node Tests with FakeMessagesListChatModel ---")
    
    # ... (Previous tests omitted for brevity, focusing on new test) ...
    
    # 4. Test Executor Node (Hard Constraint Enforcement)
    print("\nTesting executor_node (Constraint Enforcement)...")
    
    # Mock LLM that generates a tool call for a forbidden action
    # We need to mock the tool binding/calling behavior
    # executor_node: response = await llm_with_tools.ainvoke([system_msg])
    # The response should have .tool_calls
    
    class MockToolCallResponse:
        def __init__(self, name, args):
            self.tool_calls = [{"name": name, "args": args}]
            self.content = ""

    class MockExecutorLLM:
        def __init__(self, tool_call_name, tool_call_args):
             self.response = MockToolCallResponse(tool_call_name, tool_call_args)
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, messages):
            return self.response

    # Scenario: "biolink:related_to" is forbidden ONLY for source "CHEBI:123"
    forbidden_pred = "biolink:related_to"
    forbidden_source = "CHEBI:123"
    
    state_constraints: AgentState = {
        "plan": ["Retrieve edges"],
        "hard_constraints": {
            "forbidden_predicates": [], # Global list empty
            "forbidden_continuations": [{"source": forbidden_source, "predicate": forbidden_pred}]
        }
    }
    
    # 1. Blocked Call (Matching Source + Predicate)
    mock_exec_llm_blocked = MockExecutorLLM("get_edges", {"source": forbidden_source, "predicate": forbidden_pred})
    tools = [MockTool("get_edges")]
    
    print("  Testing Blocked Call...")
    try:
        res_blocked = await executor_node(state_constraints, mock_exec_llm_blocked, tools)
        steps = res_blocked.get("past_steps", [])
        if steps and "Action blocked" in steps[0][1] and "forbidden due to loops" in steps[0][1]:
             print(f"  ✓ Correctly blocked specific triple: {steps[0][1]}")
        else:
             print(f"  ✗ Failed to block triple. Steps: {steps}")
    except Exception as e:
        print(f"  ✗ Test crashed: {e}")

    # 2. Allowed Call (Different Source, Same Predicate)
    print("  Testing Allowed Call (Different Source)...")
    mock_exec_llm_allowed = MockExecutorLLM("get_edges", {"source": "CHEBI:999", "predicate": forbidden_pred})
    
    try:
        res_allowed = await executor_node(state_constraints, mock_exec_llm_allowed, tools)
        steps = res_allowed.get("past_steps", [])
        # Should NOT have "Action blocked"
        if not steps: # Success implies no error steps returned in the error format I defined? 
                      # Wait, my mock tool returns success. executor_node returns a dict with 'evidence' for success.
            # executor_node returns evidence item in 'evidence' list, and NO 'past_steps' (or empty?)
            # Actually executor_node returns None for past_steps on success?
            # Let's check the code. It returns evidence_item.
            # Wait, executor_node logic:
            # if success: evidence_item = {...}, output_text = "...". It does NOT return a dict with "past_steps" key?
            # It returns the result of the node?
            # Ah, looking at executor_node:
            # It returns: {"past_steps": [(task, output_text)], "evidence": [evidence_item]}
            
            # So we check past_steps[0][1]
            out_text = res_allowed.get("past_steps", [])[0][1]
            if "Action blocked" not in out_text and "Result from get_edges" in out_text:
                 print(f"  ✓ Correctly allowed non-forbidden triple: {out_text}")
            else:
                 print(f"  ✗ Incorrectly blocked or failed: {out_text}")
    except Exception as e:
        print(f"  ✗ Test crashed: {e}")

if __name__ == "__main__":
    asyncio.run(test_nodes())
