from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from app.database import init_db
from app.routers.auth.router import router as auth_router
from app.routers.models.router import router as models_router
from app.routers.projects.router import router as projects_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    try:
        yield
    finally:
        pass


app = FastAPI(title="Supply Chain Lite API", lifespan=lifespan)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(models_router, prefix="/api/models", tags=["models"])
app.include_router(projects_router, prefix="/api/projects", tags=["projects"])

# @app.exception_handler(Exception)
# async def global_exception_handler(request: Request, exc: Exception):
#     return JSONResponse(
#         status_code=500,
#         content={"detail": str(exc)},
#     )
