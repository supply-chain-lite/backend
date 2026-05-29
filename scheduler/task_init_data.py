"""Task initialization data for the scheduler.

All seed data is defined here as lists of lists and imported by database.py
during DB initialization.
"""

# Task Definitions
# [TaskName, TaskDescription, TaskParams, MaxRetries, TimeoutSeconds]
task_definitions = [
    ["celery_task_update", "Celery task update job", "{}", 3, 300],
    ["cleanup_temp_files", "Temporary files cleanup and database vacuum job", "{}", 3, 300],
    ["revoke_stale_tasks", "Revoke tasks stuck in PENDING state for more than an hour", "{}", 3, 300],
    ["cancel_long_running_tasks", "Cancel tasks in STARTED state exceeding max run time", "{}", 3, 300],
]

# Task Schedules
# [TaskName, ScheduleType, CronExpression, IsEnabled]
# ScheduleType: "cron", "run_once", "run_at_startup"
task_schedules = [
    ["celery_task_update", "cron", "* * * * *", 1],
    ["cleanup_temp_files", "cron", "0 * * * *", 1],
    ["revoke_stale_tasks", "cron", "*/5 * * * *", 1],
    ["cancel_long_running_tasks", "cron", "*/5 * * * *", 1],
]
