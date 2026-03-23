check_user_email = "SELECT 1 FROM S_Users WHERE UserEmail = ?"

create_user = """ INSERT INTO S_Users
                    (UserEmail, RoleId, DisplayName, PasswordHash, PasswordSalt, ActivationCode, IsActive, 
                    AccessTemplates) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""

get_template_names = """select distinct templatename from S_ModelTemplates"""