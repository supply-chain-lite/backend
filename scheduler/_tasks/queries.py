get_model_id_and_paths = """SELECT modelid, modelpath,
        json_extract(ifnull(JsonData, '{}'), '$.last_vacuum_date') as last_vacuum_date
        FROM S_Models
        WHERE ifnull(json_extract(ifnull(S_Models.JsonData, '{}'), '$.is_running'), 0) = 0;"""

update_vacuum_date = """UPDATE S_Models
        SET JsonData = json_set(COALESCE(JsonData, '{}'), '$.last_vacuum_date', ?)
        WHERE ModelId = ?"""

get_pending_tasks_older_than = """SELECT TaskId, TaskUID, TaskURL, ModelId
        FROM ST_TaskRecords
        WHERE Status = 'PENDING' COLLATE NOCASE
        AND (unixepoch(datetime('now')) - unixepoch(SubmittedAt)) > ?"""


update_task_log = """UPDATE ST_TaskLogs
                        SET LogText =  COALESCE(LogText, '') || char(10) || ?,
                         LastUpdated = datetime('now')
                        WHERE TaskId = ?"""

get_long_running_started_tasks = """SELECT TaskId, TaskUID, TaskURL, ModelId,
        ifnull(json_extract(ifnull(JSONData, '{}'), '$.max_run_seconds'), 86400) as max_run_seconds
        FROM ST_TaskRecords
        WHERE Status IN ('STARTED', 'RUNNING') COLLATE NOCASE
        AND (unixepoch(datetime('now')) - unixepoch(SubmittedAt)) >
            ifnull(json_extract(ifnull(JSONData, '{}'), '$.max_run_seconds'), 86400)"""
