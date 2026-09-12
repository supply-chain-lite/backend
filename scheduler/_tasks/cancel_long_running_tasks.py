import asyncio

from app.config import DEFAULT_MAX_RUN_HOURS
from app.connections.connection import master_connection
from app.logging_config import get_logger
from app.routers.tasks.methods import cancel_task
from scheduler._tasks.queries import get_long_running_started_tasks, update_task_log

logger = get_logger(__name__)

DEFAULT_MAX_RUN_SECONDS = int(DEFAULT_MAX_RUN_HOURS * 3600)


def _cancel_long_running(task_id, submitted_by, max_run_seconds):
    try:
        with master_connection() as cursor:
            cancel_task(cursor, task_id, submitted_by)
            update_log_text = f"Task {task_id} cancelled due to exceeding max run time of {max_run_seconds} seconds."
            cursor.execute(update_task_log, (update_log_text, task_id))
            cursor.intermediate_commit()
    except Exception as e:
        logger.error(f"Failed to cancel long-running task {task_id}: {e}")


async def main(params: dict | None = None) -> dict:
    del params

    with master_connection() as cursor:
        long_running_tasks = cursor.execute(
            get_long_running_started_tasks, (DEFAULT_MAX_RUN_SECONDS, DEFAULT_MAX_RUN_SECONDS)
        ).fetchall()

    if not long_running_tasks:
        return {"cancelled_count": 0, "checked_count": 0}

    cancelled_count = 0
    for task_id, submitted_by, max_run_seconds in long_running_tasks:
        await asyncio.to_thread(_cancel_long_running, task_id, submitted_by, max_run_seconds)
        cancelled_count += 1

    logger.info(f"Cancelled {cancelled_count}/{len(long_running_tasks)} long-running tasks")
    return {"cancelled_count": cancelled_count, "checked_count": len(long_running_tasks)}
