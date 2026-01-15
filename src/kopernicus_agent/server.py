from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langserve import add_routes
from .llm import LLMFactory
from .workflow import create_agent_graph
from .main import get_mcp_client
from .utils import setup_langfuse_tracing
import uvicorn
import asyncio
import os

from contextlib import asynccontextmanager

# Global agent instance
agent_runnable = None

async def setup_agent():
    # Helper to initialize the agent runnable
    try:
        mcp_client = get_mcp_client()
        # We need to await get_tools if it's async, but here we might need to handle the loop
        # For LangServe, it's better if we initialize tools at startup
        tools = await mcp_client.get_tools()
        llm = LLMFactory.get_llm(provider=os.getenv("LLM_PROVIDER", "openai"))
        agent = create_agent_graph(llm, tools)
        
        # Add tracing
        langfuse_handler = setup_langfuse_tracing()
        
        config = {
            "recursion_limit": 1000,
            "configurable": {"thread_id": "default-session"}
        }
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]
        
        # Use get_graph() to access visualization methods
        try:
            agent.get_graph().content
            print("\n--- Agent Architecture ---")
            agent.get_graph().print_ascii()
            print("--------------------------\n")
        except:
            pass
            
        return agent.with_config(config)
    except Exception as e:
        raise e
        return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global agent_runnable
    agent_runnable = await setup_agent()
    if agent_runnable:
        add_routes(
            app,
            agent_runnable,
            path="/kopernicus",
        )
    yield
    # Shutdown logic if needed

# Initialize app
app = FastAPI(
    title="Kopernicus Agent API",
    version="1.0",
    description="A biomedical research agent accessing RoboKOP via MCP",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# For running directly
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8822)
