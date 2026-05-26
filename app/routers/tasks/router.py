"""API routes for task management and execution operations."""

from fastapi import APIRouter, BackgroundTasks, Depends

from app.connection import master_connection
from app.routers.auth.methods import _get_user_from_token

from . import methods as run_methods
from . import schemas as run_schemas

router = APIRouter()


@router.post("/list", response_model=run_schemas.ListTasksResponse)
def list_model_tasks(
    request: run_schemas.ListTasksRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> run_schemas.ListTasksResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name
    with master_connection() as cursor:
        tasks = run_methods.list_model_tasks(cursor, useremail, model_name, project_name)
    return run_schemas.ListTasksResponse(tasks=tasks)


@router.post("/run", response_model=run_schemas.MessageResponse)
def run_model_task(
    request: run_schemas.runTaskRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> run_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name
    task_id = request.task_id
    task_param_values = request.task_params
    with master_connection() as cursor:
        run_methods.run_model_task(cursor, useremail, model_name, project_name, task_id, task_param_values)
    return run_schemas.MessageResponse(message="Task executed successfully")


@router.post("/running", response_model=run_schemas.runningTasksResponse)
def get_running_tasks(
    background_tasks: BackgroundTasks,
    user_data: tuple = Depends(_get_user_from_token),
) -> run_schemas.runningTasksResponse:
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        running_tasks = run_methods.get_running_tasks(cursor, useremail, background_tasks)
    return run_schemas.runningTasksResponse(running_tasks=running_tasks)


@router.post("/status", response_model=run_schemas.MessageResponse)
def get_task_status(
    request: run_schemas.taskStatusRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> run_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    task_id = request.task_id
    with master_connection() as cursor:
        status = run_methods.get_task_status(cursor, task_id, useremail)
    return run_schemas.MessageResponse(message=status)
