from datetime import datetime
from typing import Literal

from botocore.handlers import VALID_S3_ARN
from pydantic import BaseModel, Field, ValidationInfo, field_validator


class ObjectBrowserRequest(BaseModel):
    scheme: Literal["s3", "gs"] = "s3"
    endpoint: str = Field(default="", validate_default=True, description="Required for S3 requests")
    bucket: str = Field(min_length=1, description="Bare bucket name or S3 access-point ARN")
    region: str = ""
    access_key: str = ""
    secret_key: str = ""

    @field_validator("endpoint")
    @classmethod
    def require_s3_endpoint(cls, endpoint: str, info: ValidationInfo) -> str:
        if info.data.get("scheme") == "s3" and not endpoint.strip():
            raise ValueError("endpoint is required for S3 requests")
        return endpoint

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, bucket: str, info: ValidationInfo) -> str:
        if info.data.get("scheme") == "s3" and VALID_S3_ARN.fullmatch(bucket):
            return bucket
        if any(separator in bucket for separator in ("/", ":", "\\")):
            raise ValueError("bucket must be a bare name or an S3 access-point ARN for S3 requests")
        return bucket


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
