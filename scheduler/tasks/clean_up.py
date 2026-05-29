import asyncio
import os
import time
from datetime import datetime, timezone

import apsw

from app.config import CELERY_LOG_FOLDER, CELERY_MODELS_FOLDER, CELERY_TEMP_FOLDER, TEMP_FOLDER, master_db
from app.connection import master_connection
from app.logging_config import get_logger

from .queries import get_model_id_and_paths, update_vacuum_date

logger = get_logger(__name__)

TEMP_FILE_RETENTION_SECONDS = 3600  # 1 hour
CELERY_LOG_RETENTION_SECONDS = 7 * 24 * 3600  # 7 days
CELERY_MODEL_RETENTION_SECONDS = 30 * 24 * 3600  # 30 days
VACUUM_INTERVAL_SECONDS = 7 * 24 * 3600  # 7 days


def _cleanup_folder(folder_path, retention_seconds):
    now = time.time()
    deleted_count = 0

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
    return {
        "deleted_counts": deleted_counts,
        "master_vacuumed": bool(master_vacuumed),
        "user_models_vacuum": user_models_vacuum,
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

    parsed_date = datetime.fromisoformat(last_vacuum_date)
    if parsed_date.tzinfo is None:
        return parsed_date.replace(tzinfo=timezone.utc)
    return parsed_date.astimezone(timezone.utc)


async def vacuum_user_models(params: dict | None = None) -> dict:
    del params

    with master_connection() as cursor:
        cursor.execute(get_model_id_and_paths)
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
                    update_vacuum_date,
                    (datetime.now(timezone.utc).isoformat(), model_id),
                )
            vacuumed_count += 1

    return {
        "checked_count": checked_count,
        "skipped_count": skipped_count,
        "vacuumed_count": vacuumed_count,
        "failed_count": failed_count,
    }
