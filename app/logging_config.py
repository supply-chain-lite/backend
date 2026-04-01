import logging
import logging.config

from app.config import LOG_FILE, LOG_LEVEL


def configure_logging() -> None:
    if getattr(configure_logging, "_configured", False):
        return

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

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
                    "filename": str(LOG_FILE),
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


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
