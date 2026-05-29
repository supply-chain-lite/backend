"""
Scheduled task implementations.

Each task function is an async coroutine that receives task_params (dict)
and returns a result dict. Blocking I/O (e.g. DB calls via apsw) should
be wrapped with ``asyncio.to_thread`` so the event loop stays responsive.
"""

import asyncio

from app.connection import master_connection
from app.logging_config import get_logger
from app.routers.tasks.methods import update_task_status
from scheduler._tasks.clean_up import main as cleanup_main

logger = get_logger(__name__)


async def celery_task_update(params: dict) -> dict:
    def _update():
        with master_connection() as cursor:
            update_task_status(cursor)

    await asyncio.to_thread(_update)
    return {"status": "completed"}


# Registry mapping task names to their async handler functions
TASK_REGISTRY: dict[str, callable] = {
    "cleanup_temp_files": cleanup_main,
    "celery_task_update": celery_task_update,
}


async def run_task(task_name: str, params: dict) -> dict:
    """
    Execute a task by its name.

    Args:
        task_name: The registered task name
        params: Parameters to pass to the task

    Returns:
        Task result dictionary

    Raises:
        ValueError: If task_name is not registered
    """
    if task_name not in TASK_REGISTRY:
        raise ValueError(f"Unknown task: {task_name}")

    handler = TASK_REGISTRY[task_name]
    return await handler(params)
