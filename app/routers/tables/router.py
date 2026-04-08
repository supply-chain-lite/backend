"""API routes for table-related operations."""

from fastapi import APIRouter, Depends

from app.connection import master_connection
from app.routers.auth.methods import _get_user_from_token

from . import methods as table_methods
from . import schemas as table_schemas

router = APIRouter()


@router.post("/headers", response_model=table_schemas.TableHeaderResponse)
def get_table_headers(
    request: table_schemas.TableHeaderRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.TableHeaderResponse:
    """Return the headers of the specified table for the authenticated user."""
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        headers = table_methods.get_table_headers(
            cursor, useremail, request.model_name, request.project_name, request.table_name
        )
        return table_schemas.TableHeaderResponse(headers=headers)


@router.post("/data", response_model=table_schemas.TableDataResponse)
def get_table_data(
    request: table_schemas.TableDataRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.TableDataResponse:
    """Return the data of the specified table for the authenticated user."""
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        data = table_methods.get_table_data(
            cursor,
            useremail,
            request.model_name,
            request.project_name,
            request.table_name,
            request.column_names,
            request.select_filters,
            request.text_filters,
            request.page_number,
            request.page_size,
        )
        return table_schemas.TableDataResponse(data=data)


@router.post("/distinct-values", response_model=table_schemas.DistinctColumnValuesResponse)
def get_distinct_column_values(
    request: table_schemas.DistinctColumnValuesRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.DistinctColumnValuesResponse:
    """Return the distinct values of the specified column in the specified table for the authenticated user."""
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        values = table_methods.get_distinct_column_values(
            cursor,
            useremail,
            request.model_name,
            request.project_name,
            request.table_name,
            request.column_name,
            request.select_filters,
            request.text_filters,
            request.page_size,
        )
        return table_schemas.DistinctColumnValuesResponse(values=values)
