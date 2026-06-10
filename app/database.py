import json

from .connection import master_connection
from .logging_config import get_logger

logger = get_logger(__name__)

create_user_table = """CREATE TABLE IF NOT EXISTS S_Users (
                            UserEmail TEXT PRIMARY KEY UNIQUE,
                            RoleId INTEGER NOT NULL,
                            DisplayName TEXT,
                            PasswordHash TEXT,
                            PasswordSalt BLOB,
                            TokenVersion INTEGER DEFAULT 0,
                            ActivationCode TEXT,
                            FailedAttempts INTEGER DEFAULT 0,
                            LockedUntil DATETIME DEFAULT NULL,
                            IsActive INTEGER DEFAULT 0,
                            AccessTemplates TEXT,
                            JsonData TEXT,
                            CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
                            UpdatedAt TEXT NOT NULL DEFAULT (datetime('now'))
                        )"""

create_user_role_table = """CREATE TABLE IF NOT EXISTS S_UserRoles (
                                    RoleId INTEGER PRIMARY KEY AUTOINCREMENT,
                                    RoleName TEXT NOT NULL UNIQUE,
                                    RoleDescription TEXT,
                                    JsonData TEXT,
                                    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
                                    UpdatedAt TEXT NOT NULL DEFAULT (datetime('now'))
                            )"""

insert_user_role = """INSERT INTO S_UserRoles (RoleID, RoleName, RoleDescription, JSONData)
                        SELECT ?, ?, ?, ?
                        WHERE NOT EXISTS (
                            SELECT 1 FROM S_UserRoles WHERE RoleName = ?
                        )"""

create_projects_table = """CREATE TABLE IF NOT EXISTS S_Projects (
                                    ProjectId INTEGER PRIMARY KEY,
                                    UserEmail TEXT NOT NULL,
                                    ProjectName TEXT NOT NULL,
                                    ProjectStatus TEXT,
                                    JsonData TEXT,
                                    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
                                    UpdatedAt TEXT NOT NULL DEFAULT (datetime('now')),
                                    UNIQUE (UserEmail, ProjectName)
                                )"""

create_task_history_table = """CREATE TABLE IF NOT EXISTS ST_TaskRecords (
                                        TaskId          INTEGER PRIMARY KEY AUTOINCREMENT,
                                        TaskUID         TEXT NOT NULL,
                                        ClientTaskId    INTEGER NOT NULL,
                                        TaskName        TEXT NOT NULL,
                                        ProjectName     TEXT NOT NULL,
                                        ModelName       TEXT NOT NULL,
                                        ModelId         INTEGER NOT NULL,
                                        SubmittedBy     TEXT NOT NULL,
                                        SubmittedAt     TEXT NOT NULL DEFAULT (datetime('now')),
                                        Status          TEXT NOT NULL,
                                        TaskURL         TEXT,
                                        JSONData        TEXT,
                                        LastUpdated     TEXT NOT NULL DEFAULT (datetime('now'))
                                    )"""

create_task_logs_table = """CREATE TABLE IF NOT EXISTS ST_TaskLogs (
                                        TaskId      INTEGER NOT NULL,
                                        LogText     TEXT NOT NULL,
                                        LastUpdated   TEXT NOT NULL DEFAULT (datetime('now'))
                                    )"""


create_user_models_table = """CREATE TABLE IF NOT EXISTS S_UserModels (
                                    ModelId     INTEGER,
                                    UserEmail      TEXT,
                                    ProjectId   INTEGER,
                                    AccessLevel TEXT    NOT NULL,
                                    ModelName TEXT      NOT NULL,
                                    JsonData TEXT,
                                    GrantedAt   TEXT    NOT NULL
                                                DEFAULT (datetime('now')),
                                    PRIMARY KEY (
                                        ModelId,
                                        UserEmail,
                                        ProjectId
                                    )
                                )"""
create_models_table = """CREATE TABLE IF NOT EXISTS S_Models (
                                ModelId     INTEGER PRIMARY KEY AUTOINCREMENT,
                                ModelUID    TEXT    NOT NULL
                                            UNIQUE,
                                ModelPath   TEXT,
                                TemplateName TEXT,
                                JsonData TEXT,
                                CreatedAt   TEXT    NOT NULL
                                            DEFAULT (datetime('now')),
                                OwnerEmail  TEXT
                            )"""

create_models_backup_table = """CREATE TABLE IF NOT EXISTS S_ModelBackups (
                                        BackupId   INTEGER PRIMARY KEY AUTOINCREMENT,
                                        BackupText TEXT NOT NULL,
                                        ModelId    INTEGER NOT NULL,
                                        BackupPath TEXT NOT NULL,
                                        JsonData TEXT,
                                        CreatedAt  TEXT NOT NULL DEFAULT (datetime('now')),
                                        LastUsedAt TEXT NOT NULL DEFAULT (datetime('now'))
                                    )"""

create_model_templates_table = """ CREATE TABLE IF NOT EXISTS S_ModelTemplates (
                                            TemplateName               TEXT PRIMARY KEY,
                                            TemplateSQL                TEXT NOT NULL,
                                            TemplateWithDataSQL        TEXT NOT NULL,
                                            JsonData TEXT,
                                            CreatedAt    TEXT NOT NULL DEFAULT (datetime('now'))
                                        )  """

insert_model_template = """INSERT INTO S_ModelTemplates (TemplateName, TemplateSQL, TemplateWithDataSQL)
                            SELECT ?, ?, ?
                            WHERE NOT EXISTS (
                                SELECT 1 FROM S_ModelTemplates WHERE TemplateName = ?
                            )"""

create_user_notifications_table = """CREATE TABLE IF NOT EXISTS S_UserNotifications (
                                            NotificationId INTEGER PRIMARY KEY AUTOINCREMENT,
                                            FromUserEmail TEXT NOT NULL,
                                            ToUserEmail TEXT NOT NULL,
                                            Title TEXT NOT NULL,
                                            Message TEXT NOT NULL,
                                            NotificationType TEXT,
                                            NotificationParams TEXT,
                                            IsRead INTEGER DEFAULT 0,
                                            JsonData TEXT,
                                            CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
                                            ReadAt TEXT DEFAULT NULL,
                                            IsAccepted INTEGER DEFAULT 0
                                        )"""

create_query_history_table = """CREATE TABLE IF NOT EXISTS S_SQLHistory (
                                    HistoryId INTEGER PRIMARY KEY AUTOINCREMENT,
                                    UserEmail TEXT NOT NULL,
                                    ModelId INTEGER NOT NULL,
                                    ModelName TEXT NOT NULL,
                                    ProjectName TEXT NOT NULL,
                                    SQLQuery TEXT NOT NULL,
                                    IsErrored INTEGER NOT NULL,
                                    Status TEXT NOT NULL,
                                    RowsAffected INTEGER,
                                    JSONData TEXT,
                                    CreatedAt TEXT NOT NULL DEFAULT (datetime('now'))
                                )"""

create_request_errors_table = """CREATE TABLE IF NOT EXISTS S_RequestErrors (
                                    ErrorId INTEGER PRIMARY KEY AUTOINCREMENT,
                                    RequestId TEXT NOT NULL,
                                    Method TEXT NOT NULL,
                                    UrlPath TEXT NOT NULL,
                                    ErrorType TEXT NOT NULL,
                                    ErrorDetail TEXT,
                                    ErrorCode INTEGER NOT NULL DEFAULT 500,
                                    JsonData TEXT,
                                    CreatedAt TEXT NOT NULL DEFAULT (datetime('now'))
                                )"""

create_modules_table = """CREATE TABLE IF NOT EXISTS S_Modules (
                            ModuleId INTEGER PRIMARY KEY AUTOINCREMENT,
                            ModuleName TEXT NOT NULL UNIQUE,
                            ModulePath TEXT,
                            ModuleDescription TEXT,
                            ModuleHomePage TEXT,
                            JsonData TEXT
                        )"""

insert_module = """INSERT INTO S_Modules (ModuleName, ModuleDescription, ModulePath, ModuleHomePage)
                    SELECT ?, ?, ?, ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM S_Modules WHERE ModuleName = ?
                    )"""

module_data = [
    ("Models", "Create and manage data models", "/api/models", "home-page.html"),
    ("Projects", "Organize models into projects and manage access", "/api/projects", "home-page.html"),
    ("SQLClient", "Run ad-hoc SQL queries against your data warehouse", "/api/sql-client", "sql-client.html"),
    ("Tables", "CRUD operations for tables", "/api/tables", "table.html"),
    ("Tasks", "Monitor and manage long-running tasks", "/api/tasks", "task-details.html"),
    ("Scheduler", "Schedule recurring tasks and manage schedules", "/api/schedules", "scheduler.html"),
]

admin_role = {"modules": [module[0] for module in module_data], "homePage": "home-page.html"}
user_role = {"modules": [module[0] for module in module_data if module[0] != "Scheduler"], "homePage": "home-page.html"}

user_roles = [
    (1, "Admin", "Administrator with full access", json.dumps(admin_role)),
    (2, "User", "Regular user with limited access", json.dumps(user_role)),
    (3, "PowerUser", "Power user with extended access", json.dumps(user_role)),
]

_MIGRATIONS = [
    ("ST_TaskRecords", "TaskURL", "TEXT"),
]


def migrate_db() -> None:
    """
    Apply schema migrations listed in _MIGRATIONS.

    For each (table, column, col_type) tuple, adds the specified column to the table if it does not already exist. The operation is idempotent: existing columns are skipped. Database errors from the underlying connection propagate to the caller.
    """
    logger.info("Running database migrations")
    with master_connection() as cursor:
        for table, column, col_type in _MIGRATIONS:
            rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
            existing_columns = {row[1] for row in rows}
            if column not in existing_columns:
                stmt = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                cursor.execute(stmt)
                logger.info("Migration applied: %s.%s", table, column)
            else:
                logger.debug("Column %s.%s already exists, skipping", table, column)
    logger.info("Database migrations finished")


def init_db() -> None:
    """
    Initialize the application's database schema and seed default user roles and model templates.

    Creates all required tables (users, roles, projects, errors, models, backups, templates, notifications) if they do not exist and inserts two user roles ("Admin", "User") and two model templates ("Generic Data Model", "Supply Planning") using guarded inserts to avoid duplicates. This function does not handle database errors; any exceptions from the underlying DB operations will propagate to the caller.
    """
    logger.info("Initializing database schema")
    with master_connection() as cursor:
        cursor.execute(create_user_table)
        cursor.execute(create_user_role_table)
        cursor.execute(create_projects_table)
        cursor.execute(create_user_models_table)
        cursor.execute(create_models_table)
        cursor.execute(create_models_backup_table)
        cursor.execute(create_model_templates_table)
        cursor.execute(
            insert_model_template,
            (
                "Generic Data Model",
                "generic_model.sql",
                "generic_model.sql",
                "Generic Data Model",
            ),
        )
        cursor.execute(
            insert_model_template,
            (
                "Supply Planning",
                "supply_planning.sql",
                "supply_planning_with_data.sql",
                "Supply Planning",
            ),
        )
        cursor.execute(create_user_notifications_table)
        cursor.execute(create_query_history_table)
        cursor.execute(create_task_history_table)
        cursor.execute(create_task_logs_table)
        cursor.execute(create_request_errors_table)
        cursor.execute(create_modules_table)
        for module_name, module_desc, module_path, module_home in module_data:
            cursor.execute(insert_module, (module_name, module_desc, module_path, module_home, module_name))
        for role_id, role_name, role_desc, json_data in user_roles:
            cursor.execute(insert_user_role, (role_id, role_name, role_desc, json_data, role_name))
    logger.info("Database schema initialization finished")
