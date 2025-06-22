# quantitative_momentum_trader/utils/logging_config.py
"""
Centralized logging configuration for the Quantitative Momentum Trading System.

This module sets up a standardized logging format and directs output to both
a console and a log file. It ensures that all other modules can access a
pre-configured logger, leading to consistent and comprehensive log records.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

def setup_logging(log_level: str = 'INFO', log_file: str = 'logs/quantitative_momentum_trader.log') -> None:
    """
    Configures the root logger for the application.

    This function sets up two handlers:
    1. A StreamHandler to print logs to the console (stdout).
    2. A RotatingFileHandler to save logs to a file, with automatic rotation
       to prevent the log file from growing indefinitely.

    Args:
        log_level (str): The minimum logging level to capture (e.g., 'DEBUG', 'INFO', 'WARNING').
                         Defaults to 'INFO'.
        log_file (str): The path to the log file. Defaults to 'logs/quantitative_momentum_trader.log'.
    """
    # Get the root logger
    root_logger = logging.getLogger()
    
    # Set the comprehensive log level for the root logger
    # Handlers can have their own, more restrictive levels.
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(level)

    # Prevent adding duplicate handlers if this function is called multiple times
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # --- Formatter ---
    # Define a standard format for log messages
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # --- Console Handler ---
    # This handler prints logs to the standard output (your terminal)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)

    # --- File Handler ---
    # This handler writes logs to a file. RotatingFileHandler manages log file size.
    try:
        # Create a rotating file handler
        # 5 MB per file, keeping up to 5 backup files.
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5*1024*1024, backupCount=5
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(log_format)
        root_logger.addHandler(file_handler)
    except FileNotFoundError:
        # This can happen if the 'logs' directory does not exist.
        # Log an error to the console and continue without file logging.
        logging.error(f"Log directory not found. Could not create log file at: {log_file}")
        logging.error("Please create the 'logs' directory manually.")

    # Log the successful setup of the logging configuration
    logging.info(f"Logging configured. Level: {log_level}, File: {log_file}")