check_user_email = "SELECT 1 FROM S_Users WHERE UserEmail = ?"

create_user = """ INSERT INTO S_Users
                    (UserEmail, RoleId, DisplayName, PasswordHash, PasswordSalt, ActivationCode, IsActive,
                    AccessTemplates) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""

get_template_names = """select distinct templatename from S_ModelTemplates"""

get_status_activation_code = "SELECT IsActive, ActivationCode FROM S_Users WHERE UserEmail = ?"

update_user_activation = "UPDATE S_Users SET IsActive = 1 WHERE UserEmail = ?"

update_password_reset_code = "UPDATE S_Users SET ActivationCode = ? WHERE UserEmail = ?"

update_user_password = """UPDATE S_Users SET PasswordHash = ?, UpdatedAt = DATETIME('now'),
                            PasswordSalt = ? WHERE UserEmail = ?"""

get_user_password = """SELECT PasswordHash, PasswordSalt, IsActive, FailedAttempts, TokenVersion,
                    CASE WHEN IFNULL(LockedUntil, DATETIME('now')) > DATETIME('now') THEN 1 ELSE 0 END AS Locked
                    FROM S_Users WHERE UserEmail = ?"""

lock_user_account = """UPDATE S_Users SET LockedUntil = datetime(DATETIME('now'), ?),
                       TokenVersion = ?, UpdatedAt = DATETIME('now'),
                       FailedAttempts = ? WHERE UserEmail = ?"""


get_user_details = """SELECT S_UserRoles.RoleName, DisplayName, TokenVersion, IsActive,
                        CASE WHEN IFNULL(LockedUntil, DATETIME('now')) > DATETIME('now') THEN 1 ELSE 0 END AS Locked
                         FROM S_Users, S_UserRoles
                        WHERE S_Users.RoleId = S_UserRoles.RoleId AND UserEmail = ? """
