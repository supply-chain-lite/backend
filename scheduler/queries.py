get_jobs = """ SELECT sj.ScheduleId, t.TaskId, t.TaskName, t.TaskParams,
                sj.ScheduleType, sj.CronExpression, t.MaxRetries, t.TimeoutSeconds,
                sj.LastRunAt, sj.NextRunAt
                FROM SJ_ScheduledJobs sj
                JOIN SJ_TaskMaster t ON sj.TaskId = t.TaskId
                WHERE sj.IsEnabled = 1"""

disable_schedule = """UPDATE SJ_ScheduledJobs SET IsEnabled = 0,
                      UpdatedAt = datetime('now') WHERE ScheduleId = ?"""

update_schedule_run_time = """UPDATE SJ_ScheduledJobs SET LastRunAt = ?, NextRunAt = ?,
                              UpdatedAt = datetime('now') WHERE ScheduleId = ?"""

insert_job_execution = """INSERT INTO SJ_JobExecutions
                        (ScheduleId, TaskId, TaskName, Status, StartedAt, CompletedAt,
                        DurationSeconds, RetryCount, ErrorMessage, ResultData)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        RETURNING ExecutionId"""

update_job_execution = """UPDATE SJ_JobExecutions
                        SET Status = ?, CompletedAt = ?, DurationSeconds = ?,
                        ErrorMessage = ?, ResultData = ?
                        WHERE ExecutionId = ?"""

update_schedule_running_status = """UPDATE SJ_ScheduledJobs SET IsRunning = ?,
                                    UpdatedAt = datetime('now')
                                    WHERE ScheduleId = ?
                                    AND IsRunning = ?
                                    RETURNING 1"""
