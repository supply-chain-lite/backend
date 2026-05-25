list_task_query = """SELECT TaskId, TaskDisplayName, ifnull(TaskParameters, '[]') as TaskParameters
                     FROM [S_TaskMaster]"""

get_current_running_tasks = """select count(*) from S_TaskRecords
                                WHERE Status in ('RUNNING', 'PENDING', 'STARTED') COLLATE NOCASE
                                and   ModelID = ?"""

get_user_run_count = """SELECT  ifnull(json_extract(ifnull(JsonData, '{}'), '$.max_concurrent_runs'),
                        1) as max_runs FROM [S_Users] WHERE UserEmail = ? """

get_user_model_run_count = """select count(*)
                                from S_UserModels, S_TaskRecords
                                WHERE S_UserModels.ModelId = S_TaskRecords.ModelId
                                AND   S_TaskRecords.Status in ('RUNNING', 'PENDING', 'STARTED') COLLATE NOCASE
                                AND   S_UserModels.UserEmail = ?"""

get_broker_url = "SELECT ParamValue FROM S_ModelParams WHERE ParamName = 'BROKER_URL' COLLATE NOCASE"

get_task_name = "SELECT TaskName FROM S_TaskMaster WHERE TaskId = ?"

insert_task_record = """INSERT INTO S_TaskRecords (ModelId, TaskUID, ClientTaskId, TaskName, ModelName, ProjectName,
                        SubmittedBy, Status, TaskURL, JSONData)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

update_task_params = "UPDATE S_TaskMaster  SET TaskParameters = ? WHERE TaskId = ?"

get_task_params = "SELECT TaskName, TaskDisplayName, TaskParameters FROM S_TaskMaster WHERE TaskId = ?"

get_running_tasks = """select S_TaskRecords.taskid, S_TaskRecords.taskname, S_UserModels.modelname,
                        S_Projects.projectname, S_TaskRecords.TaskUID, S_TaskRecords.TaskURL, S_TaskRecords.Status
                                from S_UserModels, S_TaskRecords, S_Projects
                                WHERE S_UserModels.ModelId = S_TaskRecords.ModelId
                                AND   S_UserModels.ProjectId = S_Projects.ProjectId
                                AND   S_UserModels.UserEmail= S_Projects.UserEmail
                                AND   S_TaskRecords.Status in ('RUNNING', 'STARTED', 'PENDING') COLLATE NOCASE
                                AND   S_UserModels.UserEmail = ?"""

get_task_status = """select S_TaskRecords.Status
                                from S_UserModels, S_TaskRecords, S_Projects
                                WHERE S_UserModels.ModelId = S_TaskRecords.ModelId
                                AND   S_UserModels.ProjectId = S_Projects.ProjectId
                                AND   S_UserModels.UserEmail= S_Projects.UserEmail
                                AND   S_TaskRecords.TaskId = ?
                                AND   S_UserModels.UserEmail = ?"""

get_all_running_tasks = """select taskid,   TaskUID, TaskURL, Status from S_TaskRecords
                           WHERE Status in ('RUNNING', 'STARTED', 'PENDING') COLLATE NOCASE"""

insert_task_notifications = """INSERT INTO S_UserNotifications (
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

update_task_status = """UPDATE S_TaskRecords SET Status = ?,
                        LastUpdated = datetime('now') WHERE TaskId = ?
                        AND Status = ?
                        RETURNING TaskName, ModelName, ProjectName, SubmittedBy,
                        (unixepoch(datetime('now')) - unixepoch(SubmittedAt))/60 as ExecutionMinutes"""

get_task_file = """select Status,
                            ifnull(json_extract(ifnull(S_TaskRecords.JsonData, '{}'), '$.file_url'), '') as output_model_path,
                            S_Models.ModelId,
                            S_Models.ModelPath
                            from S_TaskRecords, S_Models
                            WHERE S_TaskRecords.ModelId = S_Models.ModelId
                            AND   S_TaskRecords.TaskId = ?;"""


get_task_uid = """select TaskUID from S_TaskRecords WHERE TaskId = ?;"""


insert_task_log = """INSERT INTO S_TaskLogs (LogText, TaskId) VALUES (?, ?)"""

update_task_log = """UPDATE S_TaskLogs SET LogText = ?, LastUpdated = datetime('now') WHERE TaskId = ?
                      RETURNING 1;"""

update_model_lock = """UPDATE S_Models
                        SET JSONData = json_set(COALESCE(JSONData, '{}'), '$.IsLocked', ?)
                        WHERE ModelId = ?;"""