list_task_query = """SELECT TaskId, TaskDisplayName, ifnull(TaskParameters, '[]') as TaskParameters
                     FROM [S_TaskMaster]"""

get_current_running_tasks = """select count(*) from ST_TaskRecords
                                WHERE Status in ('RUNNING', 'PENDING', 'STARTED') COLLATE NOCASE
                                and   ModelID = ?"""

get_user_run_count = """SELECT  ifnull(json_extract(ifnull(JsonData, '{}'), '$.max_concurrent_runs'),
                        1) as max_runs FROM [S_Users] WHERE UserEmail = ? """

get_user_model_run_count = """select count(*)
                                from S_UserModels, ST_TaskRecords
                                WHERE S_UserModels.ModelId = ST_TaskRecords.ModelId
                                AND   ST_TaskRecords.Status in ('RUNNING', 'PENDING', 'STARTED') COLLATE NOCASE
                                AND   S_UserModels.UserEmail = ?"""

get_broker_url = "SELECT ParamValue FROM S_ModelParams WHERE ParamName = 'BROKER_URL' COLLATE NOCASE"

get_task_name = "SELECT TaskName FROM S_TaskMaster WHERE TaskId = ?"

insert_task_record = """INSERT INTO ST_TaskRecords (ModelId, TaskUID, TaskCode, TaskName, ModelName, ProjectName,
                        SubmittedBy, Status, TaskURL, JSONData)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        RETURNING TaskId"""

update_task_params = "UPDATE S_TaskMaster  SET TaskParameters = ? WHERE TaskId = ?"

get_task_params = "SELECT TaskName, TaskDisplayName, TaskParameters FROM S_TaskMaster WHERE TaskId = ?"

get_running_tasks = """select ST_TaskRecords.taskid, ST_TaskRecords.taskname, S_UserModels.modelname,
                        S_Projects.projectname, ST_TaskRecords.TaskUID, ST_TaskRecords.TaskURL, ST_TaskRecords.Status
                                from S_UserModels, ST_TaskRecords, S_Projects
                                WHERE S_UserModels.ModelId = ST_TaskRecords.ModelId
                                AND   S_UserModels.ProjectId = S_Projects.ProjectId
                                AND   S_UserModels.UserEmail= S_Projects.UserEmail
                                AND   ST_TaskRecords.Status in ('RUNNING', 'STARTED', 'PENDING') COLLATE NOCASE
                                AND   S_UserModels.UserEmail = ?"""

get_task_status = """select ST_TaskRecords.Status
                                from S_UserModels, ST_TaskRecords, S_Projects
                                WHERE S_UserModels.ModelId = ST_TaskRecords.ModelId
                                AND   S_UserModels.ProjectId = S_Projects.ProjectId
                                AND   S_UserModels.UserEmail= S_Projects.UserEmail
                                AND   ST_TaskRecords.TaskId = ?
                                AND   S_UserModels.UserEmail = ?"""

get_all_running_tasks = """select taskid,   TaskUID, TaskURL, Status from ST_TaskRecords
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

update_task_status = """UPDATE ST_TaskRecords SET Status = ?,
                        LastUpdated = datetime('now') WHERE TaskId = ?
                        AND Status = ?
                        RETURNING TaskName, ModelName, ProjectName, SubmittedBy,
                        (unixepoch(datetime('now')) - unixepoch(SubmittedAt))/60 as ExecutionMinutes"""

get_task_file = """select Status,
                            ifnull(json_extract(ifnull(ST_TaskRecords.JsonData, '{}'), '$.db'), '') as output_model_path,
                            S_Models.ModelId,
                            S_Models.ModelPath
                            from ST_TaskRecords, S_Models
                            WHERE ST_TaskRecords.ModelId = S_Models.ModelId
                            AND   ST_TaskRecords.TaskId = ?;"""


get_task_uid = """select TaskUID from ST_TaskRecords WHERE TaskId = ?;"""


get_task_uid_and_status = """select TaskUID, Status, TaskURL , json_extract(JSONData, '$.ChildProcessId')
                             from ST_TaskRecords
                              WHERE TaskId = ? AND SubmittedBy = ?;"""

update_user_revoked_flag = """UPDATE ST_TaskRecords
                        SET JSONData = json_set(COALESCE(JSONData, '{}'), '$.UserRevoked', 1)
                        WHERE TaskUID = ?;"""

get_user_revoked = """SELECT status, json_extract(COALESCE(JSONData, '{}'), '$.UserRevoked')
                      FROM ST_TaskRecords WHERE TaskUID = ?"""


insert_task_log = """INSERT INTO ST_TaskLogs (LogText, TaskId) VALUES (?, ?)"""

update_task_log = """UPDATE ST_TaskLogs SET LogText = ?, LastUpdated = datetime('now') WHERE TaskId = ?
                      RETURNING 1;"""

update_model_lock = """UPDATE S_Models
                        SET JSONData = json_set(COALESCE(JSONData, '{}'), '$.IsLocked', ?)
                        WHERE ModelId = ?;"""


get_task_details = """select ST_TaskRecords.TaskName, ST_TaskRecords.Status, ST_TaskRecords.SubmittedBy,
                        ST_TaskRecords.SubmittedAt, ST_TaskRecords.LastUpdated,
                        ST_TaskRecords.TaskUID, ST_TaskRecords.TaskURL, ST_TaskRecords.Result
                        from ST_TaskRecords
                        where ST_TaskRecords.taskid = ?
                        and ST_TaskRecords.modelid = ?"""

get_task_log = """SELECT LogText FROM ST_TaskLogs WHERE TaskId = ?;"""

delete_task_record = """DELETE FROM ST_TaskRecords WHERE TaskId = ?"""
