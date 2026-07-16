import json
from datetime import UTC, datetime

from app.connection import master_connection

from . import queries as task_queries


def _now():
    return datetime.now(UTC).isoformat()


def _serialise(obj):
    """Safely serialise args/kwargs to JSON."""
    try:
        return json.dumps(obj)
    except (TypeError, ValueError):
        return str(obj)


def record_task_received(task_uid: str, task_name: str, args=None, kwargs=None):
    """Insert a new row when the task is first received by a worker."""
    with master_connection() as conn:
        query = "SELECT Status FROM SC_TaskWorker WHERE TaskUID = ?"
        existing = conn.execute(query, (task_uid,)).fetchone()
        if existing and existing[0] == "CANCELLED":
            return "CANCELLED"
        conn.intermediate_commit()
        conn.execute(
            task_queries.task_received_query,
            (task_uid, task_name, _serialise(args), _serialise(kwargs), _now()),
        )
        if conn.rowcount() == 1:
            return "RECEIVED"

        # Another worker already claimed this task_uid; do not treat as received.
        current = conn.execute(query, (task_uid,)).fetchone()
        if current and current[0]:
            return current[0]
    return "DUPLICATE"


def record_task_started(task_uid: str, process_id=None, worker_name=None):
    """Mark the task as STARTED and set time_started."""
    with master_connection() as conn:
        conn.execute(
            task_queries.task_started_query,
            (_now(), process_id, worker_name, task_uid),
        )


def record_task_success(task_uid: str, result=None):
    """Mark the task as SUCCESS."""
    with master_connection() as conn:
        conn.execute(
            task_queries.task_success_query,
            (_now(), _serialise(result), task_uid),
        )


def record_task_cancelled(task_uid: str):
    """Mark the task as CANCELLED."""
    with master_connection() as conn:
        conn.execute(
            task_queries.task_cancelled_query,
            (_now(), task_uid),
        )


def record_task_failure(task_uid: str, error=None, traceback_str=None):
    """Mark the task as FAILED."""
    with master_connection() as conn:
        conn.execute(
            task_queries.task_failure_query,
            (_now(), str(error), traceback_str, task_uid),
        )


def get_task_program_path_and_details(template_name: str, task_name: str):
    with master_connection() as conn:
        row = conn.execute(task_queries.get_program_details, (template_name, task_name)).fetchone()
        if not row:
            raise ValueError(f"No program details found for template '{template_name}' and task '{task_name}'")
        working_directory, program_path, execution_file_path, command_line_parameters, fixed_parameters = row
        command_line_parameters = json.loads(command_line_parameters)
        if not isinstance(command_line_parameters, list):
            raise ValueError(
                f"CommandLineParameters for template '{template_name}' and task '{task_name}' is not a list"
            )
        fixed_parameters = json.loads(fixed_parameters)
        if not isinstance(fixed_parameters, dict):
            raise ValueError(f"FixedParameters for template '{template_name}' and task '{task_name}' is not a dict")

        return {
            "working_directory": working_directory,
            "program_path": program_path,
            "execution_file_path": execution_file_path,
            "command_line_parameters": command_line_parameters,
            "fixed_parameters": fixed_parameters,
        }


def update_child_process_id(child_process_id: int, task_uid: str):
    """Update the child process ID in the database for the given task."""
    with master_connection() as conn:
        conn.execute(task_queries.update_child_process_id, (child_process_id, task_uid))
