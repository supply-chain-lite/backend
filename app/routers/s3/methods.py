import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.config import S3_ACCESS_KEY, S3_SECRET_KEY, S3_URL


def _make_s3_client(
    access_key: str | None = None,
    secret_key: str | None = None,
    allow_server_credentials: bool = True,
):
    """Create an S3 client using request credentials, configured keys, or AWS discovery."""
    if bool(access_key) != bool(secret_key):
        raise HTTPException(status_code=400, detail="Both S3 access_key and secret_key must be provided")

    if not allow_server_credentials and not (access_key and secret_key):
        raise HTTPException(status_code=400, detail="S3 access_key and secret_key are required")

    key_id = access_key
    secret = secret_key
    if allow_server_credentials:
        key_id = key_id or S3_ACCESS_KEY
        secret = secret or S3_SECRET_KEY
        if bool(key_id) != bool(secret):
            raise HTTPException(status_code=500, detail="S3 access key configuration is incomplete")

    client_options = {}
    if S3_URL:
        client_options["endpoint_url"] = S3_URL
    region = os.getenv("S3_REGION") or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if region:
        client_options["region_name"] = region
    if key_id and secret:
        client_options.update(aws_access_key_id=key_id, aws_secret_access_key=secret)

    # Without explicit keys, boto3 uses its provider chain: environment, shared
    # credentials/config, web identity, container credentials, or instance role.
    return boto3.client("s3", **client_options)


def list_files(
    bucket: str,
    prefix: str = "",
    access_key: str | None = None,
    secret_key: str | None = None,
    allow_server_credentials: bool = True,
):
    """List the immediate files and folders under an S3 bucket prefix."""
    if not bucket.strip():
        raise HTTPException(status_code=400, detail="bucket must not be empty")

    normalized_prefix = prefix.lstrip("/")
    if normalized_prefix and not normalized_prefix.endswith("/"):
        normalized_prefix += "/"

    entries = {}
    try:
        client = _make_s3_client(access_key, secret_key, allow_server_credentials)
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=normalized_prefix, Delimiter="/"):
            for folder in page.get("CommonPrefixes", []):
                key = folder["Prefix"]
                name = key[len(normalized_prefix) :].rstrip("/")
                entries[key] = {"key": key, "name": name, "type": "folder"}

            for item in page.get("Contents", []):
                key = item["Key"]
                # S3 may contain a zero-byte object used as a directory marker.
                if key == normalized_prefix and key.endswith("/"):
                    continue
                presigned_url = client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": bucket,
                        "Key": key,
                        "ResponseContentDisposition": "inline",
                    },
                    ExpiresIn=600,
                )
                entries[key] = {
                    "key": key,
                    "name": key[len(normalized_prefix) :],
                    "type": "file",
                    "size": item.get("Size"),
                    "last_modified": item.get("LastModified"),
                    "presigned_url": presigned_url,
                }
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in {"NoSuchBucket", "NotFound"}:
            raise HTTPException(status_code=404, detail="S3 bucket not found") from exc
        if error_code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken"}:
            raise HTTPException(
                status_code=403, detail="S3 access denied; check credentials and bucket permissions"
            ) from exc
        raise HTTPException(status_code=502, detail="S3 listing failed") from exc
    except BotoCoreError as exc:
        raise HTTPException(status_code=502, detail="Could not connect to S3") from exc

    return sorted(entries.values(), key=lambda entry: (entry["type"] != "folder", entry["name"].casefold()))
