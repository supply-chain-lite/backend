"""
Scheduled task implementations.

Each task function is an async coroutine that receives task_params (dict)
and returns a result dict. Blocking I/O (e.g. DB calls via apsw) should
be wrapped with ``asyncio.to_thread`` so the event loop stays responsive.
"""

import asyncio
import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.connection import master_connection
from app.logging_config import get_logger
from app.routers.tasks.methods import update_task_status

logger = get_logger(__name__)


def _load_cleanup_tasks_module():
    cleanup_dir = Path(__file__).with_name("tasks")
    package_name = "scheduler_task_handlers"
    module_name = f"{package_name}.clean_up"

    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(cleanup_dir)]
        sys.modules[package_name] = package

    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, cleanup_dir / "clean_up.py")
    if spec is None or spec.loader is None:
        raise ImportError("Unable to load scheduler cleanup task module")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


cleanup_tasks = _load_cleanup_tasks_module()


async def cleanup_logs(params: dict) -> dict:
    """
    Remove old task logs from S_TaskLogs table.

    Args:
        params: {"days_to_keep": int}

    Returns:
        {"deleted_count": int, "cutoff_date": str}
    """
    days_to_keep = params.get("days_to_keep", 30)
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days_to_keep)).strftime("%Y-%m-%d %H:%M:%S")

    logger.info("Cleaning up logs older than %s", cutoff_date)

    def _query():
        with master_connection() as cursor:
            cursor.execute("DELETE FROM S_TaskLogs WHERE LastUpdated < ?", (cutoff_date,))
            return cursor.rowcount()

    deleted_count = await asyncio.to_thread(_query)

    logger.info("Deleted %d old log entries", deleted_count)
    return {"deleted_count": deleted_count, "cutoff_date": cutoff_date}


async def db_stats_report(params: dict) -> dict:
    """
    Generate database statistics for specified tables.

    Args:
        params: {"include_tables": list[str]}

    Returns:
        {"stats": {table_name: row_count}, "generated_at": str}
    """
    include_tables = params.get("include_tables", [])

    logger.info("Generating database stats for tables: %s", include_tables)

    def _query():
        stats = {}
        with master_connection() as cursor:
            for table in include_tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                    result = cursor.fetchall()
                    stats[table] = result[0][0] if result else 0
                except Exception as e:
                    logger.warning("Failed to get stats for table %s: %s", table, e)
                    stats[table] = f"error: {str(e)}"
        return stats

    stats = await asyncio.to_thread(_query)

    result = {
        "stats": stats,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.info("Database stats report: %s", json.dumps(result))
    return result


async def celery_task_update(params: dict) -> dict:
    def _update():
        with master_connection() as cursor:
            update_task_status(cursor)

    await asyncio.to_thread(_update)
    return {"status": "completed"}


# Registry mapping task types to their async handler functions
TASK_REGISTRY: dict[str, callable] = {
    "cleanup_logs": cleanup_logs,
    "cleanup_temp_files": cleanup_tasks.main,
    "vacuum_user_models": cleanup_tasks.vacuum_user_models,
    "db_stats_report": db_stats_report,
    "celery_task_update": celery_task_update,
}


async def run_task(task_type: str, params: dict) -> dict:
    """
    Execute a task by its type.

    Args:
        task_type: The registered task type name
        params: Parameters to pass to the task

    Returns:
        Task result dictionary

    Raises:
        ValueError: If task_type is not registered
    """
    if task_type not in TASK_REGISTRY:
        raise ValueError(f"Unknown task type: {task_type}")

    handler = TASK_REGISTRY[task_type]
    return await handler(params)
