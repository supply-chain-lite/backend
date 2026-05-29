"""
Scheduler runner - async entry point for running scheduled jobs.

This module provides an async scheduler that:
- Loads job definitions from the database
- Evaluates cron expressions to determine when to run jobs
- Executes due jobs concurrently via asyncio.gather
- Handles retries with non-blocking exponential backoff
"""

import asyncio
import json
import signal
import sys
from datetime import datetime, timezone

from croniter import croniter

from app.logging_config import configure_logging, get_logger
from scheduler import methods as db_methods
from scheduler.database import init_scheduler_db
from scheduler.tasks import run_task

configure_logging(file_name="scheduler.log")
logger = get_logger(__name__)

# Global flag for graceful shutdown
_shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    logger.info("Shutdown signal received, finishing current jobs...")
    _shutdown_requested = True


def get_next_run(cron_expr: str, base_time: datetime | None = None) -> datetime:
    """Calculate the next run time for a cron expression."""
    base = base_time or datetime.now(timezone.utc)
    cron = croniter(cron_expr, base)
    return cron.get_next(datetime)


def is_job_due(
    next_run_at: datetime | None, cron_expr: str, last_run: datetime | None, tolerance_seconds: int = 60
) -> bool:
    """
    Determine if a job should run now based on its stored NextRunAt time.

    Uses the NextRunAt value from the database as the primary trigger so that
    jobs whose scheduled time passed while the scheduler was offline are
    executed immediately on restart. Falls back to the cron expression only
    when NextRunAt is not set (e.g. a brand-new job).

    Args:
        next_run_at: Stored next-run time from the database (None if not set)
        cron_expr: Cron expression string (used as fallback)
        last_run: Last execution time (None if never run)
        tolerance_seconds: Window of time to consider "now" (fallback only)

    Returns:
        True if the job should run
    """
    now = datetime.now(timezone.utc)

    if next_run_at is not None:
        # Primary path: run if we've reached or passed the stored next-run time
        return now >= next_run_at

    # Fallback for jobs that don't have a NextRunAt yet
    if last_run is None:
        cron = croniter(cron_expr, now)
        prev_scheduled = cron.get_prev(datetime)
        return (now - prev_scheduled).total_seconds() <= tolerance_seconds

    cron = croniter(cron_expr, last_run)
    next_scheduled = cron.get_next(datetime)
    return now >= next_scheduled


def parse_last_run_at(last_run_at: str | None, job_name: str) -> datetime | None:
    """Parse LastRunAt from DB and normalize to UTC."""
    if not last_run_at:
        return None

    try:
        return datetime.strptime(last_run_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning("Job '%s' has invalid LastRunAt '%s'; treating as never run", job_name, last_run_at)
        return None


async def execute_single_task(
    task_type: str, task_params: str, max_retries: int, task_name: str
) -> tuple[bool, dict | None, str | None]:
    retry_count = 0
    last_error = None

    while retry_count <= max_retries:
        try:
            params = json.loads(task_params) if task_params else {}
            logger.info("Executing task '%s' (attempt %d/%d)", task_name, retry_count + 1, max_retries + 1)
            result = await run_task(task_type, params)
            return True, result, None
        except Exception as e:
            last_error = str(e)
            retry_count += 1
            logger.warning("Task '%s' failed (attempt %d): %s", task_name, retry_count, last_error)
            if retry_count <= max_retries:
                await asyncio.sleep(2**retry_count)  # Non-blocking exponential backoff

    return False, None, last_error


async def execute_flow(job_id: int, job_name: str, flow_id: int, max_retries: int) -> bool:
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    flow_info = await db_methods.get_flow_info(flow_id)
    if not flow_info:
        logger.error("Flow %d not found for job '%s'", flow_id, job_name)
        return False

    _, flow_name, _, stop_on_error = flow_info
    steps = await db_methods.get_flow_steps(flow_id)

    if not steps:
        logger.warning("Flow '%s' has no steps", flow_name)
        return True

    execution_id = await db_methods.log_job_execution(
        job_id=job_id,
        job_name=job_name,
        status="running",
        started_at=started_at,
    )

    if execution_id == -1:
        logger.warning("Job '%s' is already running, skipping flow execution", job_name)
        return False

    logger.info("Starting flow '%s' with %d steps", flow_name, len(steps))

    step_results = []
    flow_success = True

    for step in steps:
        step_id, step_name, task_type, task_params, step_retries, _step_timeout, continue_on_error = step
        success, result, error = await execute_single_task(task_type, task_params, step_retries, step_name)

        step_results.append(
            {
                "step_id": step_id,
                "step_name": step_name,
                "success": success,
                "result": result,
                "error": error,
            }
        )

        if not success:
            flow_success = False
            if stop_on_error and not continue_on_error:
                logger.error("Flow '%s' stopped at step '%s' due to error: %s", flow_name, step_name, error)
                break
            else:
                logger.warning("Flow '%s' step '%s' failed but continuing: %s", flow_name, step_name, error)

    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    duration = (
        datetime.strptime(completed_at, "%Y-%m-%d %H:%M:%S") - datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
    ).total_seconds()

    # Determine overall status
    completed_steps = len(step_results)
    failed_steps = sum(1 for r in step_results if not r["success"])

    if flow_success:
        status = "success"
    elif completed_steps < len(steps):
        status = "partial"  # Stopped before completing all steps
    else:
        status = "failed"

    await db_methods.update_job_execution(
        job_id,
        execution_id=execution_id,
        status=status,
        completed_at=completed_at,
        duration=duration,
        error_message=f"{failed_steps} step(s) failed" if failed_steps else None,
        result_data=json.dumps({"steps": step_results}),
    )

    logger.info("Flow '%s' completed with status '%s' in %.2fs", flow_name, status, duration)
    return True


async def execute_task_job(job_id: int, job_name: str, task_type: str, task_params: str, max_retries: int) -> bool:
    """
    Execute a single task job.

    Returns:
        True if successful, False otherwise
    """
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    execution_id = await db_methods.log_job_execution(job_id, job_name, "running", started_at)

    if execution_id == -1:
        logger.warning("Job '%s' is already running, skipping execution", job_name)
        return False

    success, result, error = await execute_single_task(task_type, task_params, max_retries, job_name)

    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    duration = (
        datetime.strptime(completed_at, "%Y-%m-%d %H:%M:%S") - datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
    ).total_seconds()

    await db_methods.update_job_execution(
        job_id,
        execution_id=execution_id,
        status="success" if success else "failed",
        completed_at=completed_at,
        duration=duration,
        error_message=error,
        result_data=json.dumps(result) if result else None,
    )

    if success:
        logger.info("Job '%s' completed successfully in %.2fs", job_name, duration)
    else:
        logger.error("Job '%s' failed after retries: %s", job_name, error)

    return True


async def run_job(job) -> None:
    """Execute a single job (task or flow). Exceptions are logged, not propagated."""
    (
        job_id,
        job_name,
        task_category,
        task_type,
        task_params,
        flow_id,
        cron_expr,
        max_retries,
        _,
        last_run_at,
        next_run_at_str,
    ) = job

    try:
        last_run = parse_last_run_at(last_run_at, job_name)
        next_run_at = parse_last_run_at(next_run_at_str, job_name)  # same format

        if not is_job_due(next_run_at, cron_expr, last_run):
            return

        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        next_run = get_next_run(cron_expr, now)
        next_run_str = next_run.strftime("%Y-%m-%d %H:%M:%S")

        if task_category == "Flow":
            job_status = await execute_flow(job_id, job_name, flow_id, max_retries)
        else:
            job_status = await execute_task_job(job_id, job_name, task_type, task_params, max_retries)

        if job_status:
            await db_methods.update_job_run_times(job_id, now_str, next_run_str)
    except Exception as e:
        logger.exception("Error executing job '%s': %s", job_name, e)


async def run_scheduler(poll_interval: int = 60):
    """
    Main async scheduler loop.

    Due jobs are dispatched concurrently via asyncio.gather so that a job
    waiting on network I/O or sleeping during retry backoff does not block
    other jobs from making progress.

    Args:
        poll_interval: Seconds between checking for jobs to run
    """
    global _shutdown_requested

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Scheduler starting...")
    init_scheduler_db()
    logger.info("Scheduler initialized, entering main loop (poll interval: %ds)", poll_interval)

    while not _shutdown_requested:
        logger.info("Polling for jobs to run...")
        try:
            jobs = await db_methods.get_enabled_jobs()
            logger.info("Found %d enabled jobs", len(jobs))

            # Run all due jobs concurrently
            if jobs and not _shutdown_requested:
                await asyncio.gather(*(run_job(job) for job in jobs))

        except Exception as e:
            logger.exception("Error in scheduler loop: %s", e)

        # Wait before next poll, checking for shutdown every second
        for _ in range(poll_interval):
            if _shutdown_requested:
                break
            await asyncio.sleep(1)

    logger.info("Scheduler shut down gracefully")


if __name__ == "__main__":
    poll_interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    asyncio.run(run_scheduler(poll_interval))
