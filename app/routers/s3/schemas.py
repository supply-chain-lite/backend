from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class ObjectBrowserRequest(BaseModel):
    scheme: Literal["s3", "gs"] = "s3"
    endpoint: str = Field(default="", validate_default=True, description="Required for S3 requests")
    bucket: str = Field(min_length=1, pattern=r"^[^/:\\]+$", description="Bare bucket name")
    region: str = ""
    access_key: str = ""
    secret_key: str = ""

    @field_validator("endpoint")
    @classmethod
    def require_s3_endpoint(cls, endpoint: str, info: ValidationInfo) -> str:
        if info.data.get("scheme") == "s3" and not endpoint.strip():
            raise ValueError("endpoint is required for S3 requests")
        return endpoint


class fileListRequest(ObjectBrowserRequest):
    prefix: str


class PreviewRequest(ObjectBrowserRequest):
    key: str = Field(min_length=1)


class PresignedURLRequest(PreviewRequest):
    expires_in: int = Field(default=600, ge=1, le=604800)


class PresignedURLResponse(BaseModel):
    presigned_url: str
    expires_in: int


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
