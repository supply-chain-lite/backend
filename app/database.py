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
                            CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
                            UpdatedAt TEXT NOT NULL DEFAULT (datetime('now'))
                        )"""

create_user_role_table = """CREATE TABLE IF NOT EXISTS S_UserRoles (
                                    RoleId INTEGER PRIMARY KEY AUTOINCREMENT,
                                    RoleName TEXT NOT NULL UNIQUE,
                                    RoleDescription TEXT,
                                    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
                                    UpdatedAt TEXT NOT NULL DEFAULT (datetime('now'))
                            )"""

insert_user_role = """INSERT INTO S_UserRoles (RoleID, RoleName, RoleDescription)
                        SELECT ?, ?, ?
                        WHERE NOT EXISTS (
                            SELECT 1 FROM S_UserRoles WHERE RoleName = ?
                        )"""

create_projects_table = """CREATE TABLE IF NOT EXISTS S_Projects (
                                    ProjectId INTEGER PRIMARY KEY,
                                    UserEmail TEXT NOT NULL,
                                    ProjectName TEXT NOT NULL,
                                    ProjectStatus TEXT,
                                    CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
                                    UpdatedAt TEXT NOT NULL DEFAULT (datetime('now')),
                                    UNIQUE (UserEmail, ProjectName)
                                )"""

create_user_error_table = """CREATE TABLE IF NOT EXISTS S_UserErrors (
                                    MethodName TEXT NOT NULL,
                                    UserEmail TEXT,
                                    RequestBody TEXT,
                                    ErrorType TEXT,
                                    ErrorCode INTEGER NOT NULL,
                                    ErrorDetail TEXT
                                )"""
create_user_models_table = """CREATE TABLE IF NOT EXISTS S_UserModels (
                                    ModelId     INTEGER,
                                    UserEmail      TEXT,
                                    ProjectId   INTEGER,
                                    AccessLevel TEXT    NOT NULL,
                                    ModelName TEXT      NOT NULL,
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
                                CreatedAt   TEXT    NOT NULL
                                            DEFAULT (datetime('now')),
                                OwnerEmail  TEXT
                            )"""

create_models_backup_table = """CREATE TABLE IF NOT EXISTS S_ModelBackups (
                                        BackupId   INTEGER PRIMARY KEY AUTOINCREMENT,
                                        BackupText TEXT NOT NULL,
                                        ModelId    INTEGER NOT NULL,
                                        BackupPath TEXT NOT NULL,
                                        CreatedAt  TEXT NOT NULL DEFAULT (datetime('now')),
                                        LastUsedAt TEXT NOT NULL DEFAULT (datetime('now'))
                                    )"""

create_model_templates_table = """ CREATE TABLE IF NOT EXISTS S_ModelTemplates (
                                            TemplateName               TEXT PRIMARY KEY,
                                            TemplateSQL                TEXT NOT NULL,
                                            TemplateWithDataSQL        TEXT NOT NULL,
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
                                            CreatedAt TEXT NOT NULL DEFAULT (datetime('now')),
                                            ReadAt TEXT DEFAULT NULL,
                                            IsAccepted INTEGER DEFAULT 0
                                        )"""


def init_db() -> None:
    """
    Initialize the application's database schema and seed default user roles and model templates.
    
    Creates all required tables (users, roles, projects, errors, models, backups, templates, notifications) if they do not exist and inserts two user roles ("Admin", "User") and two model templates ("Generic Data Model", "Supply Planning") using guarded inserts to avoid duplicates. This function does not handle database errors; any exceptions from the underlying DB operations will propagate to the caller.
    """
    logger.info("Initializing database schema")
    with master_connection() as cursor:
        cursor.execute(create_user_table)
        cursor.execute(create_user_role_table)
        cursor.execute(insert_user_role, (1, "Admin", "Administrator with full access", "Admin"))
        cursor.execute(insert_user_role, (2, "User", "Regular user with limited access", "User"))
        cursor.execute(create_projects_table)
        cursor.execute(create_user_error_table)
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
    logger.info("Database schema initialization finished")
