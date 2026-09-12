"""
Scheduled task implementations.

Each task function is an async coroutine that receives task_params (dict)
and returns a result dict. Blocking I/O (e.g. DB calls via apsw) should
be wrapped with ``asyncio.to_thread`` so the event loop stays responsive.
"""

import asyncio

from app.connections.connection import master_connection
from app.logging_config import get_logger
from app.routers.tasks.methods import run_task_by_model_id as submit_model_task
from app.routers.tasks.methods import update_task_status
from app.routers.tasks.schemas import TaskParamValues
from scheduler._tasks.cancel_long_running_tasks import main as cancel_long_running_main
from scheduler._tasks.clean_up import main as cleanup_main
from scheduler._tasks.revoke_tasks import main as revoke_tasks_main

logger = get_logger(__name__)


async def celery_task_update(params: dict) -> dict:
    def _update():
        with master_connection() as cursor:
            update_task_status(cursor)

    await asyncio.to_thread(_update)
    return {"status": "completed"}


def _required_param(params: dict, key: str):
    value = params.get(key)
    if value is None:
        raise ValueError(f"Missing required task parameter: {key}")
    return value


def _task_param_values(raw_params) -> list[TaskParamValues]:
    if isinstance(raw_params, dict):
        return [
            TaskParamValues(ParameterName=parameter_name, ParameterValue=parameter_value)
            for parameter_name, parameter_value in raw_params.items()
        ]
    return [TaskParamValues(**param) for param in raw_params or []]


async def run_model_task(params: dict) -> dict:
    """
    Submit a model task through the same method used by the tasks API.

    Expected params:
        model_name: Model name
        project_name: Project name
        task_code: Model task code
        task_params: List of task parameter values
    """

    user_email = _required_param(params, "user_email")
    model_id = _required_param(params, "model_id")
    task_code = int(_required_param(params, "task_code"))
    task_param_values = _task_param_values(params.get("task_input_params"))

    def _submit():
        with master_connection() as cursor:
            task_id, task_name, resolved_model_name, resolved_project_name = submit_model_task(
                cursor,
                user_email,
                model_id,
                task_code,
                task_param_values,
            )
        return {
            "status": "submitted",
            "task_id": task_id,
            "task_name": task_name,
            "model_name": resolved_model_name,
            "project_name": resolved_project_name,
        }

    return await asyncio.to_thread(_submit)


# Registry mapping task names to their async handler functions
TASK_REGISTRY: dict[str, callable] = {
    "cleanup_temp_files": cleanup_main,
    "celery_task_update": celery_task_update,
    "run_model_task": run_model_task,
    "revoke_stale_tasks": revoke_tasks_main,
    "cancel_long_running_tasks": cancel_long_running_main,
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
