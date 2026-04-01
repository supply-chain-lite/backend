import os
import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import TEMP_FOLDER
from app.database import init_db
from app.logging_config import configure_logging, get_logger
from app.routers.auth.router import router as auth_router
from app.routers.models.router import router as models_router
from app.routers.projects.router import router as projects_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    logger.info("Starting Supply Chain Lite API")
    init_db()
    if os.path.exists(TEMP_FOLDER):
        shutil.rmtree(TEMP_FOLDER)
    os.makedirs(TEMP_FOLDER, exist_ok=True)
    logger.info("Database initialization completed")
    try:
        yield
    finally:
        logger.info("Shutting down Supply Chain Lite API")


app = FastAPI(title="Supply Chain Lite API", lifespan=lifespan)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(models_router, prefix="/api/models", tags=["models"])
app.include_router(projects_router, prefix="/api/projects", tags=["projects"])


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
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )
