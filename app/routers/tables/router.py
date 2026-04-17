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
    Retrieve rows from a table according to requested columns, filters, sorting, and pagination for the authenticated user.

    Parameters:
        request (TableDataRequest): Identifiers (model_name, project_name, table_name) and retrieval options (column_names, select_filters, text_filters, sort_columns, page_number, page_size).

    Returns:
        TableDataResponse: Response whose `data` field contains the requested rows matching the provided identifiers and filters.
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
            request.sort_columns,
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


@router.post("/add-column", response_model=table_schemas.MessageResponse)
def add_column(
    request: table_schemas.AddColumnRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.MessageResponse:
    """
    Add a new column to a table owned by the authenticated user.

    Parameters:
        request (AddColumnRequest): Contains `model_name`, `project_name`, `table_name`, `column_name`, and `column_type` that identify the target table and describe the column to create.

    Returns:
        MessageResponse: Confirmation message "Column added successfully."
    """
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        table_methods.add_new_column(
            cursor,
            useremail,
            request.model_name,
            request.project_name,
            request.table_name,
            request.column_name,
            request.column_type,
        )
        return table_schemas.MessageResponse(message="Column added successfully.")


@router.post("/set-column-formatting", response_model=table_schemas.MessageResponse)
def set_column_formatting(
    request: table_schemas.SetColumnFormattingRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.MessageResponse:
    """
    Persist formatting settings for a specific column of a user's table.

    Parameters:
        request (SetColumnFormattingRequest): Contains table identifiers and formatting to apply:
            - model_name: model identifier
            - project_name: project identifier
            - table_name: table identifier
            - column_name: column identifier to update
            - column_type: the column's data type
            - format: formatting settings to persist
        user_data (tuple): Authentication-derived user data (injected dependency); only the user's email is used.

    Returns:
        MessageResponse: Confirmation message indicating the column formatting was set successfully.
    """
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        table_methods.set_column_formatting(
            cursor,
            useremail,
            request.model_name,
            request.project_name,
            request.table_name,
            request.column_name,
            request.column_type,
            request.format,
        )
        return table_schemas.MessageResponse(message="Column formatting set successfully.")


@router.post("/get-column-formatting", response_model=table_schemas.GetColumnFormattingResponse)
def get_column_formatting(
    request: table_schemas.TableHeaderRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.GetColumnFormattingResponse:
    """
    Return column formatting settings for the specified table for the authenticated user.

    Parameters:
        request (TableHeaderRequest): Identifies the target table via `model_name`, `project_name`, and `table_name`.

    Returns:
        column_formatting (dict): Mapping of column names to their persisted formatting settings.
    """
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        formatting_settings = table_methods.get_column_formatting(
            cursor,
            useremail,
            request.model_name,
            request.project_name,
            request.table_name,
        )
        return table_schemas.GetColumnFormattingResponse(column_formatting=formatting_settings)


@router.post("/update-row", response_model=table_schemas.MessageResponse)
def update_row(
    request: table_schemas.updateRowRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.MessageResponse:
    """
    Update values for a single row in the specified table.

    Parameters:
        request (updateRowRequest): Identifiers and update payload; must include `model_name`, `project_name`, `table_name`, `row_id`, and `updates` (mapping of column names to new values).

    Returns:
        MessageResponse: Confirmation message `"Row updated successfully."`
    """
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        table_methods.update_row(
            cursor,
            useremail,
            request.model_name,
            request.project_name,
            request.table_name,
            request.row_id,
            request.updates,
        )
        return table_schemas.MessageResponse(message="Row updated successfully.")


@router.post("/update-rows", response_model=table_schemas.updateRowValuesResponse)
def update_rows(
    request: table_schemas.updateRowValuesRequest, user_data: tuple = Depends(_get_user_from_token)
) -> table_schemas.updateRowValuesResponse:
    """
    Update multiple rows in a table by setting a single column to a given value.

    Parameters:
        request (updateRowValuesRequest): Identifiers and update payload with fields:
            - model_name: name of the model containing the project
            - project_name: project identifier
            - table_name: target table name
            - row_ids: list of row IDs to update
            - column_name: name of the column to set
            - column_value: value to assign to the column for each listed row

    Returns:
        updateRowValuesResponse: Object with `rows_updated` set to the number of rows that were updated.
    """
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        row_count = table_methods.update_rows(
            cursor,
            useremail,
            request.model_name,
            request.project_name,
            request.table_name,
            request.row_ids,
            request.column_name,
            request.column_value,
            request.select_filters,
            request.text_filters,
        )
        return table_schemas.updateRowValuesResponse(rows_updated=row_count)
