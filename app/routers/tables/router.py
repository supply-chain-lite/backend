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
    """
    Get the column headers for the specified table for the authenticated user.

    Returns:
        table_schemas.TableHeaderResponse: Response object containing the table's column headers.
    """
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
    """
    Retrieve table rows using the request's column selection, filters, and pagination for the authenticated user.

    Parameters:
        request (TableDataRequest): Request containing model/project/table identifiers, column_names, select_filters, text_filters, page_number, and page_size.

    Returns:
        table_data_response (TableDataResponse): The requested rows.
    """
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
    """
    Return the distinct values for a specified column in a table, filtered and limited by the request.

    Returns:
        table_schemas.DistinctColumnValuesResponse: response containing the list of distinct values for the requested column.
    """
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


@router.post("/row-count", response_model=table_schemas.RowCountResponse)
def get_row_count(
    request: table_schemas.RowCountRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.RowCountResponse:
    """
    Retrieve the number of rows in the specified table for the authenticated user, applying any provided select and text filters.

    Returns:
        RowCountResponse: contains `row_count`, the number of rows that match the request's identifiers and filters.
    """
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        row_count = table_methods.get_row_count(
            cursor,
            useremail,
            request.model_name,
            request.project_name,
            request.table_name,
            request.select_filters,
            request.text_filters,
        )
        return table_schemas.RowCountResponse(row_count=row_count)


@router.post("/all-headers", response_model=table_schemas.TableAllHeadersResponse)
def get_all_table_headers(
    request: table_schemas.TableHeaderRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.TableAllHeadersResponse:
    """
    Fetches all column headers for the specified table belonging to the authenticated user.
    
    Returns:
        TableAllHeadersResponse: Contains the list of all column headers for the requested model, project, and table.
    """
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        headers = table_methods.get_table_columns_all(
            cursor, useremail, request.model_name, request.project_name, request.table_name
        )
        return table_schemas.TableAllHeadersResponse(headers=headers)


@router.post("/set-columns-order", response_model=table_schemas.MessageResponse)
def set_columns_order(
    request: table_schemas.SetColumnOrderRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.MessageResponse:
    """
    Update and persist the column order for the authenticated user's specified table.
    
    Parameters:
        request (table_schemas.SetColumnOrderRequest): Contains `model_name`, `project_name`, `table_name`, and `column_names` — the list of column names in the desired order.
    
    Returns:
        table_schemas.MessageResponse: Response containing a confirmation message.
    """
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        table_methods.set_columns_order(
            cursor, useremail, request.model_name, request.project_name, request.table_name, request.column_names
        )
        return table_schemas.MessageResponse(message="Columns order set successfully.")
