import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler

from app.common.config import LoggingConfig, get_project_dir


def build_logger(name: str, default_log_file: str) -> logging.Logger:
    config = LoggingConfig()
    log_dir = config.log_dir or os.path.join(get_project_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, default_log_file)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.log_level, logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y%m%d"
    file_handler.extMatch = re.compile(r"^\d{8}$", re.ASCII)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False
    return logger
