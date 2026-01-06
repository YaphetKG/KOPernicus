# KOPernicus Architecture Diagram

## v3: The KOPernicus System (Decomposed)
**"The Specialist Team"**

This diagram represents the **v3 (Decomposed)** architecture implemented in this current code base. It is designed for granular control, with separated concerns for analysis, decision making, and planning.

### Mermaid Diagram

```mermaid
graph TD
    %% Subgraphs for Phases
    subgraph "Phase 1: Execution"
        Planner[Planner Node]
        Executor[Executor Node]
        Tools[MCP Tools]
    end

    subgraph "Phase 2: Analysis (Parallel)"
        Schema[Schema Analyzer]
        Coverage[Coverage Analyzer]
        Loop[Loop Detector]
        Decision[Decision Maker]
    end

    subgraph "Phase 3: Planning (Branching)"
        Exploration[Exploration Planner]
        Synthesis[Synthesis Planner]
    end

    subgraph "Phase 4: Answer"
        AnswerGen[Answer Generator]
        End((End))
    end

    %% Definition of Flow
    Planner -->|Initial Strategy| Executor
    Executor <-->|Strict Tool Calls| Tools
    
    %% Parallel Analysis
    Executor -->|Evidence| Schema
    Executor -->|Evidence| Coverage
    Executor -->|Evidence| Loop
    
    %% Aggregation
    Schema -->|Patterns| Decision
    Coverage -->|Density Score| Decision
    Loop -->|Stuck Status| Decision
    
    %% Branching
    Decision -->|Explore More| Exploration
    Decision -->|Ready to Answer| Synthesis
    
    %% Loops & Finalization
    Exploration -->|Next Step| Executor
    Synthesis -->|Answer Plan| AnswerGen
    AnswerGen -->|Final Response| End

    %% Styling
    style Decision fill:#f96,stroke:#333,stroke-width:2px
    style Executor fill:#bfb,stroke:#333,stroke-width:2px
```

### Description
- **Phase 1: Execution**: 
  - **Planner**: Sets the initial direction.
  - **Executor**: strictly handles tool interaction.
- **Phase 2: Analysis**:
  - Three specialized analyzers run in parallel (logically) to assess the state without making decisions.
  - **Decision Maker**: Aggregates all signals to make a single state transition decision.
- **Phase 3: Planning**:
  - **Exploration Helper**: Plans the next logical step if more info is needed.
  - **Synthesis Helper**: Structures the final answer if sufficient info is gathered.
- **Phase 4: Answer**:
  - **Answer Generator**: Writes the final response with strict citation rules, separate from logic.

### KOPernicus Visualization (v3 Conceptual)

![KOPernicus v3 Architecture Nano Banana Style](kopernicus_v3_architecture_nano_banana_1767677055077.png)

---

## v2: The Thinker (Plan-Reason-Act)
**"The Analyst"**

To solve the "mindless execution" problem of v1, we introduced the **Analyst** node. This shifted the paradigm from "doing" to "reasoning".

### Mermaid Diagram

```mermaid
graph TD
    subgraph "KOPernicus Agent v2"
        Planner2[Planner]
        Executor2[Executor]
        Analyst2[Analyst]
        Replanner2[Replanner]
        
        Planner2 --> Executor2
        Executor2 --> Analyst2
        Analyst2 --> Replanner2
        Replanner2 --> Executor2
    end
```

### Visualization

![KOPernicus v2 Analyst](kopernicus_v2_architecture_nano_banana_1767677072456.png)

---

## v1: The Foundation (Standard ReAct)
**"The Doer"**

The initial version was a standard implementation of the Plan-and-Execute pattern using a ReAct agent.

### Mermaid Diagram

```mermaid
graph LR
    Planner -->|List of Steps| Executor
    Executor -->|Tool Result| Replanner
    Replanner -->|Updated Plan| Executor
    Executor -->|Uses| Tools[MCP Tools]
    
    style Executor fill:#eee,stroke:#333
```

### Visualization

![KOPernicus v1 ReAct](kopernicus_v1_architecture_nano_banana_1767677090495.png)
