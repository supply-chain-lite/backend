import asyncio

from app.connection import master_connection

from . import queries as db_queries


async def get_enabled_jobs() -> list:
    """Fetch all enabled scheduled jobs."""

    def _query():
        with master_connection() as conn:
            return conn.execute(db_queries.get_jobs).fetchall()

    return await asyncio.to_thread(_query)


async def update_job_run_times(job_id: int, last_run: str, next_run: str) -> None:
    """Update the last and next run times for a job."""

    def _query():
        with master_connection() as conn:
            conn.execute(db_queries.update_job_run_time, (last_run, next_run, job_id))

    await asyncio.to_thread(_query)


async def log_job_execution(
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

    def _query():
        with master_connection() as conn:
            count_updated_rows = conn.execute(db_queries.update_job_running_status, (1, job_id, 0)).fetchone()
            if not count_updated_rows:
                return -1
            execution_id = conn.execute(
                db_queries.insert_job_execution,
                (job_id, job_name, status, started_at, completed_at, duration, retry_count, error_message, result_data),
            ).fetchone()
            if not execution_id:
                raise Exception("Failed to log job execution")
            return execution_id[0]

    return await asyncio.to_thread(_query)


async def update_job_execution(
    job_id,
    execution_id: int,
    status: str,
    completed_at: str,
    duration: float,
    error_message: str | None = None,
    result_data: str | None = None,
) -> None:
    """Update an existing job execution record."""

    def _query():
        with master_connection() as conn:
            count_updated_rows = conn.execute(db_queries.update_job_running_status, (0, job_id, 1)).fetchone()
            if not count_updated_rows:
                raise Exception("Failed to update job run times - job is currently running or does not exist")
            conn.execute(
                db_queries.update_job_execution,
                (status, completed_at, duration, error_message, result_data, execution_id),
            )

    await asyncio.to_thread(_query)
