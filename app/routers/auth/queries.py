check_user_email = "SELECT 1 FROM S_Users WHERE UserEmail = ?"

create_user = """ INSERT INTO S_Users
                    (UserEmail, RoleId, DisplayName, PasswordHash, PasswordSalt, ActivationCode, IsActive,
                    AccessTemplates) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""

add_default_project = """INSERT INTO S_Projects(UserEmail, ProjectName, ProjectStatus)
                        SELECT ?, 'Default', 'Active'
                        WHERE NOT EXISTS (SELECT 1 FROM S_Projects WHERE UserEmail = ? AND ProjectName = 'Default');"""

get_template_names = """select distinct templatename from S_ModelTemplates"""

get_status_activation_code = "SELECT IsActive, ActivationCode FROM S_Users WHERE UserEmail = ?"

update_user_activation = "UPDATE S_Users SET IsActive = 1 WHERE UserEmail = ?"

update_password_reset_code = "UPDATE S_Users SET ActivationCode = ? WHERE UserEmail = ?"

update_user_password = """UPDATE S_Users SET PasswordHash = ?, UpdatedAt = DATETIME('now'),
                            TokenVersion = TokenVersion + 1,
                            PasswordSalt = ? WHERE UserEmail = ?"""

get_user_password = """SELECT S_Users.PasswordHash, S_Users.PasswordSalt, S_Users.IsActive,
                    S_Users.FailedAttempts, S_Users.TokenVersion,
                    CASE WHEN IFNULL(S_Users.LockedUntil, DATETIME('now')) > DATETIME('now') THEN 1 ELSE 0 END AS Locked,
                        S_UserRoles.RoleName
                    FROM S_Users, S_UserRoles
                    WHERE S_Users.RoleId = S_UserRoles.RoleId AND S_Users.UserEmail = ?"""

lock_user_account = """UPDATE S_Users SET LockedUntil = datetime(DATETIME('now'), ?),
                       TokenVersion = ?, UpdatedAt = DATETIME('now'),
                       FailedAttempts = ? WHERE UserEmail = ?"""


get_user_details = """SELECT S_UserRoles.RoleName, DisplayName, TokenVersion, IsActive,
                        CASE WHEN IFNULL(S_Users.LockedUntil, DATETIME('now')) > DATETIME('now') THEN 1 ELSE 0 END AS Locked
                         FROM S_Users, S_UserRoles
                        WHERE S_Users.RoleId = S_UserRoles.RoleId AND S_Users.UserEmail = ? """


get_home_page_url = """select ifnull(json_extract(ifnull(S_UserRoles.JsonData,
                        '{}'), '$.homePage'), 'home-page.html') as home_url
                    from S_UserRoles
                    where roleName = ?"""

check_if_user_can_access_url = """select COUNT(*)
        from S_UserRoles,
        json_each(ifnull(json_extract(ifnull(S_UserRoles.JsonData, '{}'), '$.modules'), '[]')) as module_list,
        S_Modules
        WHERE S_UserRoles.RoleName = ?
        AND   S_Modules.ModuleName = module_list.value
        AND   INSTR(?, S_Modules.ModuleHomePage) BETWEEN 1 AND 2"""
