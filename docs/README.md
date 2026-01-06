# KOPernicus Examples

This document provides visual examples of KOPernicus in action.

## Interactive Exploration

The following example demonstrates the agent interacting with the RoboKOP graph to answer a biomedical question.

![Example 1 - Analyzing Diabetes Treatments](example1.gif)

### What's Happening in the Example?

1.  **User Query**: The user asks "What treats Diabetes?".
2.  **Planning**: The agent formulates an initial strategy, identifying the key entity "Diabetes".
3.  **Execution**:
    *   It uses the `name-resolver` to map "Diabetes" to its CURIE (e.g., `MONDO:0005015`).
    *   It executes a `biolink:treats` query to find related chemical entities.
4.  **Analysis**:
    *   **Schema Analysis**: Identifies pattern connections between "Diabetes" and various treatments.
    *   **Coverage Analysis**: Assesses if it has enough information to synthesizing an answer.
5.  **Result**: The agent presents a summarized list of treatments, citing its evidence from the graph.



### Other interesting test queries (No promises that they will be answered , LLMs can be moody)

1. Which genes associated with cyclic vomiting syndrome are modulated by chemical exposures, and what chemicals emerge as potential therapeutic hypotheses? 
 (CURRENTLY this drives the agent into a loop... , get egdes gives it a triple with NCBIGene:4567-->Unknown , and that drives it crazy but eventually ... here's the answer )
Below is the Agents final answer (after *some* time): 
    ```
    Introduction Cyclic vomiting syndrome (MONDO:0010778) is a recurrent, episodic disorder characterized by severe nausea and vomiting. While its exact pathophysiology remains unclear, recent data suggest a genetic component.
    Genetic Landscape The only gene that the current knowledge graph links to cyclic vomiting syndrome is TRNL1 (NCBIGene:4567). This association is captured by the edge gene_associated_with_condition (NCBIGene:4567 → MONDO:0010778).
    Chemical Modulation of TRNL1 Attempts to identify chemical modulators of TRNL1 in the graph were made via the predicates modulated_by, regulated_by, and has_chemical_modulator. All three predicates returned a single edge each, but the target of the edge is listed as Unknown (no CURIE). Consequently, no specific chemical modulator of TRNL1 is currently documented in the graph.
    Therapeutic Hypotheses Because the graph does not provide concrete chemical modulators for TRNL1, we cannot propose evidence‑based therapeutic chemicals at this time. The absence of known modulators highlights a gap in the literature and suggests that future experimental work should focus on identifying small molecules or biologics that influence TRNL1 expression or function.
    Conclusion The current evidence base identifies a single gene, TRNL1 (NCBIGene:4567), associated with cyclic vomiting syndrome (MONDO:0010778). No chemical modulators of this gene are documented in the knowledge graph, precluding the derivation of therapeutic hypotheses from existing data. Further research is needed to uncover molecular targets and their chemical modulators for this condition.
    Limitations Only one gene is linked to the disease in the graph. All chemical modulation edges point to Unknown; no CURIEs for chemicals are available. The evidence set may be incomplete; additional literature may reveal other genes or modulators not captured here. Confidence: medium
    Critical Subgraph { "nodes": [ {"id": "MONDO:0010778", "label": "cyclic vomiting syndrome"}, {"id": "NCBIGene:4567", "label": "TRNL1"}, {"id": "Unknown", "label": "unknown chemical modulator"} ], "edges": [ {"source": "NCBIGene:4567", "target": "MONDO:0010778", "predicate": "gene_associated_with_condition"}, {"source": "NCBIGene:4567", "target": "Unknown", "predicate": "modulated_by"}, {"source": "NCBIGene:4567", "target": "Unknown", "predicate": "regulated_by"}, {"source": "NCBIGene:4567", "target": "Unknown", "predicate": "has_chemical_modulator"} ] }
    ```
