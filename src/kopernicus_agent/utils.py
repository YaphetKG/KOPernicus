import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

def prune_evidence(evidence: List[Dict], max_items: int = 20) -> List[Dict]:
    """Keep only most relevant evidence"""
    if len(evidence) <= max_items:
        return evidence
    
    successful = [e for e in evidence if e.get("status") == "success"]
    recent = evidence[-max_items//2:]
    
    combined = []
    seen_steps = set()
    for e in successful + recent:
        step_sig = (e.get("step"), e.get("tool"))
        if step_sig not in seen_steps:
            combined.append(e)
            seen_steps.add(step_sig)
            if len(combined) >= max_items:
                break
    
    logger.info(f"Pruned evidence from {len(evidence)} to {len(combined)} items")
    return combined

def get_unique_schema(schema_list: List[str]) -> List[str]:
    return list(set(schema_list))

def setup_langfuse_tracing():
    """
    Setup Langfuse tracing using config file or environment variables.
    Returns: CallbackHandler or None
    """
    import os
    import json
    from pathlib import Path
    
    # Try finding config file
    config_path = Path('langfuse_config.json')
    if not config_path.exists():
        # Try finding in root if running from src
        config_path = Path(__file__).parent.parent.parent / 'langfuse_config.json'

    if config_path.exists():
        try:
            logger.info(f"Attempting to load config from: {config_path.absolute()}")
            # PowerShell Out-File often uses UTF-16; try detection or utf-8-sig
            try:
                with open(config_path, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
                    # If empty, it's useless
                    if not content.strip():
                        logger.warning("Config file is empty")
                        return None
                    config = json.loads(content)
            except UnicodeDecodeError:
                # Fallback implementation for UTF-16 (common in PowerShell)
                with open(config_path, 'r', encoding='utf-16') as f:
                    config = json.load(f)
                
            # Set environment variables from config
            if "LANGFUSE_SECRET_KEY" in config:
                os.environ["LANGFUSE_SECRET_KEY"] = config["LANGFUSE_SECRET_KEY"]
            if "LANGFUSE_PUBLIC_KEY" in config:
                os.environ["LANGFUSE_PUBLIC_KEY"] = config["LANGFUSE_PUBLIC_KEY"]
            if "LANGFUSE_HOST" in config:
                # Default to cloud if not specified
                os.environ["LANGFUSE_HOST"] = config.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
                
            logger.info(f"Loaded Langfuse config from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load langfuse config: {e}")

    # Check if tracing is feasible
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        try:
            from langfuse.langchain import CallbackHandler
            logger.info("Langfuse tracing enabled")
            return CallbackHandler()
        except ImportError:
            logger.warning("langfuse-langchain not installed, tracing disabled")
            return None
        except Exception as e:
            logger.warning(f"Failed to initialize Langfuse: {e}")
            return None
    else:
        logger.info("Langfuse credentials not found, tracing disabled")
        return None
