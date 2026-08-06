"""Logger configuration for the extraction subgraph."""

import logging
import os
from pathlib import Path
from ..config.settings import settings


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance with DEBUG level and dual output
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, settings.log.level))

    # Create formatter
    formatter = logging.Formatter(settings.log.format)

    # Console handler
    if settings.log.console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # File handler
    if settings.log.file_output:
        # Ensure log directory exists
        log_dir = Path(settings.log.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        log_path = log_dir / settings.log.log_file
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
