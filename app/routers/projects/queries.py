get_project_id = "SELECT ProjectId FROM S_Projects WHERE UserEmail=? AND ProjectName=?"

insert_new_project = " INSERT INTO S_Projects (UserEmail, ProjectName) VALUES (?, ?) RETURNING ProjectId"

get_current_project = "SELECT ProjectName FROM S_Projects WHERE UserEmail=? AND ProjectStatus='Active'"


set_project_status = """ UPDATE S_Projects SET ProjectStatus=NULL WHERE UserEmail=?;
                        UPDATE S_Projects SET ProjectStatus='Active' WHERE UserEmail=? AND ProjectName=? """

get_project_models = """SELECT S_UserModels.ModelName
                        FROM S_UserModels, S_Projects
                        WHERE S_UserModels.ProjectId = S_Projects.ProjectId
                        AND S_Projects.UserEmail = S_UserModels.UserEmail
                        AND S_Projects.UserEmail = ?
                        AND S_Projects.ProjectName = ?"""

delete_project = "DELETE FROM S_Projects WHERE UserEmail=? AND ProjectName=?"

rename_project = (
    "UPDATE S_Projects SET ProjectName = ?, UpdatedAt = CURRENT_TIMESTAMP WHERE UserEmail = ? AND ProjectName = ?"
)

list_user_projects = "SELECT ProjectName FROM S_Projects WHERE UserEmail=?"
