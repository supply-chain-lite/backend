import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import nullcontext
from uuid import uuid4

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
    SQLITE_DIFF_TOOL,
    TEMP_FOLDER,
)
from app.connection import master_connection, sql_connection
from app.logging_config import get_logger
from app.routers.models.methods import get_model_id_and_path
from app.routers.models.queries import get_access_level, get_template_name

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
        for task_code, task_name, task_params_json in all_rows:
            tasks.append(
                {
                    "task_code": task_code,
                    "task_name": task_name,
                    "task_params": json.loads(task_params_json) if task_params_json else [],
                }
            )
        return tasks


def run_model_task(
    cursor, user_email: str, model_name: str, project_name: str, task_code: int, task_param_values: list
):
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

    template_name = cursor.execute(get_template_name, (model_id,)).fetchone()[0]

    with sql_connection(model_id, model_path) as model_cursor:
        task_name, task_display_name = update_task_param_values(model_cursor, task_code, task_param_values)
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
    kwarg_data = {"db": file_url, "task_name": task_name, "template_name": template_name}

    reserverd_param_names = kwarg_data.keys()
    for params in task_param_values:
        if params.ParameterName in reserverd_param_names:
            raise HTTPException(
                status_code=400,
                detail=f"Reserved parameter name: {params.ParameterName}. ",
            )
        kwarg_data[params.ParameterName] = params.ParameterValue

    # Generate the task UID up front so the ST_TaskRecords row is created and
    # committed *before* the task is enqueued. This guarantees the worker can
    # find (and atomically claim) the row the moment it picks up the task.
    task_uid = str(uuid4())
    row_tuple = (
        model_id,
        task_uid,
        task_code,
        task_display_name,
        model_name,
        project_name,
        user_email,
        "PENDING",
        this_broker_url,
        json.dumps(kwarg_data),
    )
    try:
        row = cursor.execute(run_queries.insert_task_record, row_tuple).fetchone()
        if not row:
            raise RuntimeError("INSERT INTO ST_TaskRecords returned no row")
        task_id = row[0]
    except Exception as e:
        cursor.execute(run_queries.update_model_lock, (0, model_id))
        cursor.intermediate_commit()
        raise HTTPException(status_code=500, detail=f"Failed to insert task record: {str(e)}")

    # Commit the task record (and the model lock) so the worker sees the row
    # before the task is enqueued and can be picked up.
    cursor.intermediate_commit()

    try:
        result = celery_app.send_task("celery_app.run_command", kwargs=kwarg_data, task_id=task_uid)
        if not result or not result.id:
            raise RuntimeError("No task ID returned")
    except Exception as e:
        # Enqueue failed: remove the pending record and release the lock so the
        # model is not left locked with an orphaned PENDING task.
        cursor.execute(run_queries.delete_task_record, (task_id,))
        cursor.execute(run_queries.update_model_lock, (0, model_id))
        cursor.intermediate_commit()
        raise HTTPException(status_code=500, detail=f"Failed to enqueue task for execution: {str(e)}")
    return task_id, task_display_name, model_name, project_name


def update_task_param_values(model_cursor, task_code: int, new_param_values: list):
    task_row = model_cursor.execute(run_queries.get_task_params, (task_code,)).fetchone()
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
    model_cursor.execute(run_queries.update_task_params, (json.dumps(task_params, indent=4), task_code))
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
    this_status, is_user_revoked = cursor.execute(run_queries.get_user_revoked, (task_uid,)).fetchone()
    cursor.intermediate_commit()
    if is_user_revoked:
        new_status = "REVOKED"
        task_status = this_status  # Use the current status from the database for logging
    elif new_status == task_status:
        return new_status  # No status change, no update needed
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


def update_task_output_and_logs(this_cursor, task_id: int, forced_cancel: bool = False):
    cm = master_connection() if this_cursor is None else nullcontext(this_cursor)
    with cm as cursor:
        model_id = None
        try:
            task_status, output_model_path, model_id, model_path = cursor.execute(
                run_queries.get_task_file, (task_id,)
            ).fetchone()

            update_task_log(cursor, task_id, forced_cancel=forced_cancel)
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


def update_task_log(cursor, task_id, forced_cancel=False):
    if forced_cancel:
        time.sleep(2)  # Give Celery a moment to write the cancellation log
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
    if forced_cancel:
        logs += "\n\nTask was forcibly canceled by user."
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
        result,
        kwargs_json,
    ) = task_details
    current_status = status
    if status in ("RUNNING", "STARTED", "PENDING"):
        current_status = _update_task_status(cursor, task_id, task_uid, task_url, status)
        log = update_task_log(cursor, task_id)
    else:
        log = cursor.execute(run_queries.get_task_log, (task_id,)).fetchone()
        log = log[0] if log else "No logs found for this task."

    input_params = json.loads(kwargs_json) if kwargs_json else {}
    keys_to_remove = ["db", "task_name", "template_name"]
    for key in keys_to_remove:
        input_params.pop(key, None)  # Remove the key if it exists, do nothing otherwise

    return {
        "task_name": task_name,
        "submitted_by": submitted_by,
        "start_time": submission_time,
        "end_time": end_time,
        "status": current_status,
        "log": log,
        "input": input_params,
        "output": json.loads(result) if result else None,
    }


def cancel_task(cursor, task_id: int, user_email: str):
    task_row = cursor.execute(run_queries.get_task_uid_and_status, (task_id, user_email)).fetchone()
    if not task_row:
        raise HTTPException(status_code=404, detail="Task not found")
    task_uid, task_status, task_url, pid = task_row
    if task_status not in ("RUNNING", "STARTED", "PENDING"):
        raise HTTPException(
            status_code=400, detail=f"Task is not running and cannot be canceled. Current status: {task_status}"
        )
    cursor.execute(run_queries.update_user_revoked_flag, (task_uid,))  # Set UserRevoked flag
    cursor.intermediate_commit()
    celery_app = Celery("tasks", broker=task_url, backend=task_url)
    try:
        celery_app.control.revoke(task_uid)
        logger.info(f"Attempting to kill child process for task {task_uid}, PID: {pid}")
        if pid:
            try:
                os.kill(pid, 9)  # Force kill the child process
            except Exception as e:
                logger.error(f"Failed to kill child process {pid} for task {task_uid}: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to cancel the task {task_uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to cancel the task")

    _update_task_status(cursor, task_id, task_uid, task_url, task_status)  # Update status to reflect cancellation
    update_task_output_and_logs(cursor, task_id, forced_cancel=True)  # Update logs and release model lock
    return "REVOKED"


def restore_db(cursor, task_id: int, user_email: str, model_name: str, project_name: str):
    task_row = cursor.execute(run_queries.get_task_db_and_details, (task_id,)).fetchone()
    if not task_row:
        raise HTTPException(status_code=404, detail="Task not found")
    this_model_name, this_project_name, this_model_id, task_status, output_model_path = task_row
    if task_status != "SUCCESS":
        raise HTTPException(
            status_code=400,
            detail=f"Task did not succeed and cannot be used to restore the database. Current status: {task_status}",
        )
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    if model_id != this_model_id or model_name != this_model_name or project_name != this_project_name:
        raise HTTPException(
            status_code=400,
            detail=f"Task output belongs to a different model ({this_model_name} in project {this_project_name}) "
            f"and cannot be used to restore the database for model {model_name} in project {project_name}.",
        )
    if not os.path.exists(output_model_path):
        raise HTTPException(
            status_code=500,
            detail=f"Output model file for task {task_id} does not exist at {output_model_path}.",
        )
    access_level, is_running = cursor.execute(get_access_level, (model_id, user_email)).fetchone()
    if is_running:
        raise HTTPException(status_code=400, detail="Cannot restore while a task using the model is running")

    if access_level != "owner":
        raise HTTPException(status_code=403, detail="Only owner can restore")
    backup_connection = apsw.Connection(output_model_path)
    this_connection = apsw.Connection(model_path)

    try:
        with this_connection.backup("main", backup_connection, "main") as backup:
            backup.step()  # copy entire database in one step
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore backup: {str(e)}")
    finally:
        this_connection.close()
        backup_connection.close()

    return f"Model {model_name} in project {project_name} restored successfully from task {task_id}"


def get_diff(cursor, task_id: int, user_email: str, model_name: str, project_name: str):
    task_row = cursor.execute(run_queries.get_task_db_and_details, (task_id,)).fetchone()
    if not task_row:
        raise HTTPException(status_code=404, detail="Task not found")
    this_model_name, this_project_name, this_model_id, _task_status, task_model_path = task_row

    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    if model_id != this_model_id or model_name != this_model_name or project_name != this_project_name:
        raise HTTPException(
            status_code=400,
            detail=f"Task output belongs to a different model ({this_model_name} in project {this_project_name}) "
            f"and cannot be used to restore the database for model {model_name} in project {project_name}.",
        )
    if not os.path.exists(task_model_path):
        raise HTTPException(
            status_code=500,
            detail=f"Model file for task {task_id} does not exist at {task_model_path}.",
        )

    print(SQLITE_DIFF_TOOL)
    if not os.path.exists(SQLITE_DIFF_TOOL):
        raise HTTPException(
            status_code=500,
            detail="SQLITE diff tool not found. Please check the configuration.",
        )

    # Use the sqlite diff tool to get the difference between the current model
    # database and the task output database. The --summary flag produces a
    # per-table summary of changes rather than the full set of SQL statements.
    try:
        result = subprocess.run(
            [SQLITE_DIFF_TOOL, "--summary", task_model_path, model_path],
            capture_output=True,
            text=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run SQLITE diff tool: {str(e)}")

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"SQLITE diff tool failed: {result.stderr.strip()}",
        )

    return result.stdout
