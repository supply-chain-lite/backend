import json
from datetime import UTC, datetime

from app.connection import master_connection


def _now():
    return datetime.now(UTC).isoformat()


def _serialise(obj):
    """Safely serialise args/kwargs to JSON."""
    try:
        return json.dumps(obj)
    except (TypeError, ValueError):
        return str(obj)


def record_task_received(task_id: str, task_name: str, args=None, kwargs=None):
    """Insert a new row when the task is first received by a worker."""
    with master_connection() as conn:
        query = "SELECT Status FROM SC_TaskWorker WHERE TaskId = ?"
        existing = conn.execute(query, (task_id,)).fetchone()
        if existing and existing[0] == "CANCELLED":
            return "CANCELLED"
        conn.execute(
            """
            INSERT OR IGNORE INTO SC_TaskWorker (TaskId, TaskName, Args,
            Kwargs, Status, TimeReceived)
            VALUES (?, ?, ?, ?, 'RECEIVED', ?)
            """,
            (task_id, task_name, _serialise(args), _serialise(kwargs), _now()),
        )
    return "RECEIVED"


def record_task_started(task_id: str, process_id=None, worker_name=None):
    """Mark the task as STARTED and set time_started."""
    with master_connection() as conn:
        conn.execute(
            """UPDATE SC_TaskWorker SET Status = 'STARTED',
                TimeStarted = ?, ProcessId = ?, WorkerName = ?
                WHERE TaskId = ?""",
            (_now(), process_id, worker_name, task_id),
        )


def record_task_success(task_id: str, result=None):
    """Mark the task as SUCCESS."""
    with master_connection() as conn:
        conn.execute(
            """UPDATE SC_TaskWorker SET Status = 'SUCCESS', TimeCompleted = ?,
                Result = ? WHERE TaskId = ?""",
            (_now(), _serialise(result), task_id),
        )


def record_task_failure(task_id: str, error=None, traceback_str=None):
    """Mark the task as FAILURE."""
    with master_connection() as conn:
        conn.execute(
            """UPDATE SC_TaskWorker SET Status = 'FAILURE', TimeCompleted = ?,
                Error = ?, Traceback = ? WHERE TaskId = ?""",
            (_now(), str(error), traceback_str, task_id),
        )
