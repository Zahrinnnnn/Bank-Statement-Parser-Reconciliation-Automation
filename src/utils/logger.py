"""
logger.py — Logging configuration for the whole application.

Call setup_logging() once at startup (in main.py or app.py) and
every module that does `import logging; logger = logging.getLogger(__name__)`
will automatically use this configuration.

Logs go to both the console and a rotating file so nothing is lost
between runs.
"""

import logging
import logging.handlers
from pathlib import Path

# Log file lives next to the database in the data/ directory
LOG_FILE = Path(__file__).parent.parent.parent / "data" / "app.log"

# How many bytes before the log file rotates (5 MB)
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024

# How many rotated backup files to keep
LOG_FILE_BACKUP_COUNT = 3


def setup_logging(level: str = "INFO") -> None:
    """
    Set up console and file logging.

    Args:
        level: Logging level string — DEBUG, INFO, WARNING, ERROR, CRITICAL.
               Defaults to INFO. Pass DEBUG during development for verbose output.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Make sure the data/ directory exists before trying to write a log file
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Format: timestamp  level  module:line  message
    log_format = "%(asctime)s  %(levelname)-8s  %(name)s:%(lineno)d  %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    # Console handler — shows INFO and above by default
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)

    # Rotating file handler — captures everything at DEBUG level so
    # the file always has the full picture even when console is on INFO
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(LOG_FILE),
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Apply to the root logger so all modules inherit the handlers.
    # Guard against adding duplicate handlers if setup_logging() is
    # called more than once (e.g. from both a CLI group and a command).
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return  # Already configured — nothing to do
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    logging.getLogger(__name__).info("Logging initialised — level: %s", level)
