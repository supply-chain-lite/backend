"""Task initialization data for the scheduler.

All seed data is defined here as lists of lists and imported by database.py
during DB initialization.
"""

# Task Definitions
# [TaskName, TaskDescription, TaskParams, MaxRetries, TimeoutSeconds]
task_definitions = [
    ["celery_task_update", "Celery task update job", "{}", 3, 300],
    ["cleanup_temp_files", "Temporary files cleanup and database vacuum job", "{}", 3, 300],
]

# Task Schedules
# [TaskName, ScheduleType, CronExpression, IsEnabled]
# ScheduleType: "cron", "run_once", "run_at_startup"
task_schedules = [
    ["celery_task_update", "cron", "* * * * *", 1],
    ["cleanup_temp_files", "cron", "0 * * * *", 1],
]
