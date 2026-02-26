import logging
import os
import sys
from pathlib import Path

def setup_logging():
    """
    Standardize logging for KOPernicus.
    - Console: INFO level for kopernicus_agent, WARNING for others.
    - File: DEBUG level for kopernicus_agent only.
    """
    log_level_str = os.getenv("KOPERNICUS_LOG_LEVEL", "DEBUG").upper()
    log_level = getattr(logging, log_level_str, logging.DEBUG)
    
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "kopernicus.log"

    # Clear existing handlers from root logger
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Root logger level (the minimum for any handler)
    root_logger.setLevel(logging.DEBUG)

    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Filter for project-specific logs
    class ProjectFilter(logging.Filter):
        def filter(self, record):
            return "kopernicus_agent" in record.name

    # 1. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    # Console gets project logs at debug/info, and others at warning
    class ConsoleLevelFilter(logging.Filter):
        def filter(self, record):
            if "kopernicus_agent" in record.name:
                return record.levelno >= log_level # Use user-specified level for project
            return record.levelno >= logging.WARNING # Others only warning+
            
    console_handler.addFilter(ConsoleLevelFilter())
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 2. File Handler (Project logs ONLY)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG) # Depth in file
    file_handler.addFilter(ProjectFilter()) # ONLY project logs
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # silence noisy libraries explicitly as well
    for lib in ["langchain", "langgraph", "openai", "httpx", "uvicorn", "langfuse", "mcp"]:
        logging.getLogger(lib).setLevel(logging.WARNING)
        # Also handle potential src. prefix for these
        logging.getLogger(f"src.{lib}").setLevel(logging.WARNING)

    root_logger.info(f"Logging initialized. File: {log_file.absolute()}")
    return logging.getLogger("kopernicus_agent")
