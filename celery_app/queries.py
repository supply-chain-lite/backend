# Atomically claim the app-created ST_TaskRecords row for execution. Only the
# first worker to move TimeReceived off NULL wins (rowcount == 1). The API owns
# the Status column, so worker telemetry queries never write Status.
task_received_query = """UPDATE ST_TaskRecords SET TimeReceived = ?, Kwargs = ?
            WHERE TaskUID = ? AND TimeReceived IS NULL"""

get_task_status = """SELECT Status FROM ST_TaskRecords WHERE TaskUID = ?"""

task_started_query = """UPDATE ST_TaskRecords SET
                        TimeStarted = ?, ProcessId = ?, WorkerName = ?
                        WHERE TaskUID = ?"""

task_success_query = """UPDATE ST_TaskRecords SET TimeCompleted = ?,
                        Result = ? WHERE TaskUID = ?"""

task_cancelled_query = """UPDATE ST_TaskRecords SET TimeCompleted = ?
                        WHERE TaskUID = ?"""

task_failure_query = """UPDATE ST_TaskRecords SET TimeCompleted = ?,
                        Error = ?, Traceback = ? WHERE TaskUID = ?"""

get_program_details = """ SELECT WorkingDirectory, ProgramPath, ExecutionFilePath,
            ifnull(CommandLineParameters, '[]'), ifnull(FixedParameters, '{}')
            FROM SC_TaskResolution WHERE TemplateName = ? AND TaskName = ? """


update_child_process_id = """UPDATE ST_TaskRecords
                        SET JSONData = json_set(COALESCE(JSONData, '{}'), '$.ChildProcessId', ?)
                        WHERE TaskUID = ?;"""
