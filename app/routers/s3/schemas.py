from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class fileListRequest(BaseModel):
    endpoint: str = Field(min_length=1)
    bucket: str = Field(min_length=1)
    prefix: str
    region: str = ""
    access_key: str = ""
    secret_key: str = ""


class S3Object(BaseModel):
    key: str
    name: str
    type: Literal["file", "folder"]
    size: int | None = None
    last_modified: datetime | None = None
    presigned_url: str | None = None


class fileListResponse(BaseModel):
    files: list[S3Object]
