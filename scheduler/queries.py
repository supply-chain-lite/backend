get_jobs = """ SELECT JobId, JobName, TaskType, TaskParams, CronExpression,
                MaxRetries, TimeoutSeconds, LastRunAt, NextRunAt
                FROM SJ_ScheduledJobs WHERE IsEnabled = 1"""

update_job_run_time = """UPDATE SJ_ScheduledJobs SET LastRunAt = ?, NextRunAt = ?,
                         UpdatedAt = datetime('now') WHERE JobId = ?"""

insert_job_execution = """INSERT INTO SJ_JobExecutions
                        (JobId, JobName, Status, StartedAt, CompletedAt, DurationSeconds,
                        RetryCount, ErrorMessage, ResultData)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        RETURNING ExecutionId"""

update_job_execution = """UPDATE SJ_JobExecutions
                        SET Status = ?, CompletedAt = ?, DurationSeconds = ?,
                        ErrorMessage = ?, ResultData = ?
                        WHERE ExecutionId = ?"""

update_job_running_status = """UPDATE SJ_ScheduledJobs SET IsRunning = ?,
                               UpdatedAt = datetime('now')
                               WHERE JobId = ?
                               AND  IsRunning = ?
                               RETURNING 1"""
