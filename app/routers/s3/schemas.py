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


class PresignedURLRequest(BaseModel):
    endpoint: str = Field(min_length=1)
    bucket: str = Field(min_length=1)
    key: str = Field(min_length=1)
    region: str = ""
    access_key: str = ""
    secret_key: str = ""
    expires_in: int = Field(default=600, ge=1, le=604800)


class PresignedURLResponse(BaseModel):
    presigned_url: str
    expires_in: int


class PreviewRequest(BaseModel):
    endpoint: str = Field(min_length=1)
    bucket: str = Field(min_length=1)
    key: str = Field(min_length=1)
    region: str = ""
    access_key: str = ""
    secret_key: str = ""


class PreviewResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, object]]
    truncated: bool


class S3Object(BaseModel):
    key: str
    name: str
    type: Literal["file", "folder"]
    size: int | None = None
    last_modified: datetime | None = None


class fileListResponse(BaseModel):
    files: list[S3Object]
