import sqlite3

from fastapi import APIRouter, Depends

from app.database import get_db
from app.routers.models.schemas import ModelCreateRequest, ModelCreateResponse

router = APIRouter()


@router.post("/create", response_model=ModelCreateResponse)
def create_model(
    body: ModelCreateRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    cursor = db.execute(
        "INSERT INTO models (name, description) VALUES (?, ?)",
        (body.name, body.description),
    )
    db.commit()
    return ModelCreateResponse(id=cursor.lastrowid, name=body.name)
