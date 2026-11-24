import re
from contextlib import closing

import google.auth
from fastapi import HTTPException
from google.api_core.exceptions import BadRequest, Forbidden, GoogleAPIError, NotFound, Unauthorized
from google.auth.exceptions import DefaultCredentialsError, GoogleAuthError
from google.auth.transport.requests import Request
from google.cloud import storage

from .schemas import S3Object

_CLOUD_PLATFORM_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
_BUCKET_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]")


def _service_account_credentials():
    try:
        credentials, project = google.auth.default(scopes=_CLOUD_PLATFORM_SCOPES)
    except DefaultCredentialsError as exc:
        raise HTTPException(status_code=503, detail="Google Cloud credentials are unavailable") from exc
    if not getattr(credentials, "service_account_email", None):
        raise HTTPException(status_code=503, detail="Google Cloud service account credentials are required")
    return credentials, project


def list_files(bucket: str, prefix: str) -> list[S3Object]:
    if not _BUCKET_NAME.fullmatch(bucket):
        raise HTTPException(status_code=400, detail="Invalid GCS bucket name")

    normalized_prefix = prefix.lstrip("/")
    if normalized_prefix and not normalized_prefix.endswith("/"):
        normalized_prefix += "/"

    try:
        credentials, project = _service_account_credentials()
        with closing(storage.Client(project=project, credentials=credentials)) as client:
            blobs = client.list_blobs(bucket, prefix=normalized_prefix, delimiter="/")
            entries = [
                S3Object(
                    key=blob.name,
                    name=blob.name.removeprefix(normalized_prefix),
                    type="file",
                    size=blob.size,
                    last_modified=blob.updated,
                )
                for blob in blobs
                if blob.name != normalized_prefix
            ]
            entries.extend(
                S3Object(key=folder, name=folder.removeprefix(normalized_prefix).rstrip("/"), type="folder")
                for folder in blobs.prefixes
            )
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="GCS bucket not found") from exc
    except (Forbidden, Unauthorized) as exc:
        raise HTTPException(status_code=403, detail="GCS access denied; check bucket IAM permissions") from exc
    except BadRequest as exc:
        raise HTTPException(status_code=400, detail="GCS rejected the bucket or prefix") from exc
    except (GoogleAPIError, GoogleAuthError) as exc:
        raise HTTPException(status_code=502, detail="GCS listing failed") from exc

    return sorted(entries, key=lambda entry: (entry.type != "folder", entry.name.casefold(), entry.key))


def get_presigned_url(bucket: str, key: str, expires_in: int) -> str:
    if not _BUCKET_NAME.fullmatch(bucket):
        raise HTTPException(status_code=400, detail="Invalid GCS bucket name")
    if not key.strip():
        raise HTTPException(status_code=400, detail="GCS key must not be empty")

    try:
        credentials, project = _service_account_credentials()
        # Metadata credentials resolve the attached service account's email on refresh.
        request = Request()
        with request.session:
            credentials.refresh(request)
        email = credentials.service_account_email
        if not email or email == "default" or not credentials.token:
            raise HTTPException(status_code=503, detail="Google Cloud service account identity is unavailable")

        with closing(storage.Client(project=project, credentials=credentials)) as client:
            blob = client.bucket(bucket).blob(key)
            # Passing both values makes the SDK sign via IAM Credentials signBlob.
            return blob.generate_signed_url(
                version="v4",
                expiration=expires_in,
                method="GET",
                response_disposition="inline",
                service_account_email=email,
                access_token=credentials.token,
            )
    except (GoogleAPIError, GoogleAuthError) as exc:
        raise HTTPException(
            status_code=502, detail="GCS URL signing failed; check the IAM Credentials API and signBlob permission"
        ) from exc
