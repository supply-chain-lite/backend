from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class fileListRequest(BaseModel):
    bucket: str
    prefix: str = ""
    access_key: str | None = None
    secret_key: str | None = None


class S3Object(BaseModel):
    key: str
    name: str
    type: Literal["file", "folder"]
    size: int | None = None
    last_modified: datetime | None = None
    presigned_url: str | None = None


class fileListResponse(BaseModel):
    files: list[S3Object]
