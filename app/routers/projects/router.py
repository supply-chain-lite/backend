import sqlite3

from fastapi import APIRouter, Depends

from app.database import get_db
from app.routers.projects.schemas import ProjectCreateRequest, ProjectCreateResponse

router = APIRouter()


@router.post("/create", response_model=ProjectCreateResponse)
def create_project(
    body: ProjectCreateRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    cursor = db.execute(
        "INSERT INTO projects (name, description) VALUES (?, ?)",
        (body.name, body.description),
    )
    db.commit()
    return ProjectCreateResponse(id=cursor.lastrowid, name=body.name)
