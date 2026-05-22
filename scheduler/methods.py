from app.connection import master_connection
from scheduler import queries as db_queries


def get_enabled_jobs() -> list:
    """Fetch all enabled scheduled jobs (both tasks and flows)."""
    with master_connection() as conn:
        all_rows = conn.execute(db_queries.get_jobs).fetchall()
    return all_rows


def get_flow_steps(flow_id: int) -> list:
    """Fetch all steps for a flow, ordered by StepOrder."""
    with master_connection() as conn:
        all_rows = conn.execute(db_queries.get_flow_steps, (flow_id,)).fetchall()
    return all_rows


def get_flow_info(flow_id: int) -> tuple | None:
    """Fetch flow metadata."""
    with master_connection() as conn:
        all_rows = conn.execute(db_queries.get_flow_info, (flow_id,)).fetchall()
    return all_rows[0] if all_rows else None


def update_job_run_times(job_id: int, last_run: str, next_run: str) -> None:
    """Update the last and next run times for a job."""
    with master_connection() as conn:
        conn.execute(db_queries.update_job_run_time, (last_run, next_run, job_id))


def log_job_execution(
    job_id: int,
    job_name: str,
    status: str,
    started_at: str,
    completed_at: str | None = None,
    duration: float | None = None,
    retry_count: int = 0,
    error_message: str | None = None,
    result_data: str | None = None,
) -> int:
    """Log a job execution record and return the execution ID."""
    with master_connection() as conn:
        count_updated_rows = conn.execute(db_queries.update_job_running_status, (1, job_id, 0)).fetchone()
        if not count_updated_rows:
            return -1  # Indicate that the job is already running or does not exist
        execution_id = conn.execute(
            db_queries.insert_job_execution,
            (job_id, job_name, status, started_at, completed_at, duration, retry_count, error_message, result_data),
        ).fetchone()
        if not execution_id:
            raise Exception("Failed to log job execution")
        return execution_id[0]


def update_job_execution(
    job_id,
    execution_id: int,
    status: str,
    completed_at: str,
    duration: float,
    error_message: str | None = None,
    result_data: str | None = None,
) -> None:
    """Update an existing job execution record."""
    with master_connection() as conn:
        count_updated_rows = conn.execute(db_queries.update_job_running_status, (0, job_id, 1)).fetchone()
        if not count_updated_rows:
            raise Exception("Failed to update job run times - job is currently running or does not exist")
        conn.execute(
            db_queries.update_job_execution, (status, completed_at, duration, error_message, result_data, execution_id)
        )
