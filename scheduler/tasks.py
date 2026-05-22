"""
Sample scheduled task implementations.

Each task function receives task_params (dict) and returns a result dict.
"""

import json
from datetime import datetime, timedelta, timezone

from app.connection import master_connection
from app.logging_config import get_logger

logger = get_logger(__name__)


def cleanup_logs(params: dict) -> dict:
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

    with master_connection() as cursor:
        cursor.execute("DELETE FROM S_TaskLogs WHERE LastUpdated < ?", (cutoff_date,))
        deleted_count = cursor.rowcount()

    logger.info("Deleted %d old log entries", deleted_count)
    return {"deleted_count": deleted_count, "cutoff_date": cutoff_date}


def db_stats_report(params: dict) -> dict:
    """
    Generate database statistics for specified tables.

    Args:
        params: {"include_tables": list[str]}

    Returns:
        {"stats": {table_name: row_count}, "generated_at": str}
    """
    include_tables = params.get("include_tables", [])
    stats = {}

    logger.info("Generating database stats for tables: %s", include_tables)

    with master_connection() as cursor:
        for table in include_tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                result = cursor.fetchall()
                stats[table] = result[0][0] if result else 0
            except Exception as e:
                logger.warning("Failed to get stats for table %s: %s", table, e)
                stats[table] = f"error: {str(e)}"

    result = {
        "stats": stats,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.info("Database stats report: %s", json.dumps(result))
    return result


# Registry mapping task types to their handler functions
TASK_REGISTRY: dict[str, callable] = {
    "cleanup_logs": cleanup_logs,
    "db_stats_report": db_stats_report,
}


def run_task(task_type: str, params: dict) -> dict:
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
    return handler(params)
