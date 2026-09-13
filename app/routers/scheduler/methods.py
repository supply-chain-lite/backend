import json
from datetime import datetime, timedelta, timezone
from typing import Any

from cron_descriptor import CasingTypeEnum, ExpressionDescriptor, Options
from croniter import CroniterBadCronError, CroniterBadDateError, croniter
from fastapi import HTTPException

from app.routers.models.methods import get_model_details
from app.routers.tasks.methods import get_task_details

from . import queries as scheduler_queries
from . import schemas as scheduler_schemas

DB_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


_JSON_FALLBACK_UNSET = object()


def _loads_json(value: str | None, fallback: Any = _JSON_FALLBACK_UNSET) -> Any:
    if value is None or value == "":
        return {} if fallback is _JSON_FALLBACK_UNSET else fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _api_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, DB_TIME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return value
    return parsed.isoformat().replace("+00:00", "Z")


def _next_cron_run(cron_expression: str) -> str:
    try:
        return croniter(cron_expression, datetime.now(timezone.utc)).get_next(datetime).strftime(DB_TIME_FORMAT)
    except (CroniterBadCronError, CroniterBadDateError):
        raise HTTPException(status_code=400, detail="Invalid cron expression")


def _cron_description(cron_expression: str) -> str | None:
    options = Options()
    options.casing_type = CasingTypeEnum.Sentence
    options.use_24hour_time_format = True
    try:
        return ExpressionDescriptor(cron_expression, options).get_description()
    except Exception:
        return None


def _validate_schedule_fields(
    schedule_type: str,
    cron_expression: str | None,
) -> str | None:
    cron_expression = cron_expression.strip() if cron_expression else None
    if schedule_type != "cron":
        raise HTTPException(status_code=400, detail="Only cron schedules are supported")
    if not cron_expression:
        raise HTTPException(status_code=400, detail="cron_expression is required for cron schedules")
    return _next_cron_run(cron_expression)


def _execution_item(row) -> scheduler_schemas.ExecutionItem:
    return scheduler_schemas.ExecutionItem(
        execution_id=row[0],
        schedule_id=row[1],
        task_id=row[2],
        task_name=row[3],
        status=row[4],
        started_at=_api_datetime(row[5]) or row[5],
        completed_at=_api_datetime(row[6]),
        duration_seconds=row[7],
        retry_count=row[8],
        error_message=row[9],
        result_data=_loads_json(row[10], fallback=None),
    )


def _is_super_admin(role_name: str) -> bool:
    return role_name == "SUPER_ADMIN"


def list_schedules(cursor, user_email: str, role_name: str) -> list[scheduler_schemas.ScheduleItem]:
    schedules = []
    query = scheduler_queries.list_schedules
    params = ()
    if not _is_super_admin(role_name):
        query = scheduler_queries.list_schedules_for_owner
        params = (user_email,)
    for row in cursor.execute(query, params).fetchall():
        schedule_item = scheduler_schemas.ScheduleItem(
            schedule_id=row[0],
            schedule_description=row[1],
            task_id=row[2],
            task_name=row[3],
            task_params=_loads_json(row[4]),
            schedule_type=row[5],
            cron_expression=row[6],
            is_enabled=row[7],
            is_running=row[8],
            last_run_at=_api_datetime(row[9]),
            next_run_at=_api_datetime(row[10]),
            created_by=row[11],
        )
        schedules.append(schedule_item)
    return schedules


def _get_schedule_row(cursor, schedule_id: int):
    row = cursor.execute(scheduler_queries.get_schedule, (schedule_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return row


def _check_schedule_owner(created_by: str, user_email: str, role_name: str) -> None:
    if not _is_super_admin(role_name) and created_by != user_email:
        raise HTTPException(status_code=403, detail="You do not have permission to modify this schedule")


def update_schedule(
    cursor,
    user_email: str,
    role_name: str,
    schedule_id: int,
    cron_expression: str | None,
    is_enabled: int | None,
) -> str | None:
    row = _get_schedule_row(cursor, schedule_id)
    created_by = row[11]
    is_running = row[8]
    _check_schedule_owner(created_by, user_email, role_name)
    if is_running == 1:
        raise HTTPException(status_code=409, detail="Cannot update a running schedule")

    schedule_type = row[5]
    new_cron_expression = row[6]
    next_run_at = row[10]
    if cron_expression is not None and new_cron_expression != cron_expression.strip():
        new_cron_expression = cron_expression.strip()
        next_run_at = _validate_schedule_fields(schedule_type, new_cron_expression)

    new_is_enabled = row[7] if is_enabled is None else is_enabled

    new_cron_description = _cron_description(new_cron_expression)

    cursor.execute(
        scheduler_queries.update_schedule,
        (
            new_cron_expression,
            new_is_enabled,
            next_run_at,
            new_cron_description,
            schedule_id,
        ),
    )
    return _api_datetime(next_run_at)


def run_schedule(
    cursor,
    user_email: str,
    role_name: str,
    request: scheduler_schemas.RunScheduleRequest,
) -> str:
    row = _get_schedule_row(cursor, request.schedule_id)
    created_by = row[11]
    is_running = row[8]
    is_enabled = row[7]
    schedule_type = row[5]
    _check_schedule_owner(created_by, user_email, role_name)
    if schedule_type != "cron":
        raise HTTPException(status_code=400, detail="Only cron schedules can be run manually")
    if is_running == 1:
        raise HTTPException(status_code=409, detail="Cannot run a running schedule")
    if is_enabled != 1:
        raise HTTPException(status_code=400, detail="Schedule is disabled")

    next_run_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).strftime(DB_TIME_FORMAT)
    cursor.execute(scheduler_queries.update_next_run_at, (next_run_at, request.schedule_id))
    return _api_datetime(next_run_at) or next_run_at


def list_executions(cursor, user_email: str, role_name: str, schedule_id: int | None) -> list:
    created_by = None
    if not _is_super_admin(role_name):
        created_by = user_email
    query, params = scheduler_queries.get_schedule_executions(schedule_id, created_by)
    rows = cursor.execute(query, params).fetchall()
    return [_execution_item(row) for row in rows]


def get_task_schedule(
    cursor,
    user_email: str,
    task_code: int,
    model_name: str,
    project_name: str,
):
    model = get_model_details(cursor, model_name, project_name, user_email)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    model_id = model.model_id
    row = cursor.execute(scheduler_queries.get_task_schedule, (model_id, task_code)).fetchone()
    if not row:
        owner_info = model.owner_email
        if owner_info != user_email:
            raise HTTPException(status_code=403, detail="Schedule not found")
        raise HTTPException(status_code=404, detail="Schedule not found")
    cron_expression, schedule_id, is_enabled, created_by, next_run_at = row
    return scheduler_schemas.GetTaskScheduleResponse(
        schedule_id=schedule_id,
        cron_expression=cron_expression,
        is_enabled=is_enabled,
        created_by=created_by,
        next_run_at=_api_datetime(next_run_at),
    )


def set_task_schedule(
    cursor,
    user_email: str,
    role_name: str,
    task_id: int,
    model_name: str,
    project_name: str,
    cron_expression: str,
    is_enabled: int,
    schedule_id: int | None = None,
) -> tuple[int, str] | None:
    if schedule_id is not None:
        return schedule_id, update_schedule(cursor, user_email, role_name, schedule_id, cron_expression, is_enabled)

    model = get_model_details(cursor, model_name, project_name, user_email)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    model_id = model.model_id
    owner_info = model.owner_email
    if owner_info != user_email:
        raise HTTPException(status_code=403, detail="Schedule not found")

    scheduler_task_id = cursor.execute(scheduler_queries.get_task_id, ("run_model_task",)).fetchone()[0]
    schedule_type = "cron"
    schedule_description = _cron_description(cron_expression)
    next_run_at = _validate_schedule_fields(schedule_type, cron_expression)

    task_params = {"model_id": model_id, "user_email": user_email, "task_id": task_id}
    task_details = get_task_details(cursor, task_id, user_email, model_name, project_name)
    task_input_params = task_details["input"]
    task_code = task_details["task_code"]

    task_params.update({"task_code": task_code, "task_input_params": task_input_params})

    insert_params = (
        scheduler_task_id,
        json.dumps(task_params),
        schedule_type,
        cron_expression,
        is_enabled,
        next_run_at,
        schedule_description,
        user_email,
    )
    row = cursor.execute(scheduler_queries.get_task_schedule, (model_id, task_code)).fetchone()
    if row:
        raise HTTPException(status_code=409, detail="A schedule for this task already exists")
    row = cursor.execute(scheduler_queries.insert_schedule, insert_params).fetchone()
    schedule_id, next_run_at = row
    return schedule_id, _api_datetime(next_run_at)
