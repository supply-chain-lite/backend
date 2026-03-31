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