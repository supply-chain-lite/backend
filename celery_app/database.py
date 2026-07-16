"""
Celery database schema definitions.

This module defines the tables for the Celery system:
- SC_TaskWorker: Task definitions (what to run)
- SJ_ScheduledJobs: Schedules for tasks (when to run)
- SJ_JobExecutions: Execution history and logs
"""

from app.connection import master_connection
from app.logging_config import get_logger

logger = get_logger(__name__)

create_task_worker_table = """CREATE TABLE IF NOT EXISTS SC_TaskWorker (
                TaskId          INTEGER PRIMARY KEY AUTOINCREMENT,
                TaskUID         TEXT UNIQUE NOT NULL,
                WorkerName      TEXT,
                ProcessId       INTEGER,
                TaskName        TEXT NOT NULL,
                Args            TEXT,           -- JSON-serialised positional args
                Kwargs          TEXT,           -- JSON-serialised keyword args
                Status          TEXT NOT NULL DEFAULT 'PENDING',
                TimeReceived    TEXT,
                TimeStarted     TEXT,
                TimeCompleted   TEXT,
                Result          TEXT,
                Error           TEXT,
                Traceback       TEXT,
                JSONData        TEXT,           -- Optional JSON-serialised
                EntryDatetime   TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(TaskUID)
            )"""


create_task_resolutions_table = """CREATE TABLE IF NOT EXISTS SC_TaskResolution (
                                        TemplateName TEXT NOT NULL,
                                        TaskName     TEXT NOT NULL,
                                        CeleryTaskName TEXT NOT NULL,
                                        CommandLineParameters TEXT,
                                        FixedParameters TEXT,
                                        WorkingDirectory TEXT,
                                        ProgramPath      TEXT,
                                        ExecutionFilePath TEXT,
                                        JSONData TEXT
                                    )"""


def init_celery_db() -> None:
    """
    Initialize Celery database tables.
    """
    logger.info("Initializing Celery database schema")
    with master_connection() as cursor:
        cursor.execute(create_task_worker_table)
        cursor.execute(create_task_resolutions_table)

        # Support existing databases that were created before the added column.
        cursor.execute("PRAGMA table_info(SC_TaskResolution)")
        columns = {row[1] for row in cursor.fetchall()}
        if "FixedParameters" not in columns:
            cursor.execute("ALTER TABLE SC_TaskResolution ADD COLUMN FixedParameters TEXT")
    logger.info("Celery database schema initialized")
