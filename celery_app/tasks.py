"""
Sample Celery tasks.

These are intentionally simple and exist to verify that the worker, broker,
and the pre-run / post-run hooks are wired up correctly.
"""

import time

from app.logging_config import get_logger
from celery_app.celery import app

logger = get_logger(__name__)


@app.task(name="celery_app.add")
def add(x: float, y: float) -> float:
    """Return the sum of two numbers."""
    logger.info("add(%s, %s)", x, y)
    return x + y


@app.task(name="celery_app.multiply")
def multiply(x: float, y: float) -> float:
    """Return the product of two numbers."""
    logger.info("multiply(%s, %s)", x, y)
    return x * y


@app.task(name="celery_app.slow_task")
def slow_task(seconds: int = 2) -> str:
    """Sleep for a few seconds to simulate a long-running task."""
    logger.info("slow_task sleeping for %ss", seconds)
    time.sleep(seconds)
    return f"slept {seconds}s"


@app.task(name="celery_app.health_check")
def health_check() -> dict:
    """Return a simple payload to confirm the worker is alive."""
    return {"status": "ok"}
