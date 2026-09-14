get_model_id_and_paths = """SELECT modelid, modelpath,
        json_extract(ifnull(JsonData, '{}'), '$.last_vacuum_date') as last_vacuum_date,
        ifnull(json_extract(ifnull(JsonData, '{}'), '$.db_type'), 'SQLITE') as db_type
        FROM S_Models
        WHERE ifnull(json_extract(ifnull(S_Models.JsonData, '{}'), '$.IsLocked'), 0) = 0;"""

update_vacuum_date = """UPDATE S_Models
        SET JsonData = json_set(COALESCE(JsonData, '{}'), '$.last_vacuum_date', ?)
        WHERE ModelId = ?"""

get_pending_tasks_older_than = """SELECT TaskId, TaskUID, TaskURL, ModelId
        FROM ST_TaskRecords
        WHERE Status = 'PENDING' COLLATE NOCASE
        AND (unixepoch(datetime('now')) - unixepoch(SubmittedAt)) > ?"""


get_stuck_locked_models = """SELECT S_Models.ModelId,
        (SELECT TaskId FROM ST_TaskRecords
         WHERE ST_TaskRecords.ModelId = S_Models.ModelId
         ORDER BY TaskId DESC LIMIT 1) AS LatestTaskId
        FROM S_Models
        WHERE ifnull(json_extract(ifnull(S_Models.JsonData, '{}'), '$.IsLocked'), 0) = 1
        AND NOT EXISTS (
            SELECT 1 FROM ST_TaskRecords
            WHERE ST_TaskRecords.ModelId = S_Models.ModelId
            AND Status IN ('RUNNING', 'STARTED', 'PENDING') COLLATE NOCASE
        )"""


update_task_log = """UPDATE ST_TaskLogs
                        SET LogText =  COALESCE(LogText, '') || char(10) || ?,
                         LastUpdated = datetime('now')
                        WHERE TaskId = ?"""

get_long_running_started_tasks = """SELECT TaskId, SubmittedBy,
        ifnull(json_extract(ifnull(JSONData, '{}'), '$.max_run_seconds'), ?) as max_run_seconds
        FROM ST_TaskRecords
        WHERE Status IN ('STARTED', 'RUNNING') COLLATE NOCASE
        AND (unixepoch(datetime('now')) - unixepoch(SubmittedAt)) >
            ifnull(json_extract(ifnull(JSONData, '{}'), '$.max_run_seconds'), ?)"""

delete_duplicate_queries = """DELETE FROM S_SQLHistory
                                WHERE HistoryId not in
                                (
                                SELECT Max(HistoryId)
                                FROM S_SQLHistory
                                GROUP BY SQLQuery, IsErrored, UserEmail, ModelId
                                ) RETURNING 1;"""

delete_execution_logs = """DELETE FROM SJ_JobExecutions
                        WHERE JulianDay(Datetime('now')) -  JulianDay(CompletedAt) > ?
                        RETURNING 1;"""

delete_sql_history = """DELETE FROM S_SQLHistory
                        WHERE HistoryId in
                        (
                        SELECT HistoryId
                        FROM
                        (
                        SELECT
                                HistoryId,
                                ROW_NUMBER() OVER (
                                        PARTITION BY UserEmail
                                        ORDER BY HistoryId DESC
                                ) AS rn
                                FROM S_SQLHistory
                        ) WHERE rn > ?
                        )
                        RETURNING 1;"""


delete_task_history = """DELETE FROM ST_TaskRecords
                        WHERE TaskId in
                        (
                        SELECT TaskId
                        FROM
                        (
                        SELECT
                                TaskId,
                                ROW_NUMBER() OVER (
                                        PARTITION BY SubmittedBy
                                        ORDER BY TaskId DESC
                                ) AS rn
                                FROM ST_TaskRecords
                        ) WHERE rn > ?
                        )
                        AND JulianDay(Datetime('now')) -  JulianDay(SubmittedAt) > ?
                        RETURNING 1;"""


delete_task_logs = """DELETE FROM ST_TaskLogs
                        WHERE TaskId NOT IN (SELECT TaskId FROM ST_TaskRecords)
                        RETURNING 1;"""


get_system_generated_backup = """SELECT BackupId, BackupPath
                                        FROM S_ModelBackups
                                        WHERE ModelId = ?
                                        AND BackupText = ?
                                        ORDER BY BackupId DESC
                                        LIMIT 1"""

insert_model_backup = """INSERT INTO S_ModelBackups (ModelId, BackupPath, BackupText)
                            VALUES (?, ?, ?)"""

delete_backup_by_id = "DELETE FROM S_ModelBackups WHERE BackupId = ?"
