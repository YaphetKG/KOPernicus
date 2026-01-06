import subprocess
import sys
import time
import signal
import os

# Configuration for servers
SERVERS = [
    {"name": "biolink", "module": "biolink_mcp.server", "port": 8001},
    {"name": "name-resolver", "module": "name_resolver_mcp.server", "port": 8002},
    {"name": "nodenormalizer", "module": "nodenormalizer_mcp.server", "port": 8003},
    {"name": "robokop", "module": "robokop_mcp.server", "port": 8004},
]

processes = []

def start_servers():
    print("🚀 Starting ROBOKOP-MCP Servers...")
    
    for server in SERVERS:
        # Special handling for biolink_mcp which is missing if __name__ == "__main__": override
        if server["name"] == "biolink":
             cmd = [
                "uv", "run", "python", "-c", 
                f"from {server['module']} import main; main()",
                "run", "--transport", "sse", "--port", str(server["port"])
            ]
        else:
            # Standard execution for well-behaved modules
            cmd = [
                "uv", "run", "-m", server["module"],
                "run", "--transport", "sse", "--port", str(server["port"])
            ]
        
        print(f"   • Starting {server['name']} on port {server['port']}...")
        print(f"{' '.join(cmd)}")
        try:
            # shell=True required on Windows for some path resolutions, but standard Popen usually safer
            # using clean env inheritance
            p = subprocess.Popen(cmd, env=os.environ.copy())
            processes.append((server['name'], p))
        except Exception as e:
            print(f"❌ Failed to start {server['name']}: {e}")

    print("\n✅ All servers launched. Press Ctrl+C to stop.\n")

def stop_servers(signum, frame):
    print("\n🛑 Stopping servers...")
    for name, p in processes:
        print(f"   • Terminating {name}...")
        p.terminate()
    
    # Wait for graceful exit
    time.sleep(1)
    
    # Force kill if needed
    for name, p in processes:
        if p.poll() is None:
            p.kill()
            
    print("👋 Shutdown complete.")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop_servers)
    signal.signal(signal.SIGTERM, stop_servers)
    
    start_servers()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
            # Check if any process died
            for name, p in processes:
                if p.poll() is not None:
                    print(f"⚠️  Server {name} died unexpectedly with code {p.returncode}")
                    stop_servers(None, None)
    except KeyboardInterrupt:
        stop_servers(None, None)
