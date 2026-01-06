# KOPernicus
**AI Agent for Exploration over RoboKOP Graph using MCP Servers**

KOPernicus is a biomedical research agent that uses the Model Context Protocol (MCP) to query RoboKOP Knowledge Graph services. It features a decomposed "Specialist Team" architecture for planning, executing, and analyzing complex queries.

## 🚀 Getting Started

### Prerequisites
- **Python 3.12+**
- **[uv](https://github.com/astral-sh/uv)** (Fast Python package installer and manager)
  ```bash
  # Install uv (Linux/macOS)
  curl -LsSf https://astral.sh/uv/install.sh | sh

  # Install uv (Windows)
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

### Installation
1. **Clone the repository**
   ```bash
   git clone https://github.com/YaphetKG/KOPernicus.git
   cd KOPernicus
   ```

2. **Install Dependencies**
   Use `uv` to sync the environment. This will automatically install:
   - All Python dependencies (langchain, langgraph, etc.)
   - The RoboMCP servers (installed directly from the [RoboMCP repo](https://github.com/cbizon/RoboMCP))
   ```bash
   uv sync
   ```

## 🛠️ Usage

### 1. Start MCP Servers
We provide a helper script to launch all required MCP servers (`biolink`, `name-resolver`, `nodenormalizer`, `robokop`) in parallel.

```bash
uv run scripts/start_servers.py
```
*Leave this terminal open. The servers run on ports 8001-8004.*

### 2. Run the Agent
In a **new terminal**, run the agent:

**Interactive Mode:**
```bash
uv run -m src.kopernicus_agent.main
```

**Single Query Mode:**
```bash
uv run -m src.kopernicus_agent.main "What treats Diabetes?"
```

## 🧩 Architecture
KOPernicus uses a decomposed architecture where specialized semantic nodes handle specific phases of the research process:
- **Planner**: Sets initial strategy.
- **Executor**: Interacts with MCP tools.
- **Analyzers (Parallel)**:
    - `Schema`: Extracts graph patterns.
    - `Coverage`: Assesses if enough info exists to answer.
    - `Loop`: Detects repetitive actions.
- **Decision Maker**: Routes execution based on analysis.

See [docs/architecture.md](docs/architecture.md) for diagrams.
