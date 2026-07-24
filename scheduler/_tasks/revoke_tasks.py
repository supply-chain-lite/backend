import asyncio
import json

from celery import Celery

from app.config import TASK_PROCESS_TIMEOUT_MINUTES
from app.connection import master_connection
from app.logging_config import get_logger
from app.routers.tasks.methods import update_task_output_and_logs
from app.routers.tasks.queries import insert_task_notifications, update_task_status
from scheduler._tasks.queries import get_pending_tasks_older_than, update_task_log

logger = get_logger(__name__)

PENDING_TIMEOUT_SECONDS = TASK_PROCESS_TIMEOUT_MINUTES * 60  # Convert minutes to seconds


def _revoke_and_update(task_id, task_uid, task_url, model_id):
    try:
        celery_app = Celery("tasks", broker=task_url, backend=task_url)
        celery_app.control.revoke(task_uid, terminate=True)
    except Exception as e:
        logger.error(f"Failed to revoke Celery task {task_uid}: {e}")

    try:
        with master_connection() as cursor:
            cursor.execute(update_task_status, ("REVOKED", task_id, "PENDING"))
            result = cursor.fetchall()
            if result:
                task_name, model_name, project_name, submitted_by, execution_time = result[0]
                logger.info(f"Revoked stale PENDING task {task_id} (uid={task_uid})")
                notification_params = {
                    "model_name": model_name,
                    "project_name": project_name,
                    "task_name": task_name,
                    "run_status": "REVOKED",
                    "run_time_minutes": execution_time,
                    "task_id": task_id,
                    "LEVEL": "WARNING",
                }
                notification_title = f"Task Revoked: {task_name}"
                notification_message = (
                    f"Your task '{task_name}' for model '{model_name}' in project '{project_name}'"
                    f" was automatically revoked after being in PENDING state"
                    f" for over {PENDING_TIMEOUT_SECONDS} seconds."
                )
                insert_task_tuple = (
                    "System",
                    submitted_by,
                    notification_title,
                    notification_message,
                    "task_update",
                    json.dumps(notification_params),
                )
                cursor.execute(insert_task_notifications, insert_task_tuple)
                cursor.intermediate_commit()
            update_task_output_and_logs(cursor, task_id)
            task_log_message = (
                f"Task was automatically revoked after being in PENDING state "
                f"for over {PENDING_TIMEOUT_SECONDS} seconds."
            )
            cursor.execute(update_task_log, (task_log_message, task_id))
    except Exception as e:
        logger.error(f"Failed to update status for revoked task {task_id}: {e}")


async def main(params: dict | None = None) -> dict:
    del params

    with master_connection() as cursor:
        pending_tasks = cursor.execute(get_pending_tasks_older_than, (PENDING_TIMEOUT_SECONDS,)).fetchall()

    if not pending_tasks:
        return {"revoked_count": 0, "checked_count": 0}

    revoked_count = 0
    for task_id, task_uid, task_url, model_id in pending_tasks:
        await asyncio.to_thread(_revoke_and_update, task_id, task_uid, task_url, model_id)
        revoked_count += 1

    logger.info(f"Revoked {revoked_count}/{len(pending_tasks)} stale PENDING tasks")
    return {"revoked_count": revoked_count, "checked_count": len(pending_tasks)}
