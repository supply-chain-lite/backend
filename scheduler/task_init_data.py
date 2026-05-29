"""Task initialization data for the scheduler.

All seed data is defined here as lists of lists and imported by database.py
during DB initialization.
"""

# Scheduled Jobs
# [JobName, JobDescription, TaskType, TaskParams, CronExpression, IsEnabled, MaxRetries, TimeoutSeconds]
scheduled_jobs = [
    [
        "celery_task_update",
        "Celery task update job running every minute",
        "celery_task_update",
        "{}",
        "* * * * *",
        1,
        3,
        300,
    ],
    [
        "cleanup_temp_files",
        "Temporary files cleanup and database vacuum job running every hour",
        "cleanup_temp_files",
        "{}",
        "0 * * * *",
        1,
        3,
        300,
    ],
]
