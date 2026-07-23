import os
import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_FOLDER, TEMP_FOLDER
from app.connection import master_connection
from app.database import init_db
from app.logging_config import configure_logging, get_logger
from app.routers.auth.router import router as auth_router
from app.routers.models.router import router as models_router
from app.routers.projects.router import router as projects_router
from app.routers.sql_client.router import router as sql_client_router
from app.routers.tables.router import router as tables_router
from app.routers.tasks.router import router as tasks_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application startup and shutdown tasks for the FastAPI application.

    On startup this configures logging, logs a startup message, initializes and migrates the database, and recreates the TEMP_FOLDER directory (deleting it first if it exists). On shutdown this logs a shutdown message. Exceptions raised during startup or while the application is running are not swallowed by this handler and will propagate after the shutdown message is emitted.
    """
    configure_logging(file_name="app.log")
    logger.info("Starting Supply Chain Lite API")
    init_db()
    folder_path = Path(TEMP_FOLDER)
    if folder_path.exists():
        for item in folder_path.iterdir():
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
    else:
        os.makedirs(folder_path, exist_ok=True)
    logger.info("Database initialization completed")
    try:
        yield
    finally:
        logger.info("Shutting down Supply Chain Lite API")


app = FastAPI(title="Supply Chain Lite API", lifespan=lifespan)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(models_router, prefix="/api/models", tags=["models"])
app.include_router(projects_router, prefix="/api/projects", tags=["projects"])
app.include_router(tables_router, prefix="/api/tables", tags=["tables"])
app.include_router(sql_client_router, prefix="/api/sql-client", tags=["sql-client"])
app.include_router(tasks_router, prefix="/api/tasks", tags=["tasks"])
app.mount("/", StaticFiles(directory=STATIC_FOLDER, html=True), name="static")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    started_at = perf_counter()
    response = await call_next(request)

    duration_ms = (perf_counter() - started_at) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "Request completed [%s] %s %s -> %s in %.2f ms",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "n/a")
    logger.exception(
        "Unhandled exception [%s] %s %s",
        request_id,
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    try:
        with master_connection() as cursor:
            cursor.execute(
                """INSERT INTO S_RequestErrors (RequestId, Method, UrlPath, ErrorType, ErrorDetail, ErrorCode)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (request_id, request.method, request.url.path, type(exc).__name__, str(exc), 500),
            )
    except Exception:
        logger.exception("Failed to record error in master database")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )
