import json
import asyncio
import logging
from pathlib import Path
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

async def get_mcp_summary():
    """
    Reads mcp-config.json and generates a high-level summary of servers and their tools.
    Format:
    <mcp-server-name> : <server desc>
    <tools> :
        - <tool name> : <tool description>
    """
    # Try multiple locations for mcp-config.json
    config_locations = [
        Path('mcp-config.json'),
        Path(__file__).parent / 'mcp-config.json',
        Path(__file__).parent.parent / 'mcp-config.json',
        Path(__file__).parent.parent.parent / 'mcp-config.json'
    ]
    
    config_path = None
    for loc in config_locations:
        if loc.exists():
            config_path = loc
            break
            
    if not config_path:
        return "Error: Could not find mcp-config.json"

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            
        mcp_servers = config.get("mcpServers", {})
        summary_lines = []
        
        for server_name, server_config in mcp_servers.items():
            # Generate header
            # Note: The 'desc' isn't standard in mcp-config.json, so we use server_name or a placeholder
            summary_lines.append(f"{server_name} : (MCP Server)")
            summary_lines.append("<tools> :")
            
            try:
                # Initialize a single-server client to get its specific tools
                client = MultiServerMCPClient({server_name: server_config})
                
                # Use a timeout because some servers might hang during startup
                try:
                    tools = await asyncio.wait_for(client.get_tools(), timeout=10.0)
                    
                    if not tools:
                        summary_lines.append("    - (No tools found)")
                    else:
                        for tool in tools:
                            # Clean up description: first sentence or first line
                            desc = tool.description.split('\n')[0].split('. ')[0].strip()
                            summary_lines.append(f"    - {tool.name} : {desc}")
                except asyncio.TimeoutError:
                    summary_lines.append("    - Error: Timeout while retrieving tools")
            except Exception as e:
                summary_lines.append(f"    - Error: Could not connect to {server_name}")
                logger.debug(f"Connection error for {server_name}: {e}")
            
            summary_lines.append("") # Blank line between servers
            
        return "\n".join(summary_lines).strip()
        
    except Exception as e:
        return f"Error parsing MCP configuration: {e}"

if __name__ == "__main__":
    # Quick test
    async def run_test():
        print("--- MCP Server Summary ---\n")
        summary = await get_mcp_summary()
        print(summary)
        
    asyncio.run(run_test())
