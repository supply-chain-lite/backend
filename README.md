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
├── main.py             # FastAPI app entry point
├── config.py           # Settings loaded from .env
├── database.py         # SQLite connection & init
└── routers/
    ├── auth/           # Authentication & account management
    ├── models/         # Model CRUD, sharing, backups & templates
    └── projects/       # Project lifecycle management
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
uv run celery -A celery_app worker --loglevel=INFO
```

On Windows, add `--pool=solo` for local development. Worker activity is logged to the console and `LOG_FOLDER/celery.log` via the shared logging config. Sample tasks live in `celery_app/tasks.py`, and the pre-run / post-run hooks are registered in `celery_app/celery.py`.

Each task execution writes its logs to `CELERY_LOG_FOLDER/<task_uid>.log`.

### Linting & Formatting

```bash
# Check for lint errors
uv run ruff check

# Auto-format code
uv run ruff format
```

## API Endpoints

All routes accept **POST** only and are prefixed with `/api`.

### Auth (`/api/auth`)

| Route | Description |
|---|---|
| `POST /api/auth/register` | Register a new user account |
| `POST /api/auth/activate` | Activate account using activation code |
| `POST /api/auth/login` | Login and set access-token cookie |
| `POST /api/auth/logout` | Logout and clear access-token cookie |
| `POST /api/auth/me` | Get current user profile & role |
| `POST /api/auth/forgot-password` | Initiate password-reset flow |
| `POST /api/auth/reset-password` | Reset password with verification code |
| `POST /api/auth/change-password` | Change password (authenticated) |

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
| `POST /api/models/get-notifications` | List incoming share notifications |
| `POST /api/models/accept` | Accept or reject a share request |

### Projects (`/api/projects`)

| Route | Description |
|---|---|
| `POST /api/projects/current` | Get the current active project |
| `POST /api/projects/create` | Create a new project |
| `POST /api/projects/open` | Set a project as current |
| `POST /api/projects/delete` | Delete a project |
| `POST /api/projects/rename` | Rename a project |
| `POST /api/projects/list` | List all projects |

## Environment Variables

Defined in `.env` (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | — | Secret key for password hashing & tokens |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token expiry in minutes |
| `SQLITE_DB_PATH` | `./data.db` | Path to SQLite database file |
| `LOG_LEVEL` | `INFO` | Minimum log level for console and file logging |

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
