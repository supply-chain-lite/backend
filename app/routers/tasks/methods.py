import json
import os
import shutil
import tempfile
from contextlib import nullcontext

import apsw
import boto3
import redis
from botocore.exceptions import BotoCoreError, ClientError
from celery import Celery
from fastapi import BackgroundTasks, HTTPException

from app.config import (
    BROKER_URL,
    CELERY_LOG_FOLDER,
    CELERY_MODELS_FOLDER,
    S3_ACCESS_KEY,
    S3_BUCKET_NAME,
    S3_SECRET_KEY,
    S3_URL,
    SETUP_S3,
    TEMP_FOLDER,
)
from app.connection import master_connection, sql_connection
from app.logging_config import get_logger
from app.routers.models.methods import get_model_id_and_path
from app.routers.models.queries import get_access_level

from . import queries as run_queries

logger = get_logger(__name__)


def list_model_tasks(cursor, user_email: str, model_name: str, project_name: str):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    with sql_connection(model_id, model_path) as model_cursor:
        try:
            all_rows = model_cursor.execute(run_queries.list_task_query, silent=True).fetchall()
        except Exception:
            all_rows = []
        tasks = []
        for task_id, task_name, task_params_json in all_rows:
            tasks.append(
                {
                    "task_id": task_id,
                    "task_name": task_name,
                    "task_params": json.loads(task_params_json) if task_params_json else [],
                }
            )
        return tasks


def run_model_task(cursor, user_email: str, model_name: str, project_name: str, task_id: int, task_param_values: list):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    access_level = cursor.execute(get_access_level, (model_id, user_email)).fetchone()

    if access_level is None or access_level[0] in ("read", "reader", "readonly"):
        raise HTTPException(status_code=403, detail="User does not have permission to run the model")

    current_running_instances = cursor.execute(run_queries.get_current_running_tasks, (model_id,)).fetchone()[0]

    if current_running_instances >= 1:
        raise HTTPException(
            status_code=400,
            detail="Another instance of this model is already running. "
            "Please wait for it to finish before starting a new one.",
        )

    user_model_run_count = cursor.execute(run_queries.get_user_model_run_count, (user_email,)).fetchone()[0]
    user_run_count = cursor.execute(run_queries.get_user_run_count, (user_email,)).fetchone()[0]
    if user_model_run_count >= user_run_count:
        raise HTTPException(
            status_code=400,
            detail=f"You have reached your concurrent run limit"
            f" of {user_run_count}. "
            "Please wait for one of your running tasks to finish before starting a new one.",
        )

    with sql_connection(model_id, model_path) as model_cursor:
        task_name, task_display_name = update_task_param_values(model_cursor, task_id, task_param_values)
        if not task_name:
            raise HTTPException(status_code=404, detail=f"Task: {task_display_name} not found")
        this_broker_url = model_cursor.execute(run_queries.get_broker_url).fetchone()
        if not this_broker_url:
            this_broker_url = BROKER_URL
        else:
            this_broker_url = this_broker_url[0]

        redis_instance = redis.Redis.from_url(this_broker_url, socket_connect_timeout=1)
        try:
            redis_instance.ping()
        except redis.exceptions.RedisError as e:
            raise HTTPException(status_code=500, detail=f"Could not connect to Redis at {this_broker_url}. Error: {e}")
    cursor.execute(run_queries.update_model_lock, (1, model_id))
    cursor.intermediate_commit()

    try:
        file_url = _copy_db_and_upload_to_broker(model_path)
    except Exception as e:
        cursor.execute(run_queries.update_model_lock, (0, model_id))
        cursor.intermediate_commit()
        raise HTTPException(status_code=500, detail=f"Failed to prepare model for execution: {str(e)}")

    celery_app = Celery("tasks", broker=this_broker_url, backend=this_broker_url)
    kwarg_data = {"file_url": file_url, "task_name": task_name}
    try:
        result = celery_app.send_task("celery_app.run_command", kwargs=kwarg_data)
    except Exception as e:
        cursor.execute(run_queries.update_model_lock, (0, model_id))
        cursor.intermediate_commit()
        raise HTTPException(status_code=500, detail=f"Failed to enqueue task for execution: {str(e)}")
    if not result or not result.id:
        cursor.execute(run_queries.update_model_lock, (0, model_id))
        cursor.intermediate_commit()
        raise HTTPException(status_code=500, detail="Failed to enqueue task for execution: No task ID returned")
    if result.state == "FAILURE":
        cursor.execute(run_queries.update_model_lock, (0, model_id))
        cursor.intermediate_commit()
        raise HTTPException(status_code=500, detail="Failed to enqueue task for execution: Task is in FAILURE state")
    task_uid = result.id
    task_status = result.state
    if task_status == "SUCCESS":
        task_status = "STARTED"  # Celery may return SUCCESS immediately, but the task is actually STARTED

    row_tuple = (
        model_id,
        task_uid,
        task_id,
        task_display_name,
        model_name,
        project_name,
        user_email,
        task_status,
        this_broker_url,
        json.dumps(kwarg_data),
    )
    try:
        row = cursor.execute(run_queries.insert_task_record, row_tuple).fetchone()
        if not row:
            raise RuntimeError("INSERT INTO ST_TaskRecords returned no row")
        celery_task_id = row[0]
    except Exception as e:
        # The Celery task is already queued; revoke it before releasing the lock
        # so it cannot run without a corresponding ST_TaskRecords row.
        try:
            celery_app.control.revoke(task_uid, terminate=True)
        except Exception:
            pass  # best-effort – revocation failure must not hide the original error
        cursor.execute(run_queries.update_model_lock, (0, model_id))
        cursor.intermediate_commit()
        raise HTTPException(status_code=500, detail=f"Failed to insert task record: {str(e)}")
    return celery_task_id, task_display_name, model_name, project_name


def update_task_param_values(model_cursor, task_id: int, new_param_values: list):
    task_row = model_cursor.execute(run_queries.get_task_params, (task_id,)).fetchone()
    if not task_row:
        raise HTTPException(status_code=404, detail="Task not found")
    task_name, task_display_name, task_params_json = task_row
    if len(new_param_values) == 0:
        return task_name, task_display_name
    task_params = json.loads(task_params_json) if task_params_json else []
    for this_dict in task_params:
        if this_dict["ParameterType"] == "FIXED":
            continue  # skip fixed parameters since they can't be updated
        for new_param in new_param_values:
            if this_dict["ParameterName"] == new_param.ParameterName:
                this_dict["ParameterValue"] = new_param.ParameterValue
                break
    model_cursor.execute(run_queries.update_task_params, (json.dumps(task_params, indent=4), task_id))
    return task_name, task_display_name


def _copy_db_and_upload_to_broker(model_path: str):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db", dir=TEMP_FOLDER)
    tmp.close()  # Close the file so that it can be used by other processes

    connection = apsw.Connection(model_path)
    try:
        connection.execute(f"VACUUM INTO '{tmp.name}'")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create a copy of the model for upload: {str(e)}")
    finally:
        connection.close()

    tmp_path = tmp.name

    if SETUP_S3:
        raise HTTPException(status_code=500, detail="S3 upload for task execution is not implemented yet")
        s3_client = boto3.client(
            "s3", aws_access_key_id=S3_ACCESS_KEY, aws_secret_access_key=S3_SECRET_KEY, endpoint_url=S3_URL
        )

        try:
            s3_key = f"model_copies/{os.path.basename(tmp_path)}"
            s3_client.upload_file(tmp_path, S3_BUCKET_NAME, s3_key)
            presigned_url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET_NAME, "Key": s3_key},
                ExpiresIn=3600,  # URL expires in 1 hour
            )
            return presigned_url
        except (BotoCoreError, ClientError) as e:
            raise HTTPException(status_code=500, detail=f"Failed to upload model copy to S3: {str(e)}")
        finally:
            os.remove(tmp_path)
    else:
        shutil.copy(tmp_path, CELERY_MODELS_FOLDER)
        os.remove(tmp_path)
        return os.path.join(CELERY_MODELS_FOLDER, os.path.basename(tmp_path))


def get_running_tasks(cursor, user_email: str, background_tasks: BackgroundTasks):
    running_tasks = cursor.execute(run_queries.get_running_tasks, (user_email,)).fetchall()
    task_list = []
    for task_id, task_name, model_name, project_name, task_uid, task_url, task_status in running_tasks:
        try:
            current_status = _update_task_status(cursor, task_id, task_uid, task_url, task_status)
        except Exception as e:
            logger.error(f"Error updating status for task {task_id}: {e}")
            current_status = task_status  # Fall back to existing status if update fails
        if current_status not in ("RUNNING", "STARTED", "PENDING"):
            background_tasks.add_task(update_task_output_and_logs, None, task_id)
            continue  # Only include tasks that are still running
        task_list.append(
            {
                "task_id": task_id,
                "task_name": task_name,
                "model_name": model_name,
                "project_name": project_name,
            }
        )
    return task_list


def get_task_status(cursor, task_id: int, user_email: str):
    status_row = cursor.execute(run_queries.get_task_status, (task_id, user_email)).fetchone()
    if not status_row:
        raise HTTPException(status_code=404, detail="Task not found")
    return status_row[0]


def update_task_status(cursor):
    all_running_tasks = cursor.execute(run_queries.get_all_running_tasks).fetchall()
    for task_id, task_uid, task_url, task_status in all_running_tasks:
        try:
            current_status = _update_task_status(cursor, task_id, task_uid, task_url, task_status)
            if current_status in ("SUCCESS", "COMPLETED", "FAILURE", "ERRORED", "REVOKED"):
                update_task_output_and_logs(cursor, task_id)
        except Exception as e:
            logger.error(f"Error updating status for task {task_id}: {e}")


def _update_task_status(cursor, task_id: int, task_uid: str, task_url: str, task_status: str):
    celery_app = Celery("tasks", broker=task_url, backend=task_url)
    result = celery_app.AsyncResult(task_uid)
    new_status = result.state
    if new_status == task_status:
        return new_status  # No status change, no update needed
    cursor.intermediate_commit()
    cursor.execute(run_queries.update_task_status, (new_status, task_id, task_status))
    result = cursor.fetchall()
    if not result:
        raise HTTPException(status_code=404, detail="Task not found for status update")
    task_name, model_name, project_name, submitted_by, execution_time = result[0]
    if new_status in ("RUNNING", "STARTED", "PENDING"):
        return new_status  # Don't send notification for running status, only for completion or failure
    notification_params = {
        "model_name": model_name,
        "project_name": project_name,
        "task_name": task_name,
        "run_status": new_status,
        "run_time_minutes": execution_time,
        "task_id": task_id,
    }
    notification_type = "task_update"
    if new_status in ("SUCCESS", "COMPLETED"):
        notification_params["LEVEL"] = "INFO"
        title = f"Task {task_name} completed"
        message = f"Your task {task_name} has completed successfully in {execution_time} minutes."
    elif new_status in ("FAILURE", "ERRORED"):
        notification_params["LEVEL"] = "ERROR"
        title = f"Task {task_name} failed"
        message = (
            f"Your task {task_name} has failed in {execution_time} minutes. Please check the logs for more details."
        )
    elif new_status == "REVOKED":
        notification_params["LEVEL"] = "WARNING"
        title = f"Task {task_name} revoked"
        message = f"Your task {task_name} has been revoked after {execution_time} minutes."
    else:
        notification_params["LEVEL"] = "WARNING"
        title = f"Task {task_name} status update"
        message = f"Your task {task_name} status has been updated to {new_status} after {execution_time} minutes."
    insert_task_tuple = (
        "System",
        submitted_by,
        title,
        message,
        notification_type,
        json.dumps(notification_params),
    )
    cursor.execute(run_queries.insert_task_notifications, insert_task_tuple)
    cursor.intermediate_commit()
    return new_status


def add_error_notification(cursor, task_id: int, task_status: str, error_message: str):
    new_status = "POST-EXECUTION ERROR"
    cursor.intermediate_commit()
    cursor.execute(run_queries.update_task_status, (new_status, task_id, task_status))
    result = cursor.fetchall()
    if len(result) == 0:
        return new_status  # Task not found, can't add notification
    task_name, model_name, project_name, submitted_by, execution_time = result[0]
    notification_params = {
        "model_name": model_name,
        "project_name": project_name,
        "task_name": task_name,
        "run_status": new_status,
        "run_time_minutes": execution_time,
        "error_message": error_message,
        "task_id": task_id,
    }
    notification_type = "task_update"
    title = f"Task {task_name} encountered an error"
    message = f"Your task {task_name} encountered an error: {error_message}"
    insert_task_tuple = (
        "System",
        submitted_by,
        title,
        message,
        notification_type,
        json.dumps(notification_params),
    )
    cursor.execute(run_queries.insert_task_notifications, insert_task_tuple)
    cursor.intermediate_commit()
    return new_status


def update_task_output_and_logs(this_cursor, task_id: int):
    cm = master_connection() if this_cursor is None else nullcontext(this_cursor)
    with cm as cursor:
        model_id = None
        try:
            task_status, output_model_path, model_id, model_path = cursor.execute(
                run_queries.get_task_file, (task_id,)
            ).fetchone()

            update_task_log(cursor, task_id)
            # s3 is not implemented for task output yet, so we only handle local file output for now
            if os.path.exists(output_model_path) and task_status in ("SUCCESS", "COMPLETED"):
                backup_connection = apsw.Connection(output_model_path)
                this_connection = apsw.Connection(model_path)
                try:
                    with this_connection.backup("main", backup_connection, "main") as backup:
                        backup.step()  # copy entire database in one step
                except Exception as e:
                    logger.error(f"Failed to update model with task output: {str(e)}")
                    add_error_notification(
                        cursor, task_id, task_status, f"Failed to update model with task output: {str(e)}"
                    )
                finally:
                    backup_connection.close()
                    this_connection.close()
                    cursor.execute(run_queries.update_model_lock, (0, model_id))
            else:
                cursor.execute(run_queries.update_model_lock, (0, model_id))
        finally:
            if model_id:
                cursor.execute(run_queries.update_model_lock, (0, model_id))
                cursor.intermediate_commit()


def update_task_log(cursor, task_id):
    this_rows = cursor.execute(run_queries.get_task_uid, (task_id,)).fetchall()
    if len(this_rows) == 0:
        logger.error(f"Task with ID {task_id} not found for log update")
        return
    task_uid = this_rows[0][0]
    log_file_path = os.path.join(CELERY_LOG_FOLDER, f"{task_uid}.log")
    if os.path.exists(log_file_path):
        with open(log_file_path, "r") as log_file:
            logs = log_file.read()
    else:
        logs = "No logs found for this task."
    cursor.intermediate_commit()
    this_row = cursor.execute(run_queries.update_task_log, (logs, task_id)).fetchone()
    if not this_row:
        cursor.execute(run_queries.insert_task_log, (logs, task_id))
    cursor.intermediate_commit()
    return logs


def get_task_details(cursor, task_id: int, user_email: str, model_name: str, project_name: str):
    model_id, _ = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    task_details = cursor.execute(run_queries.get_task_details, (task_id, model_id)).fetchone()
    if not task_details:
        raise HTTPException(status_code=404, detail="Task not found")
    (
        task_name,
        status,
        submitted_by,
        submission_time,
        end_time,
        task_uid,
        task_url,
    ) = task_details
    current_status = status
    if status in ("RUNNING", "STARTED", "PENDING"):
        current_status = _update_task_status(cursor, task_id, task_uid, task_url, status)
        log = update_task_log(cursor, task_id)
    else:
        log = cursor.execute(run_queries.get_task_log, (task_id,)).fetchone()
        log = log[0] if log else "No logs found for this task."

    return {
        "task_name": task_name,
        "submitted_by": submitted_by,
        "start_time": submission_time,
        "end_time": end_time,
        "status": current_status,
        "log": log,
    }
