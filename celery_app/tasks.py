"""
Sample Celery tasks.

These are intentionally simple and exist to verify that the worker, broker,
and the pre-run / post-run hooks are wired up correctly.
"""

import os
import subprocess
import sys
import threading
import time

from app.logging_config import get_logger
from celery_app.celery import app
from celery_app.methods import get_task_program_path_and_details

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
    task_name = kwargs.get("task_name", None)
    if task_name is None:
        raise ValueError("task_name is required in kwargs")
    db = kwargs.get("db", None)
    if db is None:
        raise ValueError("db is required in kwargs")
    template_name = kwargs.get("template_name", None)
    if template_name is None:
        raise ValueError("template_name is required in kwargs")
    for key, value in kwargs.items():
        logger.info("run_command received kwarg: %s=%s", key, value)

    task_details = get_task_program_path_and_details(template_name, task_name)

    # Filter kwargs to only include parameters that are in command_line_parameters
    command_line_params = task_details.get("command_line_parameters", [])
    filtered_kwargs = {key: value for key, value in kwargs.items() if key in command_line_params}

    return _run_task_command(task_details, filtered_kwargs)


def _stream_to_logger(pipe, log) -> None:
    """Read a subprocess pipe line-by-line and forward each line to the logger."""
    try:
        for line in iter(pipe.readline, ""):
            line = line.rstrip("\n")
            if line:
                log(line)
    finally:
        pipe.close()


def _build_command(task_details: dict, filtered_kwargs: dict = None) -> list:
    """Build the command argument list from task_details.

    Args:
        task_details: Task configuration from get_task_program_path_and_details
        filtered_kwargs: Optional kwargs filtered to only include command_line_parameters
    """
    if filtered_kwargs is None:
        filtered_kwargs = {}

    command = []
    program_path = task_details.get("program_path")
    if program_path:
        command.append(program_path)
    execution_file_path = task_details.get("execution_file_path")
    if execution_file_path:
        command.append(execution_file_path)

    # Add fixed_parameters as key value pairs
    for key, value in task_details.get("fixed_parameters", {}).items():
        command.append(f"--{key}")
        command.append(str(value))

    # Add filtered_kwargs as --name value pairs
    for key, value in filtered_kwargs.items():
        command.append(f"--{key}")
        command.append(str(value))

    return command


def _run_task_command(task_details: dict, filtered_kwargs: dict = None) -> dict:
    """Run the command described by task_details, redirecting stdout/stderr to the logger.

    Args:
        task_details: Task configuration from get_task_program_path_and_details
        filtered_kwargs: Optional kwargs filtered to only include command_line_parameters
    """
    if filtered_kwargs is None:
        filtered_kwargs = {}

    command = _build_command(task_details, filtered_kwargs)
    working_directory = task_details.get("working_directory") or None

    logger.info("Running command: %s (cwd=%s)", command, working_directory)

    process = subprocess.Popen(
        command,
        cwd=working_directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    stdout_thread = threading.Thread(target=_stream_to_logger, args=(process.stdout, logger.info))
    stderr_thread = threading.Thread(target=_stream_to_logger, args=(process.stderr, logger.error))
    stdout_thread.start()
    stderr_thread.start()

    return_code = process.wait()
    stdout_thread.join()
    stderr_thread.join()

    logger.info("Command finished with return code %s", return_code)

    return {"return_code": return_code, "command": command}


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
