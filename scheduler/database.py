"""
Scheduler database schema definitions.

This module defines the tables for the scheduler system:
- S_ScheduledJobs: Job definitions with cron expressions and task categories
- S_JobExecutions: Execution history and logs
- S_Flows: Flow definitions (sequences of tasks)
- S_FlowSteps: Individual steps within a flow
"""

from app.connection import master_connection
from app.logging_config import get_logger

logger = get_logger(__name__)

# Task categories: 'task' for individual tasks, 'flow' for task sequences
create_scheduled_jobs_table = """CREATE TABLE IF NOT EXISTS S_ScheduledJobs (
    JobId INTEGER PRIMARY KEY AUTOINCREMENT,
    JobName TEXT NOT NULL UNIQUE,
    JobDescription TEXT,
    TaskCategory TEXT NOT NULL DEFAULT 'Task',
    TaskType TEXT,
    TaskParams TEXT,
    FlowId INTEGER,
    CronExpression TEXT NOT NULL,
    IsEnabled INTEGER DEFAULT 1,
    MaxRetries INTEGER DEFAULT 3,
    TimeoutSeconds INTEGER DEFAULT 300,
    IsRunning INTEGER DEFAULT 0,
    LastRunAt TEXT,
    NextRunAt TEXT,
    JSONData TEXT,
    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
    UpdatedAt TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (FlowId) REFERENCES S_Flows(FlowId),
    CHECK (TaskCategory IN ('Task', 'Flow')),
    CHECK (
        (TaskCategory = 'Task' AND TaskType IS NOT NULL AND FlowId IS NULL) OR
        (TaskCategory = 'Flow' AND FlowId IS NOT NULL AND TaskType IS NULL)
    )
)"""

# Flows table: defines reusable sequences of tasks
create_flows_table = """CREATE TABLE IF NOT EXISTS S_Flows (
    FlowId INTEGER PRIMARY KEY AUTOINCREMENT,
    FlowName TEXT NOT NULL UNIQUE,
    FlowDescription TEXT,
    StopOnError INTEGER DEFAULT 1,
    JSONData TEXT,
    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
    UpdatedAt TEXT NOT NULL DEFAULT (datetime('now'))
)"""

# Flow steps: individual tasks within a flow, executed in order
create_flow_steps_table = """CREATE TABLE IF NOT EXISTS S_FlowSteps (
    StepId INTEGER PRIMARY KEY AUTOINCREMENT,
    FlowId INTEGER NOT NULL,
    StepOrder INTEGER NOT NULL,
    StepName TEXT NOT NULL,
    TaskType TEXT NOT NULL,
    TaskParams TEXT,
    MaxRetries INTEGER DEFAULT 3,
    TimeoutSeconds INTEGER DEFAULT 300,
    ContinueOnError INTEGER DEFAULT 0,
    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
    JSONData TEXT,
    FOREIGN KEY (FlowId) REFERENCES S_Flows(FlowId),
    UNIQUE (FlowId, StepOrder)
)"""

create_job_executions_table = """CREATE TABLE IF NOT EXISTS S_JobExecutions (
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
    FOREIGN KEY (JobId) REFERENCES S_ScheduledJobs(JobId)
)"""

insert_scheduled_job = """INSERT INTO S_ScheduledJobs
    (JobName, JobDescription, TaskCategory, TaskType, TaskParams, FlowId, CronExpression, IsEnabled,
    MaxRetries, TimeoutSeconds)
    SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
    WHERE NOT EXISTS (
        SELECT 1 FROM S_ScheduledJobs WHERE JobName = ?
    )"""

insert_flow = """INSERT INTO S_Flows (FlowName, FlowDescription, StopOnError)
    SELECT ?, ?, ?
    WHERE NOT EXISTS (
        SELECT 1 FROM S_Flows WHERE FlowName = ?
    )"""

insert_flow_step = """INSERT INTO S_FlowSteps
    (FlowId, StepOrder, StepName, TaskType, TaskParams, MaxRetries, TimeoutSeconds, ContinueOnError)
    SELECT ?, ?, ?, ?, ?, ?, ?, ?
    WHERE NOT EXISTS (
        SELECT 1 FROM S_FlowSteps WHERE FlowId = ? AND StepOrder = ?
    )"""


def init_scheduler_db() -> None:
    """
    Initialize scheduler database tables and seed sample jobs/flows.
    """
    logger.info("Initializing scheduler database schema")
    with master_connection() as cursor:
        cursor.execute(create_scheduled_jobs_table)
        cursor.execute(create_flows_table)
        cursor.execute(create_flow_steps_table)
        cursor.execute(create_job_executions_table)

        # Sample Job 1: Cleanup old task logs (runs daily at 2 AM) - individual task
        cursor.execute(
            insert_scheduled_job,
            (
                "cleanup_old_logs",
                "Remove task logs older than 30 days",
                "Task",
                "cleanup_logs",
                '{"days_to_keep": 30}',
                None,
                "0 2 * * *",
                1,
                3,
                120,
                "cleanup_old_logs",
            ),
        )

        # Sample Job 2: Database statistics report (runs every Monday at 6 AM) - individual task
        cursor.execute(
            insert_scheduled_job,
            (
                "weekly_db_stats",
                "Generate weekly database statistics report",
                "Task",
                "db_stats_report",
                '{"include_tables": ["S_Users", "S_Projects", "S_Models", "S_TaskRecords"]}',
                None,
                "0 6 * * 1",
                1,
                2,
                300,
                "weekly_db_stats",
            ),
        )

        # Job: Celery task update (runs every 20 seconds)
        cursor.execute(
            insert_scheduled_job,
            (
                "celery_task_update",
                "Celery task update job running every 20 seconds",
                "Task",
                "celery_task_update",
                "{}",
                None,
                "* * * * *",
                1,
                3,
                300,
                "celery_task_update",
            ),
        )

        # Sample Flow: Daily maintenance (cleanup logs + generate stats)
        cursor.execute(
            insert_flow,
            (
                "daily_maintenance",
                "Daily maintenance: cleanup old logs then generate stats report",
                1,
                "daily_maintenance",
            ),
        )

        # Get the flow ID for inserting steps
        cursor.execute("SELECT FlowId FROM S_Flows WHERE FlowName = 'daily_maintenance'")
        flow_result = cursor.fetchall()
        if flow_result:
            flow_id = flow_result[0][0]

            # Step 1: Cleanup logs
            cursor.execute(
                insert_flow_step,
                (
                    flow_id,
                    1,
                    "Cleanup Old Logs",
                    "cleanup_logs",
                    '{"days_to_keep": 30}',
                    3,
                    120,
                    0,
                    flow_id,
                    1,
                ),
            )

            # Step 2: Generate stats
            cursor.execute(
                insert_flow_step,
                (
                    flow_id,
                    2,
                    "Generate DB Stats",
                    "db_stats_report",
                    '{"include_tables": ["S_Users", "S_Projects", "S_Models", "S_TaskRecords"]}',
                    2,
                    300,
                    0,
                    flow_id,
                    2,
                ),
            )

            # Schedule the flow to run on Sundays at 3 AM
            cursor.execute(
                insert_scheduled_job,
                (
                    "sunday_maintenance_flow",
                    "Run daily maintenance flow on Sundays",
                    "Flow",
                    None,
                    None,
                    flow_id,
                    "0 3 * * 0",
                    1,
                    1,
                    600,
                    "sunday_maintenance_flow",
                ),
            )

    logger.info("Scheduler database schema initialized")
