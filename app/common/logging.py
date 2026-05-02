import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from zoneinfo import ZoneInfo

from app.common.config import LoggingConfig, get_project_dir

KST = ZoneInfo("Asia/Seoul")


class KSTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=KST)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec="seconds")


def build_logger(name: str, default_log_file: str) -> logging.Logger:
    config = LoggingConfig()
    log_dir = config.log_dir or os.path.join(get_project_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, default_log_file)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.log_level, logging.INFO))
    logger.handlers.clear()

    formatter = KSTFormatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S %Z")

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
