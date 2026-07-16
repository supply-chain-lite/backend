task_received_query = """INSERT OR IGNORE INTO SC_TaskWorker (TaskUID, TaskName, Args,
            Kwargs, Status, TimeReceived)
            VALUES (?, ?, ?, ?, 'RECEIVED', ?)"""

task_started_query = """UPDATE SC_TaskWorker SET Status = 'STARTED',
                        TimeStarted = ?, ProcessId = ?, WorkerName = ?
                        WHERE TaskUID = ?"""

task_success_query = """UPDATE SC_TaskWorker SET Status = 'SUCCESS', TimeCompleted = ?,
                        Result = ? WHERE TaskUID = ?"""

task_cancelled_query = """UPDATE SC_TaskWorker SET Status = 'CANCELLED', TimeCompleted = ?
                        WHERE TaskUID = ?"""

task_failure_query = """UPDATE SC_TaskWorker SET Status = 'FAILED', TimeCompleted = ?,
                        Error = ?, Traceback = ? WHERE TaskUID = ?"""

get_program_details = """ SELECT WorkingDirectory, ProgramPath, ExecutionFilePath,
            ifnull(CommandLineParameters, '[]'), ifnull(FixedParameters, '{}')
            FROM SC_TaskResolution WHERE TemplateName = ? AND TaskName = ? """


update_child_process_id = """UPDATE SC_TaskWorker
                        SET JSONData = json_set(COALESCE(JSONData, '{}'), '$.ChildProcessId', ?)
                        WHERE TaskUID = ?;"""
