get_project_id = "SELECT ProjectId FROM S_Projects WHERE UserEmail=? AND ProjectName=?"

get_model_id_and_path = """SELECT S_Models.ModelId, S_Models.ModelPath
                            FROM S_UserModels, S_Projects, S_Models
                            WHERE S_UserModels.ProjectId = S_Projects.ProjectId
                                AND S_UserModels.ModelId  = S_Models.ModelId
                                AND S_Projects.UserEmail  = S_UserModels.UserEmail
                                AND S_Projects.ProjectName = ?
                                AND S_UserModels.ModelName = ?
                                AND S_UserModels.UserEmail    = ?"""

insert_models = """INSERT INTO S_Models (
                    ModelUID, ModelPath, OwnerEmail, TemplateName)
                    VALUES (?, ?, ?, ?)
                    RETURNING ModelId"""

insert_user_models = """INSERT INTO S_UserModels (
            ModelId, UserEmail, ProjectId, AccessLevel, ModelName)
            VALUES (?, ?, ?, ?, ?)"""

update_user_model_project = """UPDATE S_UserModels
                                SET ProjectId = ?
                                WHERE ModelId = ?
                                AND UserEmail = ?
                                AND ProjectId = ?
                                RETURNING ModelId
                            """

get_model_templates = """SELECT DISTINCT S_ModelTemplates.TemplateName
                            FROM S_Users,
                                json_each(S_Users.AccessTemplates) AS AT,
                                S_ModelTemplates
                            WHERE S_Users.UserEmail = ?
                            AND   S_ModelTemplates.TemplateName = AT.value"""


get_template_sql_file = "SELECT {column_name} FROM S_ModelTemplates WHERE TemplateName = ?"

get_user_models_by_project = """SELECT  S_Projects.ProjectName, S_UserModels.ModelName, S_UserModels.AccessLevel
                            FROM S_Projects
                            LEFT JOIN S_UserModels
                            ON  S_Projects.ProjectId = S_UserModels.ProjectId
                            AND S_Projects.UserEmail = S_UserModels.UserEmail
                            WHERE S_Projects.UserEmail = ?"""

get_template_name = "SELECT TemplateName FROM S_Models WHERE ModelId = ?"

rename_model = "UPDATE S_UserModels SET ModelName = ? WHERE ModelId = ? AND UserEmail = ?"

get_access_level = "SELECT lower(AccessLevel) FROM S_UserModels WHERE ModelId = ? AND UserEmail = ?"

delete_user_model = "DELETE FROM S_UserModels WHERE ModelId = ? AND UserEmail = ? "

delete_model_for_all_users = """DELETE FROM S_UserModels WHERE ModelId = ?;
                                DELETE FROM S_Models WHERE ModelId = ?"""
get_model_backups = "select BackupPath from S_ModelBackups WHERE ModelId = ? order by BackupId"

delete_model_backup = "DELETE FROM S_ModelBackups WHERE ModelId = ? OR BackupPath = ?"

get_model_backup_details = """SELECT BackupId, BackupText, CreatedAt
                                FROM S_ModelBackups
                                WHERE ModelId = ?
                                ORDER BY BackupId DESC"""

get_model_backup_path = "SELECT BackupPath FROM S_ModelBackups WHERE BackupId = ? AND ModelId = ?"

add_user_notifications = """INSERT INTO S_UserNotifications (
                                        FromUserEmail,
                                        ToUserEmail,
                                        Title,
                                        Message,
                                        NotificationType,
                                        NotificationParams,
                                        IsRead,
                                        IsAccepted
                                    )
                                    VALUES (?, ?, ?, ?, ?, ?, 0,0)
                                    RETURNING NotificationId"""

read_notification = (
    "UPDATE S_UserNotifications SET IsRead = 1, ReadAt = CURRENT_TIMESTAMP WHERE NotificationId = ? AND ToUserEmail = ?"
)

accept_notification = """UPDATE S_UserNotifications SET IsAccepted = ?, IsRead = 1, ReadAt = CURRENT_TIMESTAMP
                        WHERE NotificationId = ? AND ToUserEmail = ?"""

get_notification_params = """SELECT FromUserEmail, NotificationParams FROM S_UserNotifications
                                    WHERE NotificationId = ? AND ToUserEmail = ?"""

get_user_notifications = """SELECT NotificationId, FromUserEmail, Title, Message, NotificationType, NotificationParams,
                                    IsRead, IsAccepted
                            FROM S_UserNotifications
                            WHERE ToUserEmail = ?
                            AND   (CreatedAt > datetime('now', '-7 days') OR IsAccepted = 0)
                            -- keep notifications for 7 days or until accepted/rejected"""


get_model_info = """select OwnerEmail, TemplateName from S_Models
                        where ModelId = ?"""

get_users_for_model = """SELECT S_UserModels.UserEmail, S_UserModels.AccessLevel
                        FROM S_UserModels
                        WHERE S_UserModels.ModelId = ?
                        AND S_UserModels.UserEmail != ?"""  # exclude owner

update_user_access_level = """UPDATE S_UserModels
                                SET AccessLevel = ?
                                WHERE ModelId = ?
                                AND UserEmail = ?"""
fetch_all_user_emails = " SELECT UserEmail FROM S_Users WHERE UserEmail != ?"
