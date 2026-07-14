task_received_query = """INSERT OR IGNORE INTO SC_TaskWorker (TaskId, TaskName, Args,
            Kwargs, Status, TimeReceived)
            VALUES (?, ?, ?, ?, 'RECEIVED', ?)"""

task_started_query = """UPDATE SC_TaskWorker SET Status = 'STARTED',
                        TimeStarted = ?, ProcessId = ?, WorkerName = ?
                        WHERE TaskId = ?"""

task_success_query = """UPDATE SC_TaskWorker SET Status = 'SUCCESS', TimeCompleted = ?,
                        Result = ? WHERE TaskId = ?"""

task_cancelled_query = """UPDATE SC_TaskWorker SET Status = 'CANCELLED', TimeCompleted = ?
                        WHERE TaskId = ?"""

task_failure_query = """UPDATE SC_TaskWorker SET Status = 'FAILED', TimeCompleted = ?,
                        Error = ?, Traceback = ? WHERE TaskId = ?"""

get_program_details = """ SELECT WorkingDirectory, ProgramPath, ExecutionFilePath,
            ifnull(CommandLineParameters, '[]'), ifnull(FixedParameters, '{}')
            FROM SC_TaskResolution WHERE TemplateName = ? AND TaskName = ? """
