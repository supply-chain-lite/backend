"""API routes for project lifecycle and project context operations."""

from fastapi import APIRouter, Depends

from app.connection import master_connection
from app.routers.auth.methods import _get_user_from_token

from . import methods as sql_methods
from . import schemas as sql_schemas

router = APIRouter()


@router.post("/objects", response_model=sql_schemas.SQLObjectResponse)
def get_sql_objects(
    request: sql_schemas.SQLObjectRequest, user_data: tuple = Depends(_get_user_from_token)
) -> sql_schemas.SQLObjectResponse:
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        tables, views = sql_methods.get_sql_objects(cursor, useremail, request.model_name, request.project_name)
        return sql_schemas.SQLObjectResponse(tables=tables, views=views)


@router.post("/execute", response_model=sql_schemas.SQLQueryResponse)
def execute_sql_query(
    request: sql_schemas.SQLQueryRequest, user_data: tuple = Depends(_get_user_from_token)
) -> sql_schemas.SQLQueryResponse:
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        result = sql_methods.execute_sql_query(cursor, useremail, request.model_name, request.project_name, request.sql)
        return sql_schemas.SQLQueryResponse(**result)


@router.post("/ddl", response_model=sql_schemas.SQLObjectDDLResponse)
def get_object_ddl(
    request: sql_schemas.SQLObjectDDLRequest, user_data: tuple = Depends(_get_user_from_token)
) -> sql_schemas.SQLObjectDDLResponse:
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        ddl = sql_methods.get_object_ddl(
            cursor, useremail, request.model_name, request.project_name, request.object_name
        )
        return sql_schemas.SQLObjectDDLResponse(ddl=ddl)


@router.post("/history", response_model=sql_schemas.SQLHistoryResponse)
def get_sql_history(
    request: sql_schemas.SQLHistoryRequest, user_data: tuple = Depends(_get_user_from_token)
) -> sql_schemas.SQLHistoryResponse:
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        history = sql_methods.get_sql_history(cursor, useremail, request.model_name, request.project_name)
        return sql_schemas.SQLHistoryResponse(history=history)


@router.post("/history/add", response_model=sql_schemas.SQLHistoryAddResponse)
def add_sql_history(
    request: sql_schemas.SQLHistoryAddRequest, user_data: tuple = Depends(_get_user_from_token)
) -> sql_schemas.SQLHistoryAddResponse:
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        sql_methods.add_sql_history(
            cursor, useremail, request.model_name, request.project_name, request.sql, request.is_error, request.status
        )
        return sql_schemas.SQLHistoryAddResponse(message="SQL history added successfully")
