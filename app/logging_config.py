import logging
import logging.config
from pathlib import Path

from app.config import LOG_FOLDER, LOG_LEVEL


def configure_logging(file_name: str) -> None:
    target_log_file = Path(LOG_FOLDER) / file_name

    if (
        getattr(configure_logging, "_configured", False)
        and getattr(configure_logging, "_configured_log_file", None) == target_log_file
    ):
        return

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": LOG_LEVEL,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "standard",
                    "level": LOG_LEVEL,
                    "filename": str(target_log_file),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 5,
                    "encoding": "utf-8",
                },
            },
            "root": {
                "handlers": ["console", "file"],
                "level": LOG_LEVEL,
            },
        }
    )

    configure_logging._configured = True
    configure_logging._configured_log_file = target_log_file


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
