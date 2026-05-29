"""
Scheduler database schema definitions.

This module defines the tables for the scheduler system:
- SJ_ScheduledJobs: Job definitions with cron expressions
- SJ_JobExecutions: Execution history and logs
"""

from app.connection import master_connection
from app.logging_config import get_logger

logger = get_logger(__name__)

create_scheduled_jobs_table = """CREATE TABLE IF NOT EXISTS SJ_ScheduledJobs (
    JobId INTEGER PRIMARY KEY AUTOINCREMENT,
    JobName TEXT NOT NULL UNIQUE,
    JobDescription TEXT,
    TaskType TEXT,
    TaskParams TEXT,
    CronExpression TEXT NOT NULL,
    IsEnabled INTEGER DEFAULT 1,
    MaxRetries INTEGER DEFAULT 3,
    TimeoutSeconds INTEGER DEFAULT 300,
    IsRunning INTEGER DEFAULT 0,
    LastRunAt TEXT,
    NextRunAt TEXT,
    JSONData TEXT,
    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
    UpdatedAt TEXT NOT NULL DEFAULT (datetime('now'))
)"""


create_job_executions_table = """CREATE TABLE IF NOT EXISTS SJ_JobExecutions (
    ExecutionId INTEGER PRIMARY KEY AUTOINCREMENT,
    JobId INTEGER NOT NULL,
    JobName TEXT NOT NULL,
    Status TEXT NOT NULL,
    StartedAt TEXT NOT NULL DEFAULT (datetime('now')),
    CompletedAt TEXT,
    DurationSeconds REAL,
    RetryCount INTEGER DEFAULT 0,
    ErrorMessage TEXT,
    ResultData TEXT,
    JSONData TEXT,
    FOREIGN KEY (JobId) REFERENCES SJ_ScheduledJobs(JobId)
)"""

insert_scheduled_job = """INSERT INTO SJ_ScheduledJobs
    (JobName, JobDescription, TaskType, TaskParams, CronExpression, IsEnabled,
    MaxRetries, TimeoutSeconds, LastRunAt, NextRunAt)
    SELECT ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now', '15 seconds')
    WHERE NOT EXISTS (
        SELECT 1 FROM SJ_ScheduledJobs WHERE JobName = ?
    )"""


def init_scheduler_db() -> None:
    """
    Initialize scheduler database tables and seed scheduled jobs.
    """
    from scheduler.task_init_data import (
        scheduled_jobs,
    )

    logger.info("Initializing scheduler database schema")
    with master_connection() as cursor:
        cursor.execute(create_scheduled_jobs_table)
        cursor.execute(create_job_executions_table)

        # Insert task-type scheduled jobs
        for job in scheduled_jobs:
            cursor.execute(insert_scheduled_job, (*job, job[0]))

    logger.info("Scheduler database schema initialized")
