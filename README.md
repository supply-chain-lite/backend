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
    ├── auth/           # POST /api/auth/register, /api/auth/login
    ├── models/         # POST /api/models/create
    └── projects/       # POST /api/projects/create
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

| Route | Description |
|---|---|
| `POST /api/auth/register` | Register a new user |
| `POST /api/auth/login` | Login and get access token |
| `POST /api/models/create` | Create a new model |
| `POST /api/projects/create` | Create a new project |

## Environment Variables

Defined in `.env` (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | — | Secret key for password hashing & tokens |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token expiry in minutes |
| `SQLITE_DB_PATH` | `./data.db` | Path to SQLite database file |