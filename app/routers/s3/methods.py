import os
from urllib.parse import urlsplit

import boto3
import duckdb
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.config import S3_ACCESS_KEY, S3_SECRET_KEY
from app.connections.connection_duckdb import duckdb_resource_config
from app.serialization import serialize_database_cell

_PREVIEW_LIMIT = 500
_PREVIEW_EXTENSIONS = {".csv", ".txt", ".json", ".parquet", ".xlsx"}


def _make_s3_client(
    access_key: str | None = None,
    secret_key: str | None = None,
    allow_server_credentials: bool = True,
    endpoint_url: str | None = None,
    region: str | None = None,
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

    client_options = {
        # Path-style addressing is supported by AWS and required by many
        # S3-compatible providers, including Hetzner Object Storage.
        "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    }
    if endpoint_url:
        client_options["endpoint_url"] = endpoint_url
    region = region or os.getenv("S3_REGION") or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if not region and endpoint_url:
        host = urlsplit(endpoint_url).hostname or ""
        if host.endswith(".your-objectstorage.com"):
            region = host.split(".", 1)[0]
    if region:
        client_options["region_name"] = region
    if key_id and secret:
        client_options.update(aws_access_key_id=key_id, aws_secret_access_key=secret)

    # Without explicit keys, boto3 uses its provider chain: environment, shared
    # credentials/config, web identity, container credentials, or instance role.
    return boto3.client("s3", **client_options)


def list_files(
    bucket: str,
    endpoint_url: str,
    prefix: str = "",
    region: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    allow_server_credentials: bool = True,
):
    """List the immediate files and folders in an S3 bucket."""
    if not bucket.strip():
        raise HTTPException(status_code=400, detail="bucket must not be empty")
    if not endpoint_url.strip():
        raise HTTPException(status_code=400, detail="endpointURL must not be empty")
    endpoint = urlsplit(endpoint_url)
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        raise HTTPException(status_code=400, detail="endpointURL must be an http(s) S3 endpoint URL")

    normalized_prefix = prefix.lstrip("/")
    if normalized_prefix and not normalized_prefix.endswith("/"):
        normalized_prefix += "/"

    entries = {}
    try:
        client = _make_s3_client(
            access_key,
            secret_key,
            allow_server_credentials,
            endpoint_url,
            region,
        )
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=normalized_prefix, Delimiter="/"):
            for folder in page.get("CommonPrefixes", []):
                key = folder["Prefix"]
                name = key[len(normalized_prefix) :].rstrip("/")
                entries[key] = {"key": key, "name": name, "type": "folder"}

            for item in page.get("Contents", []):
                key = item["Key"]
                # S3 may contain zero-byte objects used as directory markers.
                if key.endswith("/"):
                    if key != normalized_prefix:
                        name = key[len(normalized_prefix) :].rstrip("/")
                        entries[key] = {"key": key, "name": name, "type": "folder"}
                    continue
                entries[key] = {
                    "key": key,
                    "name": key[len(normalized_prefix) :],
                    "type": "file",
                    "size": item.get("Size"),
                    "last_modified": item.get("LastModified"),
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


def get_presigned_url(
    bucket: str,
    endpoint_url: str,
    key: str,
    region: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    expires_in: int = 600,
    allow_server_credentials: bool = True,
) -> str:
    """Generate a temporary URL for downloading an S3 object."""
    if not bucket.strip():
        raise HTTPException(status_code=400, detail="bucket must not be empty")
    if not key.strip():
        raise HTTPException(status_code=400, detail="key must not be empty")
    if not endpoint_url.strip():
        raise HTTPException(status_code=400, detail="endpointURL must not be empty")
    endpoint = urlsplit(endpoint_url)
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        raise HTTPException(status_code=400, detail="endpointURL must be an http(s) S3 endpoint URL")

    try:
        client = _make_s3_client(
            access_key,
            secret_key,
            allow_server_credentials,
            endpoint_url,
            region,
        )
        return client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=expires_in,
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in {"NoSuchBucket", "NotFound"}:
            raise HTTPException(status_code=404, detail="S3 bucket not found") from exc
        if error_code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken"}:
            raise HTTPException(
                status_code=403, detail="S3 access denied; check credentials and bucket permissions"
            ) from exc
        raise HTTPException(status_code=502, detail="Could not generate S3 URL") from exc
    except BotoCoreError as exc:
        raise HTTPException(status_code=502, detail="Could not connect to S3") from exc


def preview_file(
    bucket: str,
    endpoint_url: str,
    key: str,
    region: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    allow_server_credentials: bool = True,
) -> dict:
    """Preview an S3 object directly through an in-memory DuckDB connection."""
    if not bucket.strip():
        raise HTTPException(status_code=400, detail="bucket must not be empty")
    if not key.strip():
        raise HTTPException(status_code=400, detail="key must not be empty")
    if not endpoint_url.strip():
        raise HTTPException(status_code=400, detail="endpointURL must not be empty")
    endpoint = urlsplit(endpoint_url)
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        raise HTTPException(status_code=400, detail="endpointURL must be an http(s) S3 endpoint URL")

    extension = os.path.splitext(key)[1].lower()
    if extension not in _PREVIEW_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Preview supports only csv, txt, json, parquet, and xlsx files",
        )

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

    region = region or os.getenv("S3_REGION") or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if not region and (endpoint.hostname or "").endswith(".your-objectstorage.com"):
        region = (endpoint.hostname or "").split(".", 1)[0]

    s3_url = f"s3://{bucket}/{key}"
    read_function = {
        ".csv": "read_csv_auto",
        ".txt": "read_csv_auto",
        ".json": "read_json_auto",
        ".parquet": "read_parquet",
        ".xlsx": "read_xlsx",
    }[extension]

    connection = None
    try:
        connection = duckdb.connect(database=":memory:", config=duckdb_resource_config())
        connection.execute("LOAD httpfs")
        if extension == ".xlsx":
            connection.execute("LOAD excel")

        secret_fields = ["TYPE s3"]
        if key_id and secret:
            secret_fields.extend([f"KEY_ID {_sql_string(key_id)}", f"SECRET {_sql_string(secret)}"])
        else:
            # Match the server's opt-in AWS credential-chain behavior when no
            # explicit request or server keys are configured.
            connection.execute("LOAD aws")
            secret_fields.extend(["PROVIDER credential_chain", "REFRESH auto"])
        if region:
            secret_fields.append(f"REGION {_sql_string(region)}")
        secret_fields.extend(
            [
                f"ENDPOINT {_sql_string(endpoint.netloc)}",
                f"USE_SSL {'true' if endpoint.scheme == 'https' else 'false'}",
                "URL_STYLE 'path'",
            ]
        )
        connection.execute("CREATE OR REPLACE SECRET s3_preview (" + ", ".join(secret_fields) + ")")
        result = connection.execute(f"SELECT * FROM {read_function}({_sql_string(s3_url)}) LIMIT {_PREVIEW_LIMIT + 1}")
        rows = result.fetchall()
        columns = [column[0] for column in result.description]
        return {
            "columns": columns,
            "rows": [
                {column: serialize_database_cell(value) for column, value in zip(columns, row)}
                for row in rows[:_PREVIEW_LIMIT]
            ],
            "truncated": len(rows) > _PREVIEW_LIMIT,
        }
    except HTTPException:
        raise
    except duckdb.Error as exc:
        error_message = str(exc).lower()
        if any(code in error_message for code in ("403", "access denied", "forbidden", "signaturedoesnotmatch")):
            raise HTTPException(
                status_code=403, detail="S3 access denied; check credentials and bucket permissions"
            ) from exc
        if any(code in error_message for code in ("404", "nosuchkey", "nosuchbucket", "not found")):
            raise HTTPException(status_code=404, detail="S3 bucket or object not found") from exc
        if "extension" in error_message or "httpfs" in error_message:
            raise HTTPException(status_code=502, detail="DuckDB could not load the required file reader") from exc
        raise HTTPException(status_code=400, detail="DuckDB could not read the object in this file format") from exc
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=502, detail="Could not configure S3 access") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not preview S3 object") from exc
    finally:
        if connection is not None:
            connection.close()


def _sql_string(value: str) -> str:
    """Escape a value embedded in a DuckDB SQL string literal."""
    return "'" + value.replace("'", "''") + "'"
