"""
Celery database schema definitions.

This module defines the Celery task-resolution table:
- SC_TaskResolution: Task definitions (how to run each task)

Per-task lifecycle and telemetry are recorded on the app's ST_TaskRecords table
(see app.database); the worker updates that row rather than a separate table.
"""

from app.connection import master_connection
from app.logging_config import get_logger

logger = get_logger(__name__)

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
        cursor.execute(create_task_resolutions_table)

        # Support existing databases that were created before the added column.
        cursor.execute("PRAGMA table_info(SC_TaskResolution)")
        columns = {row[1] for row in cursor.fetchall()}
        if "FixedParameters" not in columns:
            cursor.execute("ALTER TABLE SC_TaskResolution ADD COLUMN FixedParameters TEXT")
    logger.info("Celery database schema initialized")
