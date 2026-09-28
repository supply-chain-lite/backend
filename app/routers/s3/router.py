from fastapi import APIRouter, Depends

from app.connections.connection import master_connection
from app.routers.auth.methods import _get_user_from_token, check_module_access

from . import methods as s3_methods
from . import schemas as s3_schemas

router = APIRouter()
this_api = "/api/s3"


@router.post("/list", response_model=s3_schemas.fileListResponse)
def list_folder_contents(
    request: s3_schemas.fileListRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> s3_schemas.fileListResponse:
    _useremail, _display_name, role_name = user_data
    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
    files = s3_methods.list_files(
        bucket=request.bucket,
        endpoint_url=request.endpoint,
        prefix=request.prefix,
        region=request.region,
        access_key=request.access_key,
        secret_key=request.secret_key,
        allow_server_credentials=role_name == "SUPER_ADMIN",
    )
    return s3_schemas.fileListResponse(files=files)


@router.post("/presigned-url", response_model=s3_schemas.PresignedURLResponse)
def create_presigned_url(
    request: s3_schemas.PresignedURLRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> s3_schemas.PresignedURLResponse:
    _useremail, _display_name, role_name = user_data
    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
    url = s3_methods.get_presigned_url(
        bucket=request.bucket,
        endpoint_url=request.endpoint,
        key=request.key,
        region=request.region,
        access_key=request.access_key,
        secret_key=request.secret_key,
        expires_in=request.expires_in,
        allow_server_credentials=role_name == "SUPER_ADMIN",
    )
    return s3_schemas.PresignedURLResponse(presigned_url=url, expires_in=request.expires_in)


@router.post("/preview", response_model=s3_schemas.PreviewResponse)
def preview_s3_file(
    request: s3_schemas.PreviewRequest,
    user_data: tuple = Depends(_get_user_from_token),
) -> s3_schemas.PreviewResponse:
    _useremail, _display_name, role_name = user_data
    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
    preview = s3_methods.preview_file(
        bucket=request.bucket,
        endpoint_url=request.endpoint,
        key=request.key,
        region=request.region,
        access_key=request.access_key,
        secret_key=request.secret_key,
        allow_server_credentials=role_name == "SUPER_ADMIN",
    )
    return s3_schemas.PreviewResponse(**preview)
