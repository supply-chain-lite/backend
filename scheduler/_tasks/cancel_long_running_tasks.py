import asyncio

from celery import Celery

from app.connection import master_connection
from app.logging_config import get_logger
from app.routers.tasks.methods import update_task_output_and_logs
from app.routers.tasks.queries import update_task_status
from scheduler._tasks.queries import get_long_running_started_tasks, update_task_log

logger = get_logger(__name__)

DEFAULT_MAX_RUN_SECONDS = 86400  # 24 hours


def _cancel_and_update(task_id, task_uid, task_url, model_id, max_run_seconds):
    try:
        celery_app = Celery("tasks", broker=task_url, backend=task_url)
        celery_app.control.revoke(task_uid, terminate=True)
    except Exception as e:
        logger.error(f"Failed to revoke Celery task {task_uid}: {e}")

    try:
        with master_connection() as cursor:
            cursor.execute(update_task_status, ("REVOKED", task_id, "STARTED"))
            result = cursor.fetchall()
            if not result:
                # Task may have been in RUNNING state instead
                cursor.execute(update_task_status, ("REVOKED", task_id, "RUNNING"))
                result = cursor.fetchall()
            if result:
                logger.info(
                    f"Cancelled long-running task {task_id} (uid={task_uid}, "
                    f"max_run_seconds={max_run_seconds})"
                )
            update_task_output_and_logs(cursor, task_id)
            task_log_message = (
                f"Task was automatically cancelled after exceeding "
                f"max run time of {max_run_seconds} seconds."
            )
            cursor.execute(update_task_log, (task_log_message, task_id))
    except Exception as e:
        logger.error(f"Failed to update status for cancelled task {task_id}: {e}")


async def main(params: dict | None = None) -> dict:
    del params

    with master_connection() as cursor:
        long_running_tasks = cursor.execute(get_long_running_started_tasks).fetchall()

    if not long_running_tasks:
        return {"cancelled_count": 0, "checked_count": 0}

    cancelled_count = 0
    for task_id, task_uid, task_url, model_id, max_run_seconds in long_running_tasks:
        await asyncio.to_thread(
            _cancel_and_update, task_id, task_uid, task_url, model_id, max_run_seconds
        )
        cancelled_count += 1

    logger.info(
        f"Cancelled {cancelled_count}/{len(long_running_tasks)} long-running tasks"
    )
    return {"cancelled_count": cancelled_count, "checked_count": len(long_running_tasks)}
