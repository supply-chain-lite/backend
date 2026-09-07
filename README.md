# Supply Chain Lite — Backend v2

A lightweight FastAPI backend using raw SQLite (no ORM), built with UV for packaging and Ruff for linting.

## Tech Stack

- **Python 3.13** + **FastAPI**
- **SQLite** (stdlib `sqlite3`, no ORM)
- **UV** — package manager
- **Ruff** — linter & formatter
- **pydantic-settings** — `.env` configuration

## Project Structure

```
app/
├── main.py             # FastAPI app entry point & router wiring
├── config.py           # Settings loaded from .env
├── connection.py       # SQLite connection helpers
├── database.py         # SQLite database initialization & migrations
├── logging_config.py   # Shared logging setup
└── routers/
    ├── auth/           # Authentication, activation & password management
    ├── models/         # Model CRUD, sharing, backups, files & templates
    ├── notifications/  # Incoming notifications and share requests
    ├── projects/       # Project lifecycle management
    ├── scheduler/      # Scheduler API for cron schedules & executions
    ├── sql_client/     # SQL client for tables, views, queries & history
    ├── tables/         # Table data, schema, import/export operations
    ├── tasks/          # Model task execution & monitoring
    └── user_management/# Reserved router for future user management

celery_app/             # Celery worker, tasks & database helpers
scheduler/              # Standalone async cron scheduler (see below)
```

## Getting Started

### Prerequisites

- Python 3.13+
- [UV](https://docs.astral.sh/uv/) (`pip install uv`)

### Setup

```bash
# Clone the repo and cd into it
git clone <repo-url>
cd backend_v2

# Install dependencies
uv sync

# Create your .env file
cp .env.example .env
# Edit .env and set a strong SECRET_KEY
```

### Run the Dev Server

```bash
uv run uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`. Interactive docs at `http://127.0.0.1:8000/docs`.

Logs are written to the console and, by default, to `./data/logs/app.log` with log rotation enabled.

### Celery Worker

Run the worker from the project root:

```bash
uv run celery -A celery_app worker --loglevel=info --pool=solo
```

On Windows, add `--pool=solo` for local development. Worker activity is logged to the console and `LOG_FOLDER/celery.log` via the shared logging config. Sample tasks live in `celery_app/tasks.py`, and the pre-run / post-run hooks are registered in `celery_app/celery.py`.

Each task execution writes its logs to `CELERY_LOG_FOLDER/<task_uid>.log`.

### Scheduler App

The `scheduler/` directory contains a lightweight, standalone async cron scheduler. It polls the database for enabled jobs, evaluates cron expressions, and executes due jobs concurrently. It runs outside the main FastAPI process so long-running tasks do not block the API.

#### Run the Scheduler

```bash
uv run python -m scheduler.runner
# Optional custom interval:
uv run python -m scheduler.runner 30
```

The default poll interval is 60 seconds. Logs are written to `LOG_FOLDER/scheduler.log`.

#### Scheduler Database Tables

| Table | Purpose |
|---|---|
| `SJ_TaskMaster` | Task definitions (name, description, retries, timeout) |
| `SJ_ScheduledJobs` | Per-task schedules, cron expression, enabled flag, last/next run times |
| `SJ_JobExecutions` | Execution history with status, duration, result data, and errors |

#### Built-in Scheduled Tasks

These tasks are seeded on startup in `scheduler/task_init_data.py`:

| Task | Schedule | Description |
|---|---|---|
| `celery_task_update` | Every minute | Refresh Celery task statuses |
| `cleanup_temp_files` | Every hour | Clean temp files and vacuum databases |
| `revoke_stale_tasks` | Every 5 minutes | Revoke tasks stuck in `PENDING` for more than an hour |
| `cancel_long_running_tasks` | Every 5 minutes | Cancel tasks in `STARTED` that exceed the max run time |

#### Scheduler Behavior

- Jobs are dispatched concurrently via `asyncio.gather`; a slow or retrying job does not block other jobs.
- Failed jobs retry with non-blocking exponential backoff (`2^retry_count` seconds) up to the task's `MaxRetries`.
- The scheduler uses the stored `NextRunAt` time as the primary trigger so jobs that became due while the scheduler was offline run immediately on restart.
- The scheduler, API, and Celery all share the same SQLite master database.

### Linting & Formatting

```bash
# Check for lint errors
uv run ruff check

# Auto-format code
uv run ruff format
```

## API Endpoints

All routes accept **POST** only and are prefixed with `/api`. Static files are served from `/`.

### Auth (`/api/auth`)

| Route | Description |
|---|---|
| `POST /api/auth/register` | Register a new user account |
| `POST /api/auth/activate` | Activate account using activation code |
| `POST /api/auth/forgot-password` | Initiate password-reset flow |
| `POST /api/auth/reset-password` | Reset password with verification code |
| `POST /api/auth/login` | Login and set access-token cookie |
| `POST /api/auth/logout` | Logout and clear access-token cookie |
| `POST /api/auth/me` | Get current user profile, role, and page access |
| `POST /api/auth/change-password` | Change password (authenticated) |
| `POST /api/auth/modules` | List modules accessible to the user's role |

### Models (`/api/models`)

| Route | Description |
|---|---|
| `POST /api/models/list` | List all models grouped by project |
| `POST /api/models/templates` | List available model templates |
| `POST /api/models/create` | Create a new model |
| `POST /api/models/save-as` | Save a copy of an existing model |
| `POST /api/models/rename` | Rename a model |
| `POST /api/models/delete` | Delete a model |
| `POST /api/models/move` | Move a model to another project |
| `POST /api/models/add-existing` | Attach existing models into a project |
| `POST /api/models/download` | Download a model artifact file |
| `POST /api/models/upload` | Upload a model artifact (multipart form) |
| `POST /api/models/backup` | Create a backup snapshot |
| `POST /api/models/get-backups` | List backup snapshots for a model |
| `POST /api/models/restore` | Restore a model from a backup |
| `POST /api/models/share` | Share a model with another user |
| `POST /api/models/table-groups` | Get table groups for a model |
| `POST /api/models/vacuum` | Optimize a model's database |
| `POST /api/models/info` | Get model metadata and access details |
| `POST /api/models/update-access` | Update access levels for shared users |
| `POST /api/models/list-files` | List files attached to a model |
| `POST /api/models/download-file` | Download a specific model file |
| `POST /api/models/delete-file` | Delete a specific model file |
| `POST /api/models/upload-file` | Upload a file and attach it to a model |

### Notifications (`/api/notifications`)

| Route | Description |
|---|---|
| `POST /api/notifications/get` | List incoming notifications |
| `POST /api/notifications/mark_read` | Mark a notification as read |
| `POST /api/notifications/accept` | Accept or reject a share request |

### Projects (`/api/projects`)

| Route | Description |
|---|---|
| `POST /api/projects/current` | Get the current active project |
| `POST /api/projects/create` | Create a new project |
| `POST /api/projects/open` | Set a project as current |
| `POST /api/projects/delete` | Delete a project |
| `POST /api/projects/rename` | Rename a project |
| `POST /api/projects/list` | List all projects |

### Tables (`/api/tables`)

| Route | Description |
|---|---|
| `POST /api/tables/headers` | Get column headers for a table |
| `POST /api/tables/data` | Query rows with filters, sorting, and pagination |
| `POST /api/tables/distinct-values` | Get distinct values for a column |
| `POST /api/tables/row-count` | Count rows matching filters |
| `POST /api/tables/all-headers` | Get all column headers for a table |
| `POST /api/tables/set-columns-order` | Persist a custom column order |
| `POST /api/tables/add-column` | Add a new column to a table |
| `POST /api/tables/set-column-formatting` | Persist formatting for a column |
| `POST /api/tables/get-column-formatting` | Get persisted formatting for a table |
| `POST /api/tables/update-row` | Update a single row |
| `POST /api/tables/update-rows` | Update a column value for multiple rows |
| `POST /api/tables/delete-rows` | Delete rows by ID or filter |
| `POST /api/tables/summary` | Get summary statistics for selected columns |
| `POST /api/tables/add-row` | Add a new row to a table |
| `POST /api/tables/download-excel` | Export selected tables to Excel |
| `POST /api/tables/upload-excel` | Import an Excel file into tables |
| `POST /api/tables/check-excel-sheets` | Check whether sheet names exist in the model |

### SQL Client (`/api/sql-client`)

| Route | Description |
|---|---|
| `POST /api/sql-client/objects` | List tables and views in a model |
| `POST /api/sql-client/execute` | Execute a SQL query against a model |
| `POST /api/sql-client/ddl` | Get the DDL for a table or view |
| `POST /api/sql-client/history` | List SQL query history for a model |
| `POST /api/sql-client/history/add` | Add an entry to SQL query history |

### Tasks (`/api/tasks`)

| Route | Description |
|---|---|
| `POST /api/tasks/list` | List tasks available for a model |
| `POST /api/tasks/run` | Submit and run a model task |
| `POST /api/tasks/running` | List currently running tasks |
| `POST /api/tasks/status` | Get the status of a task |
| `POST /api/tasks/details` | Get detailed task information |
| `POST /api/tasks/cancel` | Cancel a running task |
| `POST /api/tasks/restore-db` | Restore the database from a task snapshot |
| `POST /api/tasks/get-diff` | Get the diff produced by a task |

### Scheduler (`/api/scheduler`)

| Route | Description |
|---|---|
| `POST /api/scheduler/schedules` | List all scheduled jobs |
| `POST /api/scheduler/update-schedule` | Update a schedule's cron expression or enabled flag |
| `POST /api/scheduler/run` | Manually queue a schedule to run |
| `POST /api/scheduler/executions` | List execution history for a schedule |
| `POST /api/scheduler/get-task-schedule` | Get the schedule for a specific model task |
| `POST /api/scheduler/set-task-schedule` | Create or update a schedule for a model task |

### User Management (`/api/user-management`)

Reserved prefix; no routes are implemented yet.

## Environment Variables

Defined in `.env` (see `.env.example`). Variables marked **Required** must be set or the app will fail to start.

### Core & Security

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | — | **Required**. Secret key for password hashing & JWT tokens |
| `PASSWORD_PEPPER` | `""` | Optional pepper for password hashing; set once and never change it |
| `ACCESS_TOKEN_EXPIRE_DAYS` | `1` | Access-token cookie expiry in days |
| `COOKIE_SECURE` | `true` | Set to `false` for local HTTP development; defaults to `true` if unset |
| `MAX_ATTEMPTS` | `5` | Failed login attempts before temporary lockout |
| `LOCK_TIME_MINUTES` | `1` | Account lockout duration after max failed attempts |

### Database & Storage

| Variable | Default | Description |
|---|---|---|
| `SQLITE_DB_PATH` | — | **Required**. Path to the SQLite database file |
| `DATA_FOLDER` | — | **Required**. Root folder for models, backups, logs, temp, and static files |
| `MAX_BACKUPS` | `10` | Maximum number of backups to keep per model |
| `SQLITE_DIFF_TOOL` | `sqldiff.exe` | Path to the `sqldiff` executable used for system backups |

### SMTP / Email

| Variable | Default | Description |
|---|---|---|
| `SMTP_URL` | — | SMTP server host (e.g. `smtppro.zoho.in`) |
| `SMTP_PORT` | `587` | SMTP server port |
| `SMTP_USER` | — | SMTP username |
| `SMTP_PWD` | — | SMTP password |
| `BASE_URL` | `http://localhost:3000` | Frontend base URL used in emails and links |

### Celery & Task Runtime

| Variable | Default | Description |
|---|---|---|
| `BROKER_URL` | `redis://localhost:6379/0` | Celery broker URL |
| `TASK_PROCESS_TIMEOUT_MINUTES` | `120` | Hard timeout for a task process in minutes |
| `DEFAULT_MAX_RUN_HOURS` | `24` | Max hours a task can run before it is auto-cancelled |

### S3 (Optional)

| Variable | Default | Description |
|---|---|---|
| `S3_ACCESS_KEY` | — | S3 access key |
| `S3_SECRET_KEY` | — | S3 secret key |
| `S3_BUCKET_NAME` | — | S3 bucket name |
| `S3_URL` | — | S3-compatible endpoint URL |
| `SETUP_S3` | `0` | Set to `1` to enable S3-backed storage setup |

### Logging & Cleanup

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Minimum log level for console and file logging |
| `TEMP_FILE_RETENTION_MINUTES` | `60` | How long temp files are kept before cleanup |
| `CELERY_LOG_RETENTION_DAYS` | `7` | How long Celery task log files are kept |
| `CELERY_MODEL_RETENTION_DAYS` | `30` | How long Celery model files are kept |
| `VACUUM_INTERVAL_DAYS` | `7` | Minimum days between SQLite `VACUUM` operations on model DBs |
| `EXECUTION_LOG_RETENTION_DAYS` | `30` | How long scheduler job execution logs are kept |
| `SQL_HISTORY_MAX_RECORDS_PER_USER` | `100` | Max SQL query history records kept per user |
| `TASK_HISTORY_MAX_RECORDS_PER_USER` | `30` | Max task history records kept per user |

## Logging

The application configures standard library logging during FastAPI startup and uses it in three places:

- Request logging in [app/main.py](app/main.py) for method, path, status code, duration, and request ID.
- Exception logging in [app/connection.py](app/connection.py) and [app/main.py](app/main.py) for failed DB operations and unhandled API errors.
- Business-event logging in [app/routers/auth/methods.py](app/routers/auth/methods.py) as an example of feature-level usage.

### Example Usage

```python
from app.logging_config import get_logger

logger = get_logger(__name__)


def create_project(...):
    logger.info("Creating project '%s' for user '%s'", project_name, user_email)
```

Example request log:

```text
2026-04-01 10:22:14,381 | INFO | app.main | Request completed [8d97d7f2-9357-4f7c-9a31-e9f5a4e7f0d2] POST /api/projects/create -> 200 in 18.47 ms
```
