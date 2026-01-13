"""
Logging configuration for YouTube Boss Title Updater
Provides structured logging with JSON format and file rotation
"""

import logging
import logging.handlers
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any


class JSONFormatter(logging.Formatter):
    """Format log records as JSON"""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON"""
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }

        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        # Add extra fields if present
        if hasattr(record, 'video_id'):
            log_data['video_id'] = record.video_id
        if hasattr(record, 'game_name'):
            log_data['game_name'] = record.game_name
        if hasattr(record, 'error_type'):
            log_data['error_type'] = record.error_type
        if hasattr(record, 'api_call'):
            log_data['api_call'] = record.api_call
        if hasattr(record, 'cost'):
            log_data['cost'] = record.cost

        return json.dumps(log_data)


class ColoredConsoleFormatter(logging.Formatter):
    """Format console output with colors"""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'       # Reset
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record with colors"""
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']

        # Format: [LEVEL] message
        levelname = f"{color}{record.levelname:8}{reset}"
        message = record.getMessage()

        # Add video_id if present
        if hasattr(record, 'video_id'):
            message = f"[{record.video_id}] {message}"

        return f"{levelname} {message}"


def setup_logging(
    log_dir: str = 'logs',
    log_level: str = 'INFO',
    console_output: bool = True,
    json_format: bool = True,
    verbose: bool = False,
    quiet: bool = False
) -> logging.Logger:
    """
    Set up structured logging with file rotation

    Args:
        log_dir: Directory to store log files
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        console_output: Whether to output to console
        json_format: Whether to use JSON format for files
        verbose: Enable verbose output (DEBUG level)
        quiet: Minimal output (WARNING level and above)

    Returns:
        Configured logger instance
    """
    # Create logs directory
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    # Determine log level
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = getattr(logging, log_level.upper(), logging.INFO)

    # Create logger
    logger = logging.getLogger('youtube_boss_updater')
    logger.setLevel(logging.DEBUG)  # Capture everything, let handlers filter

    # Remove existing handlers
    logger.handlers.clear()

    # File handler for all logs (JSON format)
    if json_format:
        all_handler = logging.handlers.RotatingFileHandler(
            log_path / 'info.log',
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        all_handler.setLevel(logging.DEBUG)
        all_handler.setFormatter(JSONFormatter())
        logger.addHandler(all_handler)

    # File handler for errors only (JSON format)
    error_handler = logging.handlers.RotatingFileHandler(
        log_path / 'error.log',
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JSONFormatter())
    logger.addHandler(error_handler)

    # Console handler (colored, human-readable)
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)

        if verbose or not quiet:
            console_handler.setFormatter(ColoredConsoleFormatter())
        else:
            # Minimal format for quiet mode
            console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

        logger.addHandler(console_handler)

    return logger


def log_api_call(logger: logging.Logger, api_name: str, video_id: str = None, **kwargs):
    """Log an API call with structured data"""
    logger.debug(
        f"API call: {api_name}",
        extra={
            'api_call': api_name,
            'video_id': video_id,
            **kwargs
        }
    )


def log_cost(logger: logging.Logger, operation: str, cost: float, video_id: str = None):
    """Log cost information"""
    logger.info(
        f"Cost: {operation} = ${cost:.4f}",
        extra={
            'cost': cost,
            'operation': operation,
            'video_id': video_id
        }
    )


def log_error(
    logger: logging.Logger,
    error_type: str,
    message: str,
    video_id: str = None,
    game_name: str = None,
    exc_info: bool = False
):
    """Log an error with structured data"""
    logger.error(
        message,
        extra={
            'error_type': error_type,
            'video_id': video_id,
            'game_name': game_name
        },
        exc_info=exc_info
    )
