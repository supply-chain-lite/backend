"""
Celery task definitions for running supply chain task programs.

Provides the ``run_command`` task, which resolves a task's program path and
parameters from the template registry, spawns it as a subprocess, streams
stdout/stderr to the application logger, and enforces a configurable timeout.
"""

import os
import subprocess
import threading

from celery import current_task

from app.config import TASK_PROCESS_TIMEOUT_MINUTES
from app.logging_config import get_logger
from celery_app.celery import app
from celery_app.methods import get_task_program_path_and_details, update_child_process_id

logger = get_logger(__name__)


@app.task(name="celery_app.run_command")
def run_command(**kwargs) -> dict:
    """Run a shell command and return its output."""
    task_uid = current_task.request.id
    logger.info("Running task with uid: %s", task_uid)
    task_name = kwargs.get("task_name", None)
    if task_name is None:
        raise ValueError("task_name is required in kwargs")
    db = kwargs.get("db", None)
    if db is None:
        raise ValueError("db is required in kwargs")
    template_name = kwargs.get("template_name", None)
    if template_name is None:
        raise ValueError("template_name is required in kwargs")

    task_details = get_task_program_path_and_details(template_name, task_name)

    # Filter kwargs to only include parameters that are in command_line_parameters
    command_line_params = task_details.get("command_line_parameters", [])
    filtered_kwargs = {key: value for key, value in kwargs.items() if key in command_line_params}

    return _run_task_command(task_details, filtered_kwargs, task_uid)


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


def _run_task_command(task_details: dict, filtered_kwargs: dict = None, task_uid: str = None) -> dict:
    """Run the command described by task_details, redirecting stdout/stderr to the logger.

    Args:
        task_details: Task configuration from get_task_program_path_and_details
        filtered_kwargs: Optional kwargs filtered to only include command_line_parameters
        task_uid: The unique identifier of the current task
    """
    if filtered_kwargs is None:
        filtered_kwargs = {}

    command = _build_command(task_details, filtered_kwargs)
    working_directory = task_details.get("working_directory") or None

    # logger.info("Running command: %s (cwd=%s)", command, working_directory)

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

    logger.info("Started child process with PID %s", process.pid)
    update_child_process_id(process.pid, task_uid)

    timeout_seconds = TASK_PROCESS_TIMEOUT_MINUTES * 60
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        logger.error(
            "Command timed out after %s minutes and was killed: %s",
            TASK_PROCESS_TIMEOUT_MINUTES,
            command,
        )
        raise
    finally:
        stdout_thread.join()
        stderr_thread.join()

    if return_code != 0:
        if return_code == 9:
            logger.info("Command was killed (return code 9)")
        else:
            logger.error("Command finished with non-zero return code %s", return_code)
        raise Exception(f"Task errored with return code {return_code}")
    else:
        logger.info("Command finished successfully with return code %s", return_code)

    return {"return_code": return_code, "command": command}
