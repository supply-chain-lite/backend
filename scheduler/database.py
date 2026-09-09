"""
Scheduler database schema definitions.

This module defines the tables for the scheduler system:
- SJ_TaskMaster: Task definitions (what to run)
- SJ_ScheduledJobs: Schedules for tasks (when to run)
- SJ_JobExecutions: Execution history and logs
"""

from cron_descriptor import CasingTypeEnum, ExpressionDescriptor, Options

from app.connection import master_connection
from app.logging_config import get_logger

logger = get_logger(__name__)

create_task_master_table = """CREATE TABLE IF NOT EXISTS SJ_TaskMaster (
    TaskId INTEGER PRIMARY KEY AUTOINCREMENT,
    TaskName TEXT NOT NULL UNIQUE,
    TaskDescription TEXT,
    MaxRetries INTEGER DEFAULT 3,
    TimeoutSeconds INTEGER DEFAULT 300,
    JSONData TEXT,
    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
    UpdatedAt TEXT NOT NULL DEFAULT (datetime('now'))
)"""

create_scheduled_jobs_table = """CREATE TABLE IF NOT EXISTS SJ_ScheduledJobs (
    ScheduleId INTEGER PRIMARY KEY AUTOINCREMENT,
    TaskId INTEGER NOT NULL,
    ScheduleDescription TEXT,
    TaskParams TEXT,
    ScheduleType TEXT NOT NULL DEFAULT 'cron',
    CronExpression TEXT,
    IsEnabled INTEGER DEFAULT 1,
    IsRunning INTEGER DEFAULT 0,
    LastRunAt TEXT,
    NextRunAt TEXT,
    CreatedBy TEXT,
    JSONData TEXT,
    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
    UpdatedAt TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (TaskId) REFERENCES SJ_TaskMaster(TaskId)
)"""

create_job_executions_table = """CREATE TABLE IF NOT EXISTS SJ_JobExecutions (
    ExecutionId INTEGER PRIMARY KEY AUTOINCREMENT,
    ScheduleId INTEGER NOT NULL,
    TaskId INTEGER NOT NULL,
    TaskName TEXT NOT NULL,
    Status TEXT NOT NULL,
    StartedAt TEXT NOT NULL DEFAULT (datetime('now')),
    CompletedAt TEXT,
    DurationSeconds REAL,
    RetryCount INTEGER DEFAULT 0,
    ErrorMessage TEXT,
    ResultData TEXT,
    JSONData TEXT,
    FOREIGN KEY (ScheduleId) REFERENCES SJ_ScheduledJobs(ScheduleId),
    FOREIGN KEY (TaskId) REFERENCES SJ_TaskMaster(TaskId)
)"""

insert_task_master = """INSERT INTO SJ_TaskMaster
    (TaskName, TaskDescription, MaxRetries, TimeoutSeconds)
    SELECT ?, ?, ?, ?
    WHERE NOT EXISTS (
        SELECT 1 FROM SJ_TaskMaster WHERE TaskName = ?
    )"""

insert_scheduled_job = """INSERT INTO SJ_ScheduledJobs
    (TaskId, ScheduleType, CronExpression, IsEnabled, ScheduleDescription, TaskParams, LastRunAt, NextRunAt)
    SELECT t.TaskId, ?, ?, ?, ?, ?, datetime('now'), datetime('now', '15 seconds')
    FROM SJ_TaskMaster t
    WHERE t.TaskName = ?
    AND NOT EXISTS (
        SELECT 1 FROM SJ_ScheduledJobs sj
        WHERE sj.TaskId = t.TaskId
    )"""

update_cron_schedule_description = """UPDATE SJ_ScheduledJobs
    SET ScheduleDescription = ?,
        UpdatedAt = datetime('now')
    WHERE ScheduleId = ?"""


def get_cron_description(cron_expr: str | None) -> str | None:
    """Return a human-readable schedule description for a cron expression."""
    if not cron_expr:
        return None

    options = Options()
    options.casing_type = CasingTypeEnum.Sentence
    options.use_24hour_time_format = True
    return ExpressionDescriptor(cron_expr, options).get_description()


def refresh_cron_schedule_descriptions(cursor) -> None:
    """
    Update existing cron schedules so their descriptions match CronExpression.

    This keeps seeded and already-existing rows in sync when cron expressions
    change or when cron-descriptor wording changes after a dependency update.
    """
    cron_schedules = cursor.execute(
        """SELECT ScheduleId, CronExpression
        FROM SJ_ScheduledJobs
        WHERE ScheduleType = 'cron'
        AND CronExpression IS NOT NULL
        AND TRIM(CronExpression) != ''"""
    ).fetchall()

    for schedule_id, cron_expr in cron_schedules:
        try:
            description = get_cron_description(cron_expr)
        except Exception as exc:
            logger.warning(
                "Could not describe cron expression '%s' for schedule %s: %s",
                cron_expr,
                schedule_id,
                exc,
            )
            continue

        if description:
            cursor.execute(update_cron_schedule_description, (description, schedule_id))


def init_scheduler_db() -> None:
    """
    Initialize scheduler database tables and seed scheduled jobs.
    """
    from scheduler.task_init_data import (
        task_definitions,
        task_schedules,
    )

    logger.info("Initializing scheduler database schema")
    with master_connection() as cursor:
        cursor.execute(create_task_master_table)
        cursor.execute(create_scheduled_jobs_table)
        cursor.execute(create_job_executions_table)

        # Insert task definitions
        for task in task_definitions:
            cursor.execute(insert_task_master, (*task, task[0]))

        # Insert schedules for tasks
        for schedule in task_schedules:
            # schedule: [TaskName, ScheduleType, CronExpression, IsEnabled, ScheduleDescription, TaskParams]
            task_name, schedule_type, cron_expr, is_enabled, schedule_description, task_params = schedule
            if schedule_type == "cron":
                schedule_description = get_cron_description(cron_expr) or schedule_description
            cursor.execute(
                insert_scheduled_job,
                (schedule_type, cron_expr, is_enabled, schedule_description, task_params, task_name),
            )

        refresh_cron_schedule_descriptions(cursor)

    logger.info("Scheduler database schema initialized")
