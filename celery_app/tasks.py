"""
Sample Celery tasks.

These are intentionally simple and exist to verify that the worker, broker,
and the pre-run / post-run hooks are wired up correctly.
"""

import sys
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


@app.task(name="celery_app.run_command")
def run_command(**kwargs) -> dict:
    """Run a shell command and return its output."""
    command = kwargs.get("command")
    # time.sleep(15)
    logger.info("run_command executing: %s", command)
    print("This is stdout output from run_command")
    return {"output": f"Executed command: {command}"}


@app.task(name="celery_app.health_check")
def health_check() -> dict:
    """Return a simple payload to confirm the worker is alive."""
    return {"status": "ok"}


@app.task(name="celery_app.verify_log_capture")
def verify_log_capture() -> dict:
    """Emit stdout, stderr, and logging output to verify per-task log capture.

    Run this task through a worker, then inspect ``CELERY_LOG_FOLDER/<task_uid>.log``.
    The file should contain the stdout line, the stderr line, and the INFO/WARNING/
    ERROR log lines emitted below.
    """
    stdout_marker = "STDOUT: hello from stdout"
    stderr_marker = "STDERR: hello from stderr"

    print(stdout_marker)
    print(stderr_marker, file=sys.stderr)
    logger.info("LOGGING: info-level message")
    logger.warning("LOGGING: warning-level message")
    logger.error("LOGGING: error-level message")

    return {
        "stdout": stdout_marker,
        "stderr": stderr_marker,
        "logging": ["info", "warning", "error"],
    }
