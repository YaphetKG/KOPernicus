import asyncio
import sys
from pathlib import Path
# Add project root to sys.path
root = Path(__file__).resolve().parent.parent.parent.parent
if str(root) not in sys.path:
    sys.path.append(str(root))

from src.kopernicus_agent.nodes import PlanProposerNode, PlanGatekeeperNode, PlannerNode
from src.kopernicus_agent.state import AgentState
from src.kopernicus_agent.llm import LLMFactory
from src.kopernicus_agent.workflow import create_agent_graph
from src.kopernicus_agent.main import get_mcp_client





llm = LLMFactory.get_llm()

async def test_intial_plan():
    state: AgentState = {
        "input": "yeah looks good!",
        "original_query": "What treats Type 2 Diabetes?",
        "iteration_count": 0,
        "plan_proposal": """Research Plan: Evidence‑Grounded Identification of Diabetes Treatments

Entity Resolution

Enumerate diabetes subtypes (Type 1, Type 2, gestational, MODY, etc.) and assign standardized identifiers (UMLS, ICD‑10).
Compile a comprehensive list of therapeutic agents and modalities: insulin analogues, GLP‑1 receptor agonists, SGLT2 inhibitors, metformin, DPP‑4 inhibitors, thiazolidinediones, lifestyle interventions, bariatric surgery, etc., with corresponding DrugBank and MeSH IDs.
Resolve synonyms and map each entity to the knowledge graph’s canonical nodes.
Path Discovery

Query the KOPernicus biomedical KG for documented treatment–outcome relationships (e.g., HbA1c reduction, weight loss, cardiovascular event reduction).
Extract evidence paths linking each treatment to diabetes endpoints, prioritizing paths supported by high‑confidence evidence (randomized controlled trials, meta‑analyses, large cohort studies).
Record evidence strength, study design, and sample size for each path.
Mechanism Analysis

For each high‑confidence treatment, map molecular targets and signaling pathways (e.g., insulin receptor signaling, incretin effect, renal glucose reabsorption inhibition).
Assess mechanistic overlap and potential synergistic interactions between treatments.
Identify mechanistic gaps where the mode of action is poorly characterized or where evidence is sparse.
Synthesis

Generate a ranked list of treatments based on efficacy, safety profile, and mechanistic novelty.
Highlight promising combination strategies that target complementary pathways (e.g., GLP‑1 agonist + SGLT2 inhibitor).
Propose a focused experimental validation plan for the top 3–5 candidates, including in‑vitro assays (e.g., glucose uptake, insulin signaling) and clinical trial design considerations (endpoint selection, patient population, duration).
Assumptions

Primary focus on Type 2 diabetes due to its prevalence and the abundance of evidence, while still cataloguing treatments applicable to other subtypes.
Inclusion of both pharmacologic and non‑pharmacologic interventions.
Reliance on publicly available biomedical knowledge graphs (e.g., KOPernicus KG) for evidence retrieval and integration."""
,
    }
    # result = await PlanProposerNode()(state, llm)
    # print(result['plan_proposal'])
    result = await PlannerNode()(state, llm)
    print(result)

async def test_agent_structure():
    client =  get_mcp_client()
    tools = await client.get_tools()
    print(tools)
    # graph = create_agent_graph(llm, tools)
    # print(graph.get_graph().draw_mermaid())


if __name__ == "__main__":
    # asyncio.run(test_intial_plan())
    asyncio.run(test_agent_structure())