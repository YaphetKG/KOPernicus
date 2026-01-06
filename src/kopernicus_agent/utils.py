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
