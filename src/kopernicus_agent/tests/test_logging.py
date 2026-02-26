import logging
import os
import shutil
from pathlib import Path
from kopernicus_agent.logging_config import setup_logging

def test_logging():
    # Clean up previous logs if any
    if Path("logs").exists():
        shutil.rmtree("logs")
    
    # Initialize logging
    logger = setup_logging()
    
    # Log some messages from our project
    logger.info("Verification: This is a project info message")
    logger.debug("Verification: This is a project debug message")
    
    # Simulate src. prefix (how uv/langgraph might name loggers)
    src_logger = logging.getLogger("src.kopernicus_agent.nodes")
    src_logger.info("Verification: This is a prefixed project message")
    
    # Log some messages from an "external" lib
    ext_logger = logging.getLogger("external_lib")
    ext_logger.warning("Verification: This IS allowed (Warning from external)")
    ext_logger.info("Verification: This should NOT be in the console (Info from external)")
    
    # Check log file existence
    log_file = Path("logs/kopernicus.log")
    if not log_file.exists():
        print("FAIL: Log file not created")
        return False
    
    # Check log file contents
    content = log_file.read_text()
    
    # Should include project logs
    if "project info message" not in content:
        print("FAIL: Project info missing from log file")
        return False
    if "project debug message" not in content:
        print("FAIL: Project debug missing from log file")
        return False
    if "prefixed project message" not in content:
        print("FAIL: Prefixed project message missing from log file")
        return False
        
    # Should NOT include external logs (due to our ProjectFilter)
    if "external_lib" in content:
        print("FAIL: External lib logs found in file logger (Filter failure)")
        return False
    
    print("SUCCESS: Logging verification passed!")
    print(f"Log file content length: {len(content)}")
    return True

if __name__ == "__main__":
    success = test_logging()
    exit(0 if success else 1)
