import json
import os
import shutil
import tempfile

import apsw
import boto3
import redis
from botocore.exceptions import BotoCoreError, ClientError
from celery import Celery
from fastapi import HTTPException

from app.config import (
    BROKER_URL,
    MODELS_FOLDER,
    S3_ACCESS_KEY,
    S3_BUCKET_NAME,
    S3_SECRET_KEY,
    S3_URL,
    SETUP_S3,
    TEMP_FOLDER,
)
from app.connection import sql_connection
from app.routers.models.methods import get_model_id_and_path
from app.routers.models.queries import get_access_level

from . import queries as run_queries


def list_model_tasks(cursor, user_email: str, model_name: str, project_name: str):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    with sql_connection(model_id, model_path) as model_cursor:
        try:
            all_rows = model_cursor.execute(run_queries.list_task_query).fetchall()
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
        task_name = update_task_param_values(model_cursor, task_id, task_param_values)
        if not task_name:
            raise HTTPException(status_code=404, detail="Task not found")
        this_broker_url = model_cursor.execute(run_queries.get_broker_url).fetchone()
        if not this_broker_url:
            this_broker_url = BROKER_URL
        else:
            this_broker_url = this_broker_url[0]

        redis_instance = redis.Redis.from_url(this_broker_url, socket_connect_timeout=1)
        try:
            redis_instance.ping()
        except redis.exceptions.RedisError as e:
            raise Exception(f"Could not connect to Redis at {this_broker_url}. Error: {e}")

    file_url = _copy_db_and_upload_to_broker(model_path)

    celery_app = Celery("tasks", broker=this_broker_url, backend=this_broker_url)
    kwarg_data = {"file_url": file_url}
    try:
        result = celery_app.send_task(task_name, kwargs=kwarg_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enqueue task for execution: {str(e)}")
    task_uid = result.id
    task_status = result.state
    row_tuple = (
        model_id,
        task_uid,
        task_name,
        model_name,
        project_name,
        user_email,
        task_status,
        json.dumps(kwarg_data),
    )
    cursor.execute(run_queries.insert_task_record, row_tuple)


def update_task_param_values(model_cursor, task_id: int, new_param_values: list):
    task_row = model_cursor.execute(run_queries.get_task_params, (task_id,)).fetchone()
    if not task_row:
        raise HTTPException(status_code=404, detail="Task not found")
    task_name, task_params_json = task_row
    if len(new_param_values) == 0:
        return task_name
    task_params = json.loads(task_params_json) if task_params_json else []
    for this_dict in task_params:
        for new_param in new_param_values:
            if this_dict["ParameterName"] == new_param.ParameterName:
                this_dict["ParameterValue"] = new_param.ParameterValue
                break
    model_cursor.execute(run_queries.update_task_params, (json.dumps(task_params, indent=4), task_id))
    return task_name


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
        shutil.copy(tmp_path, MODELS_FOLDER)
        os.remove(tmp_path)
        return os.path.join(MODELS_FOLDER, os.path.basename(tmp_path))
