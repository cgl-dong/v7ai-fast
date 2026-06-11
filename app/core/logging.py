"""Logging configuration for the application."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

def setup_logging():
    """Configure application logging."""
    logger = logging.getLogger("v7ai-fast")
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=1024 * 1024 * 50,  # 50MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()
