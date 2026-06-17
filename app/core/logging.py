"""Logging configuration for the application."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

def setup_logging():
    """Configure application logging.

    - Console: INFO level, colored via stdout
    - File:    DEBUG level, rotating 50MB x5 backups, writes to logs/app.log
    - Child loggers (e.g. "v7ai-fast.agent") inherit handlers via propagation
    """
    logger = logging.getLogger("v7ai-fast")
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Console — INFO+ for readability
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File — DEBUG for full traceability
    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=1024 * 1024 * 50,  # 50MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    for noisy in ("urllib3", "httpx", "httpcore", "minio", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # SQLAlchemy engine logging — only WARNING+ (set to INFO for query debugging)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    return logger

logger = setup_logging()
