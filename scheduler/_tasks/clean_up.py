import asyncio
import os
import time
from datetime import datetime, timezone

import apsw

from app.config import CELERY_LOG_FOLDER, CELERY_MODELS_FOLDER, CELERY_TEMP_FOLDER, TEMP_FOLDER, master_db
from app.connection import master_connection
from app.logging_config import get_logger
from scheduler._tasks import queries as cleanup_queries

logger = get_logger(__name__)

TEMP_FILE_RETENTION_SECONDS = 3600  # 1 hour
CELERY_LOG_RETENTION_SECONDS = 7 * 24 * 3600  # 7 days
CELERY_MODEL_RETENTION_SECONDS = 30 * 24 * 3600  # 30 days
VACUUM_INTERVAL_SECONDS = 7 * 24 * 3600  # 7 days
EXECUTION_LOG_RETENTION_DAYS = 30
SQL_HISTORY_MAX_RECORDS_PER_USER = 100
TASK_HISTORY_MAX_RECORDS_PER_USER = 30


def _cleanup_folder(folder_path, retention_seconds):
    now = time.time()
    deleted_count = 0

    if not os.path.isdir(folder_path):
        return deleted_count

    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if not os.path.isfile(file_path):
            continue

        file_age = now - os.path.getmtime(file_path)
        if file_age > retention_seconds:
            os.remove(file_path)
            deleted_count += 1

    return deleted_count


async def main(params: dict | None = None) -> dict:
    del params

    deleted_counts = {
        "temp_files": _cleanup_folder(TEMP_FOLDER, TEMP_FILE_RETENTION_SECONDS),
        "celery_temp_files": _cleanup_folder(CELERY_TEMP_FOLDER, TEMP_FILE_RETENTION_SECONDS),
        "celery_log_files": _cleanup_folder(CELERY_LOG_FOLDER, CELERY_LOG_RETENTION_SECONDS),
        "celery_model_files": _cleanup_folder(CELERY_MODELS_FOLDER, CELERY_MODEL_RETENTION_SECONDS),
    }

    master_vacuumed = await asyncio.to_thread(_query, master_db)
    user_models_vacuum = await vacuum_user_models({})
    db_cleanup_results = await asyncio.to_thread(db_cleanup)
    return {
        "deleted_counts": deleted_counts,
        "master_vacuumed": bool(master_vacuumed),
        "user_models_vacuum": user_models_vacuum,
        "db_cleanup": db_cleanup_results,
    }


def _query(db_path):
    connection = None
    try:
        connection = apsw.Connection(db_path)
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return 1
    except Exception as e:
        logger.error(f"Error during database cleanup: {e}")
        return 0
    finally:
        if connection is not None:
            connection.close()


def _parse_last_vacuum_date(last_vacuum_date):
    if not last_vacuum_date:
        return None

    try:
        parsed_date = datetime.fromisoformat(last_vacuum_date)
        if parsed_date.tzinfo is None:
            return parsed_date.replace(tzinfo=timezone.utc)
        return parsed_date.astimezone(timezone.utc)
    except ValueError:
        return None


async def vacuum_user_models(params: dict | None = None) -> dict:
    del params

    with master_connection() as cursor:
        cursor.execute(cleanup_queries.get_model_id_and_paths)
        models = cursor.fetchall()

    checked_count = 0
    skipped_count = 0
    vacuumed_count = 0
    failed_count = 0

    for model_id, model_path, last_vacuum_date in models:
        checked_count += 1
        do_vacuum = False
        if not model_path or not os.path.isfile(model_path):
            skipped_count += 1
            continue
        file_age = time.time() - os.path.getmtime(model_path)
        if file_age < VACUUM_INTERVAL_SECONDS:
            skipped_count += 1
            continue  # Skip if file is not old enough for vacuuming

        if last_vacuum_date:
            vacuum_date = _parse_last_vacuum_date(last_vacuum_date)
            if not vacuum_date:
                skipped_count += 1
                continue  # Skip if last vacuum date is invalid
            vacuum_age = (datetime.now(timezone.utc) - vacuum_date).total_seconds()
            if vacuum_age < VACUUM_INTERVAL_SECONDS:
                skipped_count += 1
                continue  # Skip if vacuumed recently
            if abs(file_age - vacuum_age) < 3600:  # 1 hour threshold to account for time differences
                skipped_count += 1
                continue
            do_vacuum = True
        else:
            do_vacuum = True  # No record of vacuuming, so proceed
        if do_vacuum:
            vacuum_result = await asyncio.to_thread(_query, model_path)
            if not vacuum_result:
                failed_count += 1
                continue

            with master_connection() as cursor:
                cursor.execute(
                    cleanup_queries.update_vacuum_date,
                    (datetime.now(timezone.utc).isoformat(), model_id),
                )
            vacuumed_count += 1

    return {
        "checked_count": checked_count,
        "skipped_count": skipped_count,
        "vacuumed_count": vacuumed_count,
        "failed_count": failed_count,
    }


def db_cleanup():
    with master_connection() as cursor:
        rows = cursor.execute(cleanup_queries.delete_duplicate_queries).fetchall()
        duplicate_deleted = len(rows)
        logger.info(f"Deleted {len(rows)} duplicate query history records")
        rows = cursor.execute(cleanup_queries.delete_execution_logs, (EXECUTION_LOG_RETENTION_DAYS,)).fetchall()
        execution_logs_deleted = len(rows)
        logger.info(f"Deleted {len(rows)} old job execution logs")
        rows = cursor.execute(cleanup_queries.delete_sql_history, (SQL_HISTORY_MAX_RECORDS_PER_USER,)).fetchall()
        sql_history_deleted = len(rows)
        logger.info(
            f"Deleted {len(rows)} old SQL history records, keeping the most recent {SQL_HISTORY_MAX_RECORDS_PER_USER} per user"
        )
        rows = cursor.execute(
            cleanup_queries.delete_task_history,
            (TASK_HISTORY_MAX_RECORDS_PER_USER, CELERY_LOG_RETENTION_SECONDS / 86400),
        ).fetchall()
        task_history_deleted = len(rows)
        logger.info(
            f"Deleted {len(rows)} old task history records, keeping the most recent {TASK_HISTORY_MAX_RECORDS_PER_USER} per user"
        )
        rows = cursor.execute(cleanup_queries.delete_task_logs).fetchall()
        task_logs_deleted = len(rows)
        logger.info(f"Deleted {len(rows)} old task logs")
    return {
        "duplicate_queries_deleted": duplicate_deleted,
        "execution_logs_deleted": execution_logs_deleted,
        "sql_history_deleted": sql_history_deleted,
        "task_history_deleted": task_history_deleted,
        "task_logs_deleted": task_logs_deleted,
    }
