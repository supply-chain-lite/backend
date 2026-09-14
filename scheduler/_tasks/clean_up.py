import asyncio
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone

from app.config import (
    BACKUP_FOLDER,
    CELERY_LOG_FOLDER,
    CELERY_MODELS_FOLDER,
    CELERY_TEMP_FOLDER,
    SQLITE_DIFF_TOOL,
    TEMP_FOLDER,
    master_db,
)
from app.connections.connection import master_connection, vacuum_database
from app.logging_config import get_logger
from scheduler._tasks import queries as cleanup_queries

logger = get_logger(__name__)

# Cleanup parameters are loaded from the environment (.env via dotenv, which is
# loaded on import of app.config). Defaults are used when the variable is unset.
TEMP_FILE_RETENTION_MINUTES = int(os.getenv("TEMP_FILE_RETENTION_MINUTES", 60))  # 1 hour
CELERY_LOG_RETENTION_DAYS = int(os.getenv("CELERY_LOG_RETENTION_DAYS", 7))  # 7 days
CELERY_MODEL_RETENTION_DAYS = int(os.getenv("CELERY_MODEL_RETENTION_DAYS", 30))  # 30 days
VACUUM_INTERVAL_DAYS = int(os.getenv("VACUUM_INTERVAL_DAYS", 7))  # 7 days
EXECUTION_LOG_RETENTION_DAYS = int(os.getenv("EXECUTION_LOG_RETENTION_DAYS", 30))
SQL_HISTORY_MAX_RECORDS_PER_USER = int(os.getenv("SQL_HISTORY_MAX_RECORDS_PER_USER", 100))
TASK_HISTORY_MAX_RECORDS_PER_USER = int(os.getenv("TASK_HISTORY_MAX_RECORDS_PER_USER", 30))


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
        "temp_files": _cleanup_folder(TEMP_FOLDER, TEMP_FILE_RETENTION_MINUTES * 60),
        "celery_temp_files": _cleanup_folder(CELERY_TEMP_FOLDER, TEMP_FILE_RETENTION_MINUTES * 60),
        "celery_log_files": _cleanup_folder(CELERY_LOG_FOLDER, CELERY_LOG_RETENTION_DAYS * 86400),
        "celery_model_files": _cleanup_folder(CELERY_MODELS_FOLDER, CELERY_MODEL_RETENTION_DAYS * 86400),
    }

    master_vacuumed = await asyncio.to_thread(_query, master_db, db_type="SQLITE")
    user_models_vacuum = await vacuum_user_models({})
    db_cleanup_results = await asyncio.to_thread(db_cleanup)
    return {
        "deleted_counts": deleted_counts,
        "master_vacuumed": bool(master_vacuumed),
        "user_models_vacuum": user_models_vacuum,
        "db_cleanup": db_cleanup_results,
    }


def _query(db_path, db_type: str):
    connection = None
    try:
        vacuum_database(db_path, db_type=db_type)
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

    for model_id, model_path, last_vacuum_date, db_type in models:
        checked_count += 1
        do_vacuum = False
        if not model_path or not os.path.isfile(model_path):
            skipped_count += 1
            continue
        file_age = time.time() - os.path.getmtime(model_path)
        if file_age < VACUUM_INTERVAL_DAYS * 86400:
            skipped_count += 1
            continue  # Skip if file is not old enough for vacuuming

        if last_vacuum_date:
            vacuum_date = _parse_last_vacuum_date(last_vacuum_date)
            if not vacuum_date:
                skipped_count += 1
                continue  # Skip if last vacuum date is invalid
            vacuum_age = (datetime.now(timezone.utc) - vacuum_date).total_seconds()
            if vacuum_age < VACUUM_INTERVAL_DAYS * 86400:
                skipped_count += 1
                continue  # Skip if vacuumed recently
            if abs(file_age - vacuum_age) < 3600:  # 1 hour threshold to account for time differences
                skipped_count += 1
                continue
            do_vacuum = True
        else:
            do_vacuum = True  # No record of vacuuming, so proceed
        if do_vacuum:
            status_dict = await asyncio.to_thread(create_system_backup, model_id, model_path, db_type=db_type)
            if status_dict["status"] == "success":
                vacuumed_count += 1
            elif status_dict["status"] == "skipped":
                skipped_count += 1
            else:
                failed_count += 1

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
            (TASK_HISTORY_MAX_RECORDS_PER_USER, CELERY_LOG_RETENTION_DAYS),
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


def create_system_backup(model_id, model_path, db_type):
    backup_name = "SYSTEM GENERATED BACKUP"
    backup_uid = str(uuid.uuid4())
    backup_path = os.path.join(BACKUP_FOLDER, f"{backup_uid}.sqlite3")
    if os.path.exists(backup_path):
        return {"status": "error", "message": "Backup file already exists."}
    if not model_path or not os.path.isfile(model_path):
        logger.error(f"Cannot create system backup for model {model_id}: model file not found at {model_path}")
        return {"status": "error", "message": "Model file not found."}

    old_backup_id = None
    old_backup_path = None
    with master_connection() as cursor:
        get_existing_backup = cursor.execute(
            cleanup_queries.get_system_generated_backup, (model_id, backup_name)
        ).fetchone()
        if get_existing_backup:
            old_backup_id, old_backup_path = get_existing_backup

    if old_backup_path and os.path.isfile(old_backup_path):
        if os.path.isfile(SQLITE_DIFF_TOOL) and db_type == "SQLITE":
            try:
                result = subprocess.run(
                    [SQLITE_DIFF_TOOL, old_backup_path, model_path],
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
            except (subprocess.SubprocessError, OSError) as e:
                logger.error(f"sqldiff failed for model {model_id}: {e}. Proceeding to create backup.")
            else:
                if result.returncode != 0:
                    logger.error(
                        f"sqldiff returned {result.returncode} for model {model_id}: "
                        f"{result.stderr.strip()}. Proceeding to create backup."
                    )
                elif not result.stdout.strip():
                    # No differences: the existing backup already matches the model.
                    # Update the vacuum date so the scheduler doesn't re-run sqldiff
                    # on every tick for unchanged models.
                    logger.info(f"System backup for model {model_id} skipped; model unchanged since last backup.")
                    with master_connection() as cursor:
                        cursor.execute(
                            cleanup_queries.update_vacuum_date,
                            (datetime.now(timezone.utc).isoformat(), model_id),
                        )
                    return {"status": "skipped", "message": "Model unchanged since last backup."}
        else:
            if db_type == "SQLITE":
                logger.warning("sqldiff tool not found; creating backup without diff check.")

    try:
        vacuum_database(model_path, db_type=db_type)
    except Exception as e:
        logger.error(f"Failed to create system backup for model {model_id}: {e}")
        return {"status": "error", "message": "Failed to create system backup."}

    try:
        shutil.copy2(model_path, backup_path)
    except OSError as e:
        logger.error(f"Failed to copy model {model_id} to backup path {backup_path}: {e}")
        return {"status": "error", "message": "Failed to copy model file to backup location."}

    with master_connection() as cursor:
        cursor.execute(cleanup_queries.insert_model_backup, (model_id, backup_path, backup_name))
        if old_backup_id is not None:
            cursor.execute(cleanup_queries.delete_backup_by_id, (old_backup_id,))
        cursor.execute(
            cleanup_queries.update_vacuum_date,
            (datetime.now(timezone.utc).isoformat(), model_id),
        )

    # Remove the previous system-generated backup file from disk.
    if old_backup_path and os.path.exists(old_backup_path):
        try:
            os.remove(old_backup_path)
        except OSError as e:
            logger.error(f"Failed to delete old system backup {old_backup_path} for model {model_id}: {e}")

    logger.info(f"Created system backup for model {model_id} at {backup_path}")
    return {"status": "success", "message": f"Created system backup for model {model_id} at {backup_path}"}
