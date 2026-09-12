from fastapi import APIRouter, Depends

from app.connections.connection import master_connection
from app.routers.auth.methods import _get_user_from_token, check_module_access

from . import methods as scheduler_methods
from . import schemas as scheduler_schemas

router = APIRouter()
this_api = "/api/scheduler"


@router.post("/schedules", response_model=scheduler_schemas.ScheduleListResponse)
def list_schedules(
    user_data: tuple = Depends(_get_user_from_token),
) -> scheduler_schemas.ScheduleListResponse:
    useremail, _display_name, role_name = user_data
    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        schedules = scheduler_methods.list_schedules(cursor, useremail, role_name)
    return scheduler_schemas.ScheduleListResponse(schedules=schedules)


@router.post("/update-schedule", response_model=scheduler_schemas.UpdateScheduleResponse)
def update_schedule(
    request: scheduler_schemas.UpdateScheduleRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> scheduler_schemas.UpdateScheduleResponse:
    useremail, _display_name, role_name = user_data
    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        schedule_id = request.schedule_id
        cron_expression = request.cron_expression
        is_enabled = request.is_enabled
        next_run_at = scheduler_methods.update_schedule(
            cursor, useremail, role_name, schedule_id, cron_expression, is_enabled
        )
    return scheduler_schemas.UpdateScheduleResponse(
        next_run_at=next_run_at,
        schedule_id=schedule_id,
        message="Schedule updated successfully",
    )


@router.post("/run", response_model=scheduler_schemas.RunScheduleResponse)
def run_schedule(
    request: scheduler_schemas.RunScheduleRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> scheduler_schemas.RunScheduleResponse:
    useremail, _display_name, role_name = user_data
    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        next_run_at = scheduler_methods.run_schedule(cursor, useremail, role_name, request)
    return scheduler_schemas.RunScheduleResponse(
        next_run_at=next_run_at,
        message="Schedule queued to run",
    )


@router.post("/executions", response_model=scheduler_schemas.ExecutionListResponse)
def list_executions(
    request: scheduler_schemas.ExecutionFiltersRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> scheduler_schemas.ExecutionListResponse:
    useremail, _display_name, role_name = user_data
    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        executions = scheduler_methods.list_executions(cursor, useremail, role_name, request.schedule_id)
    return scheduler_schemas.ExecutionListResponse(executions=executions)


@router.post("/get-task-schedule", response_model=scheduler_schemas.GetTaskScheduleResponse)
def get_task_schedule(
    request: scheduler_schemas.GetTaskScheduleRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> scheduler_schemas.GetTaskScheduleResponse:
    useremail, _display_name, role_name = user_data
    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        schedule = scheduler_methods.get_task_schedule(
            cursor, useremail, request.task_code, request.model_name, request.project_name
        )
    return schedule


@router.post("/set-task-schedule", response_model=scheduler_schemas.UpdateScheduleResponse)
def set_task_schedule(
    request: scheduler_schemas.SetTaskScheduleRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> scheduler_schemas.UpdateScheduleResponse:
    useremail, _display_name, role_name = user_data
    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        schedule_id, next_run_at = scheduler_methods.set_task_schedule(
            cursor,
            useremail,
            role_name,
            request.task_id,
            request.model_name,
            request.project_name,
            request.cron_expression,
            request.is_enabled,
            request.schedule_id,
        )
    return scheduler_schemas.UpdateScheduleResponse(
        next_run_at=next_run_at,
        schedule_id=schedule_id,
        message="Task schedule set successfully",
    )
