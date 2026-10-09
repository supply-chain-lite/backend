list_users = """select S_Users.UserEmail, S_Users.DisplayName,
                S_Users.IsActive, S_Users.AccessTemplates,
                S_UserRoles.RoleName, S_Users.JsonData, S_Users.CreatedAt
                from S_Users, S_UserRoles
                WHERE S_Users.RoleId = S_UserRoles.RoleId"""


list_templates = "select distinct TemplateName from S_ModelTemplates"


list_modules = "select distinct ModuleName, ModuleHomePage from S_Modules"


list_roles = "select RoleId, RoleName, RoleDescription, CreatedAt, JSONData  from S_UserRoles"


add_new_user = """INSERT INTO S_Users (UserEmail, DisplayName, IsActive, AccessTemplates, RoleId,
                JsonData, CreatedAt)
                SELECT ?, ?, 1, ?, RoleId, ?, CURRENT_TIMESTAMP
                FROM S_UserRoles
                WHERE RoleName = ?
                AND NOT EXISTS (SELECT 1 FROM S_Users WHERE UserEmail = ?)
                RETURNING 1"""

add_new_role = """INSERT INTO S_UserRoles (RoleName, RoleDescription, CreatedAt, JSONData)
                SELECT ?, ?, CURRENT_TIMESTAMP, ?
                WHERE NOT EXISTS (SELECT 1 FROM S_UserRoles WHERE RoleName = ?)
                RETURNING RoleId"""

update_role = """UPDATE S_UserRoles
                SET RoleName = COALESCE(?, RoleName),
                    RoleDescription = COALESCE(?, RoleDescription),
                    JsonData = CASE WHEN ? IS NULL THEN JsonData
                                ELSE json_patch(COALESCE(JsonData, '{}'), ?)
                               END,
                    UpdatedAt = CURRENT_TIMESTAMP
                WHERE RoleId = ?
                RETURNING 1"""

update_user = """UPDATE S_Users
                SET DisplayName = COALESCE(?, DisplayName),
                    IsActive = COALESCE(?, IsActive),
                    AccessTemplates = COALESCE(?, AccessTemplates),
                    RoleId = COALESCE(?, RoleId),
                    JsonData = json_patch( COALESCE(JsonData, '{}'), ?)
                WHERE UserEmail = ?
                RETURNING 1"""

get_role_id = "select RoleId from S_UserRoles where RoleName = ?"


get_access_level = """SELECT lower(S_UserModels.AccessLevel) as AccessLevel
                        FROM S_UserModels
                        WHERE S_UserModels.ModelId = ? AND S_UserModels.UserEmail = ? """

get_shared_models = """select S_UserModels.ModelId, S_UserModels.AccessLevel
                        from S_Models, S_UserModels
                        where S_Models.ModelId = S_UserModels.ModelId
                        and  S_Models.OwnerEmail != S_UserModels.UserEmail
                        and  S_Models.OwnerEmail = ?
                        and  S_UserModels.UserEmail = ?
                        """

delete_shared_model = """DELETE FROM S_UserModels
                        WHERE ModelId = ?
                        AND UserEmail = ?"""
