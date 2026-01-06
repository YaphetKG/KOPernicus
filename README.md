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

## ⚙️ Configuration

The agent's LLM can be configured using environment variables. You can set these in your shell or a `.env` file.

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | Provider backend (`openai`, `gemini`) | `openai` |
| `OPENAI_API_KEY` | API Key for the LLM provider | `EMPTY` |
| `OPENAI_MODEL` | Model identifier to use (for `openai` provider) | `openai/gpt-oss-20b` |
| `OPENAI_BASE_URL` | Base URL for the LLM API (for `openai` provider) | `http://localhost:9777/v1` |

> **Note**: By default, the agent is configured to connect to a local LLM server (e.g., vLLM) on port 9777. To use OpenAI's official API, set `OPENAI_BASE_URL` to `https://api.openai.com/v1` and provide a valid `OPENAI_API_KEY`.

### Using Google Gemini
To use Google's Gemini models:
1.  Set `LLM_PROVIDER=gemini`
2.  Set `GOOGLE_API_KEY=your_api_key`
3.  (Optional) Set `GEMINI_MODEL` (default: `gemini-1.5-pro`)

## 🛠️ Usage

### Running the Agent
The agent automatically starts the required MCP servers (configured in `mcp-config.json`). No separate server process is needed.

**Interactive Mode:**
```bash
uv run -m src.kopernicus_agent.main
```

**Single Query Mode:**
```bash
uv run -m src.kopernicus_agent.main "What treats Diabetes?"
```

## 📚 Examples

See [docs/README.md](docs/README.md) for usage examples and visual demonstrations.

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
