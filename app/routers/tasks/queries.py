list_task_query = """SELECT TaskId, TaskDisplayName, ifnull(TaskParameters, '[]') as TaskParameters
                     FROM [S_TaskMaster]"""

get_current_running_tasks = """select count(*) from S_TaskRecords
                                WHERE Status in ('RUNNING', 'PENDING') COLLATE NOCASE
                                and   ModelID = ?"""

get_user_run_count = """SELECT  ifnull(json_extract(ifnull(JsonData, '{}'), '$.max_concurrent_runs'),
                        1) as max_runs FROM [S_Users] WHERE UserEmail = ? """

get_user_model_run_count = """select count(*)
                                from S_UserModels, S_TaskRecords
                                WHERE S_UserModels.ModelId = S_TaskRecords.ModelId
                                AND   S_TaskRecords.Status in ('RUNNING', 'PENDING') COLLATE NOCASE
                                AND   S_UserModels.UserEmail = ?"""

get_broker_url = "SELECT ParamValue FROM S_ModelParams WHERE ParamName = 'BROKER_URL' COLLATE NOCASE"

get_task_name = "SELECT TaskName FROM S_TaskMaster WHERE TaskId = ?"

insert_task_record = """INSERT INTO S_TaskRecords (ModelId, TaskId, TaskName, ModelName, ProjectName,
                        SubmittedBy, Status, JSONData)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""

update_task_params = "UPDATE S_TaskMaster  SET TaskParameters = ? WHERE TaskId = ?"

get_task_params = "SELECT TaskName, TaskParameters FROM S_TaskMaster WHERE TaskId = ?"
