"""
Scheduler database schema definitions.

This module defines the tables for the scheduler system:
- SJ_TaskMaster: Task definitions (what to run)
- SJ_ScheduledJobs: Schedules for tasks (when to run)
- SJ_JobExecutions: Execution history and logs
"""

from app.connection import master_connection
from app.logging_config import get_logger

logger = get_logger(__name__)

create_task_master_table = """CREATE TABLE IF NOT EXISTS SJ_TaskMaster (
    TaskId INTEGER PRIMARY KEY AUTOINCREMENT,
    TaskName TEXT NOT NULL UNIQUE,
    TaskDescription TEXT,
    TaskParams TEXT,
    MaxRetries INTEGER DEFAULT 3,
    TimeoutSeconds INTEGER DEFAULT 300,
    JSONData TEXT,
    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
    UpdatedAt TEXT NOT NULL DEFAULT (datetime('now'))
)"""

create_scheduled_jobs_table = """CREATE TABLE IF NOT EXISTS SJ_ScheduledJobs (
    ScheduleId INTEGER PRIMARY KEY AUTOINCREMENT,
    TaskId INTEGER NOT NULL,
    ScheduleType TEXT NOT NULL DEFAULT 'cron',
    CronExpression TEXT,
    IsEnabled INTEGER DEFAULT 1,
    IsRunning INTEGER DEFAULT 0,
    LastRunAt TEXT,
    NextRunAt TEXT,
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
    (TaskName, TaskDescription, TaskParams, MaxRetries, TimeoutSeconds)
    SELECT ?, ?, ?, ?, ?
    WHERE NOT EXISTS (
        SELECT 1 FROM SJ_TaskMaster WHERE TaskName = ?
    )"""

insert_scheduled_job = """INSERT INTO SJ_ScheduledJobs
    (TaskId, ScheduleType, CronExpression, IsEnabled, LastRunAt, NextRunAt)
    SELECT t.TaskId, ?, ?, ?, datetime('now'), datetime('now', '15 seconds')
    FROM SJ_TaskMaster t
    WHERE t.TaskName = ?
    AND NOT EXISTS (
        SELECT 1 FROM SJ_ScheduledJobs sj
        WHERE sj.TaskId = t.TaskId
        AND sj.ScheduleType = ?
        AND COALESCE(sj.CronExpression, '') = COALESCE(?, '')
    )"""


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
            # schedule: [TaskName, ScheduleType, CronExpression, IsEnabled]
            task_name, schedule_type, cron_expr, is_enabled = schedule
            cursor.execute(
                insert_scheduled_job,
                (schedule_type, cron_expr, is_enabled, task_name, schedule_type, cron_expr),
            )

    logger.info("Scheduler database schema initialized")
