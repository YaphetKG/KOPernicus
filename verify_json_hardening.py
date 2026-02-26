
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock
from langchain_core.prompts import ChatPromptTemplate
from src.kopernicus_agent.nodes import QueryClassifierNode, QueryValidatorNode
from src.kopernicus_agent.state import AgentState

async def test_json_hardening():
    print("--- Verifying JSON Hardening ---")
    
    # 1. Mock LLM to capture the prompt
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content='{"is_valid": true, "feedback": "looks good"}'))
    
    # For many nodes we use prompt | llm | parser
    # We want to see the prompt that was actually passed.
    # In validate_query: validator = prompt | llm | parser
    
    # Let's test query_classifier_node
    state: AgentState = {
        "input": "What treats Type 2 Diabetes?",
        "iteration_count": 0
    }
    
    # We need to mock the LLM such that it just returns a valid JSON that the parser can handle.
    # QueryClassification expects { "contract": { "query_type": ..., ... }, "reasoning": ... }
    mock_classification_resp = MagicMock()
    mock_classification_resp.content = json.dumps({
        "contract": {
            "query_type": "treatment",
            "required_entity_types": ["chemical_entity", "disease"],
            "required_predicates": ["biolink:treats"],
            "min_path_length": 1,
            "max_path_length": 3,
            "requires_direct_evidence": False
        },
        "reasoning": "Standard treatment query."
    })
    
    mock_llm.ainvoke.return_value = mock_classification_resp
    
    print("\nTesting query_classifier_node...")
    try:
        # We need to reach into the RunnableSequence to see the prompt.
        # But easier is just to let it run and see if it CRASHES.
        # If the template is missing {format_instructions}, it will crash during ainvoke 
        # because the node passes 'format_instructions' in the dictionary.
        
        result = await QueryClassifierNode()(state, mock_llm)
        print("✓ query_classifier_node executed successfully.")
        print(f"  Result query_type: {result['answer_contract']['query_type']}")
        
    except KeyError as e:
        print(f"✗ query_classifier_node FAILED with KeyError: {e}")
        print("  This means {format_instructions} is missing from the template but passed in the code (or vice-versa, depending on direction of refactor).")
    except Exception as e:
        print(f"✗ query_classifier_node encountered an error: {e}")

    # Test validate_query
    print("\nTesting validate_query...")
    mock_llm.ainvoke.return_value = MagicMock(content='{"is_valid": true, "feedback": "valid query"}')
    try:
        result = await QueryValidatorNode().validate("What treats diabetes?", mock_llm)
        print("✓ validate_query executed successfully.")
    except Exception as e:
        print(f"✗ validate_query encountered an error: {e}")

if __name__ == "__main__":
    asyncio.run(test_json_hardening())
