import datetime
import json
import re
import tempfile

import xlsxwriter as xw
from fastapi import HTTPException, UploadFile, responses
from python_calamine import CalamineWorkbook

from app.connection import sql_connection
from app.routers.models.methods import get_model_id_and_path

from . import queries as table_queries


def get_table_headers(
    cursor, user_email: str, model_name: str, project_name: str, table_name: str
) -> list[tuple[str, str]]:
    """
    Resolve a table's columns and return them in a persisted column order when available.

    If a persisted column order exists, returns only the columns from that order that are present in the table. If no persisted order exists or the persisted order yields no matching columns, returns the full list of table columns.

    Returns:
        list[tuple[str, str]]: List of (column_name, column_type) tuples.

    Raises:
        HTTPException(404): If the model cannot be resolved or the table does not exist.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    with sql_connection(model_id, model_path) as model_cursor:
        _validate_table_and_column_names(model_cursor, table_name, [])
        table_headers = _get_table_headers_with_types(model_cursor, table_name)
    return table_headers


def _get_table_headers_with_types(cursor, table_name: str) -> list[tuple[str, str]]:
    """
    Return the table's column headers with their SQL types, using a persisted column order when available.

    If a persisted column order exists and decodes to a list, headers are returned in that order including only columns that actually exist in the table. If no persisted order is present or none of its entries match existing columns, the database-defined column order is returned. JSON parsing errors for the persisted order are ignored and treated as no persisted order.

    Returns:
        list[tuple[str, str]]: List of (column_name, column_type) tuples in the chosen order.
    """
    all_rows = cursor.execute(table_queries.get_table_columns, (table_name,)).fetchall()
    try:
        column_order_row = cursor.execute(table_queries.get_column_order, (table_name,)).fetchone()
        decoded = json.loads(column_order_row[0]) if column_order_row else []
        column_order = decoded if isinstance(decoded, list) else []
    except Exception:  # cathed broadly to avoid any issues even if S_TableGroup doesnt exists
        column_order = []
    table_columns = {name: col_type for name, col_type in all_rows}
    table_headers = []
    for col_name in column_order:
        if col_name in table_columns:
            table_headers.append((col_name, table_columns[col_name]))
    if len(table_headers) == 0:
        return all_rows
    return table_headers


def get_table_data(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    column_names: list[str],
    select_filters: dict[str, list[str | int | float | bool | None]],
    text_filters: dict[str, str],
    sort_columns: list[list[str, str]],
    page_number: int,
    page_size: int,
) -> list[tuple[str | int | float | bool | None, ...]]:
    """
    Fetch rows from a table using the requested columns, filters, sorting, and pagination.

    Parameters:
        cursor: Database cursor used to resolve the target model and to check access.
        user_email (str): Requesting user's email for model resolution and access checks.
        model_name (str): Name of the model containing the table.
        project_name (str): Project name containing the model.
        table_name (str): Target table name.
        column_names (list[str]): Columns to return, in the requested order; must contain at least one column.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters mapping column names to allowed values.
        text_filters (dict[str, str]): Substring/text filters mapping column names to search terms.
        sort_columns (list[list[str, str]]): Sort specification as a list of [column_name, direction] pairs (e.g., ["col", "asc"]).
        page_number (int): 1-based page number for pagination.
        page_size (int): Number of rows per page.

    Returns:
        list[tuple[str | int | float | bool | None, ...]]: Rows matching the query; each row is a tuple of column values in the same order as `column_names`.

    Raises:
        HTTPException: 404 if the model cannot be resolved for the given user/model/project.
        HTTPException: 400 if `column_names` is empty.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    if len(column_names) == 0:
        raise HTTPException(status_code=400, detail="At least one column must be selected")

    query_columns = list(column_names)
    query_columns.extend(select_filters.keys())
    query_columns.extend(text_filters.keys())
    query_columns.extend([col for col, _ in sort_columns])

    with sql_connection(model_id, model_path) as model_cursor:
        object_type = _validate_table_and_column_names(model_cursor, table_name, query_columns)
        access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
        if access_level is None or access_level[0] in ("read", "reader", "readonly"):
            object_type = "read_only_object"
        select_columns = ["rowid", *column_names] if object_type == "table" else list(column_names or [])
        query, params = table_queries.get_table_query(
            table_name, select_columns, select_filters, text_filters, sort_columns, page_number, page_size
        )
        data = model_cursor.execute(query, params).fetchall()
        return data


def get_distinct_column_values(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    column_name: str,
    select_filters: dict[str, list[str | int | float | bool | None]],
    text_filters: dict[str, str],
    page_size: int,
) -> list[str | int | float | bool | None]:
    """
    Return distinct values for a specific column in a table, applying exact-match and text filters and limiting the result size.

    Parameters:
        user_email (str): Email of the authenticated user owning the model.
        model_name (str): Name of the model containing the table.
        project_name (str): Project name containing the model.
        table_name (str): Table to query.
        column_name (str): Column whose distinct values to retrieve.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters keyed by column name.
        text_filters (dict[str, str]): Full-text or substring filters keyed by column name.
        page_size (int): Maximum number of distinct values to return.

    Returns:
        list[str | int | float | bool | None]: Distinct values for the specified column as produced by the database, ordered by the database and limited to page_size.

    Raises:
        HTTPException: Raised with status_code 404 and detail "Model not found" when the model cannot be resolved for the given user.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    query, params = table_queries.get_distinct_column_values_query(
        table_name, column_name, select_filters, text_filters, page_size
    )

    column_names = [column_name]
    column_names.extend(select_filters.keys())
    column_names.extend(text_filters.keys())

    with sql_connection(model_id, model_path) as model_cursor:
        _validate_table_and_column_names(model_cursor, table_name, column_names)
        values = model_cursor.execute(query, params).fetchall()
        return [row[0] for row in values]


def get_row_count(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    select_filters: dict[str, list[str | int | float | bool | None]],
    text_filters: dict[str, str],
) -> int:
    """
    Compute the number of rows in a table that match the given selection and text filters.

    Parameters:
        user_email (str): Email of the authenticated user owning the model.
        model_name (str): Name of the model containing the table.
        project_name (str): Project name containing the model.
        table_name (str): Table to query.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters keyed by column name; each key maps to allowed values for that column.
        text_filters (dict[str, str]): Full-text or substring filters keyed by column name.

    Returns:
        int: Count of rows matching the filters.

    Raises:
        HTTPException: Raised with status_code 404 and detail "Model not found" when the model cannot be resolved for the given user.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    query, params = table_queries.get_row_count_query(table_name, select_filters, text_filters)

    column_names = list(select_filters.keys())
    column_names.extend(text_filters.keys())
    with sql_connection(model_id, model_path) as model_cursor:
        _validate_table_and_column_names(model_cursor, table_name, column_names)
        row = model_cursor.execute(query, params).fetchone()
        return row[0] if row else 0


def get_table_columns_all(cursor, user_email: str, model_name: str, project_name: str, table_name: str) -> list[str]:
    """
    Return the table's column names in the database-defined order.

    Does not apply any persisted or user-specific column ordering.

    Returns:
        A list of column names in the order defined by the database schema.

    Raises:
        HTTPException(404): If the model cannot be resolved or the table does not exist.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    with sql_connection(model_id, model_path) as model_cursor:
        _validate_table_and_column_names(model_cursor, table_name, [])
        all_rows = model_cursor.execute(table_queries.get_table_columns, (table_name,)).fetchall()

        table_columns = list(row[0] for row in all_rows)

    return table_columns


def set_columns_order(
    cursor, user_email: str, model_name: str, project_name: str, table_name: str, column_names: list[str]
) -> None:
    """
    Persist a user-defined column order for a table.

    Stores the provided column name sequence so get_table_headers can apply it; column names that do not exist in the table are ignored when the order is applied.

    Parameters:
        user_email (str): Email of the authenticated user performing the change.
        model_name (str): Name of the model containing the table.
        project_name (str): Project name containing the model.
        table_name (str): Table for which to set the column order.
        column_names (list[str]): Column names in the desired order.

    Raises:
        HTTPException: status_code=404, detail="Model not found" when the model cannot be resolved.
        HTTPException: status_code=403, detail="User does not have permission to modify the model" when the user lacks required access.
        HTTPException: status_code=404, detail="Cannot set column order: Table not found: S_TableGroup" when the required metadata table is missing.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
    if access_level is None or access_level[0] not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="User does not have permission to modify the model")

    with sql_connection(model_id, model_path) as model_cursor:
        _validate_table_and_column_names(model_cursor, table_name, column_names)
        row = model_cursor.execute(table_queries.check_if_table_exists, ("S_TableGroup",)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Cannot set column order: Table not found: S_TableGroup")
        column_order_json = json.dumps(column_names)
        all_rows = model_cursor.execute(table_queries.update_column_order, (column_order_json, table_name)).fetchall()
        if len(all_rows) == 0:
            model_cursor.execute(table_queries.insert_column_order, ("Other Tables", table_name, column_order_json))


def add_new_column(
    cursor, user_email: str, model_name: str, project_name: str, table_name: str, column_name: str, column_type: str
):
    """
    Add a new column to an existing table in the resolved model database.

    Parameters:
        table_name (str): Target table to modify.
        column_name (str): Name of the column to add.
        column_type (str): Column data type. Allowed values (case-insensitive): "TEXT", "INTEGER", "REAL", "NUMERIC", "VARCHAR", "BOOLEAN".

    Raises:
        fastapi.HTTPException: 404 if the model is not found.
        fastapi.HTTPException: 403 if the user does not have "admin" or "owner" access to the model.
        fastapi.HTTPException: 404 if the target table does not exist in the model database.
        fastapi.HTTPException: 400 if a column with the given name already exists on the table.
        fastapi.HTTPException: 400 if the provided `column_type` is not one of the allowed values.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
    if access_level is None or access_level[0] not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="User does not have permission to modify the model")

    if ";" in column_name or ";" in column_type or "[" in column_name or "]" in column_name:
        raise HTTPException(status_code=400, detail="Invalid character ;[] in column name or type")

    with sql_connection(model_id, model_path) as model_cursor:
        object_type = _validate_table_and_column_names(model_cursor, table_name, [])
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"Cannot add column to view:{table_name}")
        row = model_cursor.execute(table_queries.check_if_table_column_exists, (table_name, column_name)).fetchone()
        if row:
            raise HTTPException(status_code=400, detail=f"Cannot add column: Column already exists: {column_name}")
        if column_type.upper() not in ("TEXT", "INTEGER", "REAL", "NUMERIC", "VARCHAR", "BOOLEAN"):
            raise HTTPException(status_code=400, detail=f"Cannot add column: Invalid column type: {column_type}")

        this_query = table_queries.add_new_column.format(
            table_name=table_name, column_name=column_name, column_type=column_type
        )
        model_cursor.execute(this_query)


def set_column_formatting(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    column_name: str,
    column_type: str,
    column_formatting: dict[str, str | int | float | bool | None],
):
    """
    Set or update the persisted formatting metadata for a single column in a model table.

    This validates that the requesting user has "admin" or "owner" access to the resolved model and that the metadata table `S_TableParameters` exists, then stores `column_formatting` (JSON-serialized) for the specified `table_name`/`column_name` and `column_type`. If a formatting row for that column does not already exist, a new row is inserted.

    Parameters:
        user_email (str): Email of the requesting user used to resolve access.
        model_name (str): Name of the model containing the table.
        project_name (str): Name of the project containing the model.
        table_name (str): Name of the table whose column formatting is being set.
        column_name (str): Name of the column to set formatting for.
        column_type (str): Type/category of the column (stored alongside the formatting).
        column_formatting (dict[str, str | int | float | bool | None]): Formatting parameters to persist for the column; will be JSON-serialized.

    Raises:
        fastapi.HTTPException: 404 if the model is not found.
        fastapi.HTTPException: 403 if the user lacks permission to modify the model.
        fastapi.HTTPException: 404 if the metadata table `S_TableParameters` is not present.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
    if access_level is None or access_level[0] not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="User does not have permission to modify the model")
    with sql_connection(model_id, model_path) as model_cursor:
        _validate_table_and_column_names(model_cursor, table_name, [column_name])
        row = model_cursor.execute(table_queries.check_if_table_exists, ("S_TableParameters",)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Cannot set column format: Table not found: S_TableParameters")
        format_json = json.dumps(column_formatting)
        all_rows = model_cursor.execute(
            table_queries.set_column_formatting, (column_type, format_json, table_name, column_name)
        ).fetchall()
        if len(all_rows) == 0:
            model_cursor.execute(
                table_queries.insert_column_formatting, (table_name, column_name, column_type, format_json)
            )


def get_column_formatting(
    cursor, user_email: str, model_name: str, project_name: str, table_name: str
) -> dict[str, dict[str, str | int | float | bool | None]]:
    """
    Load persisted column formatting for the given table in the resolved model.

    If the model metadata table `S_TableParameters` is missing, returns an empty dict. For each stored formatting row, the function returns a mapping from column name to a formatting dictionary (parsed from JSON when present); each formatting dictionary contains a "column_type" entry set to the stored parameter type.

    Returns:
        dict[str, dict[str, str | int | float | bool | None]]: Mapping of column name to its formatting dictionary, where each dictionary includes a `"column_type"` key.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    with sql_connection(model_id, model_path) as model_cursor:
        result = _get_column_formatting(model_cursor, table_name)
        return result


def _get_column_formatting(model_cursor, table_name: str):
    """
    Builds a mapping of column names to their persisted formatting metadata for a given table.

    Attempts to read formatting rows from the S_TableParameters metadata table; if the table is absent returns an empty dict. Parsed JSON parameter values are normalized to dictionaries, with JSON parse errors or non-dictionary values converted to {}. Each returned value includes a "column_type" entry set to the stored parameter type.

    Parameters:
        table_name (str): The target table whose column formatting should be retrieved.

    Returns:
        dict: Mapping from column name (str) to a formatting dict that always contains a "column_type" key and may include additional formatting keys from the stored JSON.
    """
    row = model_cursor.execute(table_queries.check_if_table_exists, ("S_TableParameters",)).fetchone()
    if not row:
        return {}
    all_rows = model_cursor.execute(table_queries.get_column_formatting, (table_name,)).fetchall()
    result = {}
    for column_name, parameter_type, parameter_value in all_rows:
        try:
            this_dict = json.loads(parameter_value) if parameter_value else {}
            if not isinstance(this_dict, dict):
                this_dict = {}
        except Exception:
            this_dict = {}
        this_dict["column_type"] = parameter_type
        result[column_name] = this_dict
    return result


def update_row(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    row_id: int,
    updates: dict[str, str | int | float | bool | None],
):
    """
    Update specified columns of a single row in a model table.

    Parameters:
        user_email (str): Email of the requesting user.
        model_name (str): Name of the model containing the target table.
        project_name (str): Project that scopes the model.
        table_name (str): Target table within the model.
        row_id (int): Identifier of the row to update.
        updates (dict[str, str | int | float | bool | None]): Mapping of column names to new values; use `None` to set a column to NULL.

    Raises:
        HTTPException(status_code=404): "Model not found" when the model cannot be resolved.
        HTTPException(status_code=403): "User does not have permission to modify the model" when the user lacks write access.
        HTTPException(status_code=404): "View: {table_name} is not updatable" when the target is a view, or "Table not found" when the table does not exist.
        HTTPException(status_code=400): "No valid columns provided for update" when `updates` contains no updatable columns.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
    if access_level is None or access_level[0] in ("read", "reader", "readonly"):
        raise HTTPException(status_code=403, detail="User does not have permission to modify the model")
    with sql_connection(model_id, model_path) as model_cursor:
        column_names = list(updates.keys())
        object_type = _validate_table_and_column_names(model_cursor, table_name, column_names)
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"View: {table_name} is not updatable")
        query, values = table_queries.update_row(table_name, row_id, updates)
        if len(values) <= 1:
            raise HTTPException(status_code=400, detail="No valid columns provided for update")
        model_cursor.execute(query, values)


def update_rows(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    row_ids: list[int],
    column_name: str,
    column_value: str | int | float | bool | None,
    select_filters: dict[str, list[str | int | float | bool | None]],
    text_filters: dict[str, str],
):
    """
    Update a single column on multiple rows in a model table and return the number of rows changed.

    Parameters:
        row_ids (list[int]): Primary-key IDs of rows targeted for the update.
        column_name (str): Name of the column to set.
        column_value (str | int | float | bool | None): Value to assign to the column for each specified row.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters whose keys are column names and values are lists of allowed values; only rows that match both the provided `row_ids` and these filters will be updated.
        text_filters (dict[str, str]): Substring/text filters whose keys are column names and values are the text to search for; only rows that match both the provided `row_ids` and these text filters will be updated.

    Returns:
        int: Number of rows modified by the update.

    Raises:
        HTTPException(404): If the model cannot be resolved or the target table is not found or is a non-updatable view.
        HTTPException(403): If the user does not have permission to modify the model (read-only access).
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
    if access_level is None or access_level[0] in ("read", "reader", "readonly"):
        raise HTTPException(status_code=403, detail="User does not have permission to modify the model")
    with sql_connection(model_id, model_path) as model_cursor:
        column_names = [column_name]
        column_names.extend(select_filters.keys())
        column_names.extend(text_filters.keys())
        object_type = _validate_table_and_column_names(model_cursor, table_name, column_names)
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"View: {table_name} is not updatable")
        query, values = table_queries.update_rows(
            table_name, row_ids, column_name, column_value, select_filters, text_filters
        )
        model_cursor.execute(query, values)
        return model_cursor.rowcount()


def _validate_table_and_column_names(cursor, table_name: str, column_names: list[str]) -> str:
    """
    Confirm the table exists, validate that each name in `column_names` exists on that table, and return the table's object type.

    Returns:
        object_type (str): The object type for the table (for example, "table" or "view").

    Raises:
        fastapi.HTTPException: 404 if the table is not found (detail="Table not found: {table_name}").
        fastapi.HTTPException: 404 if any column is not found (detail="Column not found: {column_name} for table: {table_name}").
    """
    row = cursor.execute(table_queries.check_if_table_exists, (table_name,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Table not found: {table_name}")
    object_type = row[0].lower()
    for column_name in column_names:
        row = cursor.execute(table_queries.check_if_table_column_exists, (table_name, column_name)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Column not found: {column_name} for table: {table_name}")
    return object_type


def delete_rows(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    row_ids: list[int],
    select_filters: dict[str, list[str | int | float | bool | None]],
    text_filters: dict[str, str],
):
    """
    Delete rows from the specified table that match the given row IDs and filter criteria.

    Parameters:
        user_email (str): Email of the requesting user.
        model_name (str): Name of the model containing the table.
        project_name (str): Project that scopes the model.
        table_name (str): Target table name.
        row_ids (list[int]): Row IDs to delete.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters mapping column names to lists of allowed values.
        text_filters (dict[str, str]): Text-match filters mapping column names to search strings.

    Returns:
        int: Number of rows deleted.

    Raises:
        fastapi.HTTPException:
            - 404 if the model is not found or the target is a view (not updatable) or a referenced column/table is missing.
            - 403 if the user does not have permission to modify the model.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
    if access_level is None or access_level[0] in ("read", "reader", "readonly"):
        raise HTTPException(status_code=403, detail="User does not have permission to modify the model")
    with sql_connection(model_id, model_path) as model_cursor:
        column_names = list(select_filters.keys())
        column_names.extend(text_filters.keys())
        object_type = _validate_table_and_column_names(model_cursor, table_name, column_names)
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"View: {table_name} is not updatable")
        query, values = table_queries.delete_rows(table_name, row_ids, select_filters, text_filters)
        model_cursor.execute(query, values)
        return model_cursor.rowcount()


def get_summary_stats(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    column_names: dict[str, str],
    select_filters: dict[str, list[str | int | float | bool | None]],
    text_filters: dict[str, str],
):
    """
    Return summary statistics for the specified columns in a table.

    Parameters:
        column_names (dict[str, str]): Mapping of column names to summary functions to compute (e.g., {"price": "avg", "id": "count"}). Only the functions "count", "avg", "sum", "min", and "max" (case-insensitive) are accepted; others are ignored.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters where keys are column names and values are lists of allowed values for that column; these filter columns will be validated.
        text_filters (dict[str, str]): Text-search filters where keys are column names and values are search strings; these filter columns will be validated.

    Returns:
        dict[str, Any]: Mapping from each requested column name (that used an allowed summary function) to its computed aggregate value.

    Raises:
        fastapi.HTTPException: 404 if the model, table, or any referenced column is not found; 400 if no valid summary functions are provided.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    with sql_connection(model_id, model_path) as model_cursor:
        column_names_list = list(column_names.keys())
        column_names_list.extend(select_filters.keys())
        column_names_list.extend(text_filters.keys())
        _validate_table_and_column_names(model_cursor, table_name, column_names_list)
        validated_columns = {}
        allowed_functions = {"count", "avg", "sum", "min", "max"}
        for column_name, summary_function in column_names.items():
            if summary_function.lower() in allowed_functions:
                validated_columns[column_name] = summary_function

        if not validated_columns:
            raise HTTPException(status_code=400, detail="No valid summary functions provided")
        query, values = table_queries.get_summary_stats_query(
            table_name, validated_columns, select_filters, text_filters
        )
        result = model_cursor.execute(query, values).fetchone()
        summary_stats = {}
        for idx, column_name in enumerate(validated_columns.keys()):
            summary_stats[column_name] = result[idx]
        return summary_stats


def add_row(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    values: dict[str, str | int | float | bool | None],
):
    """
    Insert a new row into the specified table of a resolved model.

    Validates model resolution and user write access, ensures the target table and provided column names exist and that the object is an updatable table (not a view), then executes an INSERT with the supplied values.

    Parameters:
        values (dict[str, str | int | float | bool | None]): Mapping of column names to values for the new row.

    Raises:
        fastapi.HTTPException: 404 if the model is not found.
        fastapi.HTTPException: 404 if the model, table, or any referenced column is not found, or if the target is a view and not updatable.
        fastapi.HTTPException: 403 if the user does not have permission to modify the model.
        fastapi.HTTPException: 404 if the target is a view and therefore not updatable.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
    if access_level is None or access_level[0] in ("read", "reader", "readonly"):
        raise HTTPException(status_code=403, detail="User does not have permission to modify the model")
    with sql_connection(model_id, model_path) as model_cursor:
        column_names = list(values.keys())
        object_type = _validate_table_and_column_names(model_cursor, table_name, column_names)
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"View: {table_name} is not updatable")
        query, query_values = table_queries.add_row(table_name, values)
        model_cursor.execute(query, query_values)


def export_tables_to_excel(cursor, user_email: str, model_name: str, project_name: str, table_names: list[str]):
    """
    Export the specified tables into a temporary Excel (.xlsx) file and return a FastAPI FileResponse for downloading it.

    Parameters:
        table_names (list[str]): Names of tables to export; must include at least one name. Duplicate names (case-insensitive) are skipped.

    Returns:
        fastapi.responses.FileResponse: A response pointing to a temporary .xlsx file. The response's filename is a sanitized version of the single table name when one table is exported or the sanitized model name when exporting multiple tables.

    Raises:
        HTTPException(404): If the model cannot be resolved or a requested table does not exist.
        HTTPException(400): If `table_names` is empty.

    Behavior notes:
        - Each table is written to its own worksheet; worksheet names are sanitized, limited to 31 characters, and made unique by appending a numeric suffix when needed.
        - The export reads up to 1,000,000 rows per table.
        - Per-column formatting metadata (if present) is applied to worksheet columns.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    excel_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    excel_file.close()  # Close the file so that xlsxwriter can write to it on Windows
    excel_file_name = excel_file.name
    if len(table_names) == 0:
        raise HTTPException(status_code=400, detail="At least one table must be selected for export")
    if len(table_names) == 1:
        safe_base = re.sub(r'[\\/:*?"<>|]', "_", table_names[0]) or "export"
        this_file_name = f"{safe_base}.xlsx"
    else:
        safe_base = re.sub(r'[\\/:*?"<>|]', "_", model_name) or "export"
        this_file_name = f"{safe_base}.xlsx"
    with sql_connection(model_id, model_path) as model_cursor:
        with xw.Workbook(excel_file_name, {"constant_memory": True}) as wb:
            used_table_names = set()
            for table_name in table_names:
                if table_name.lower() in used_table_names:
                    continue
                _validate_table_and_column_names(model_cursor, table_name, [])
                table_headers = _get_table_headers_with_types(model_cursor, table_name)
                column_formatting = _get_column_formatting(model_cursor, table_name)
                select_columns = [col for col, _ in table_headers]
                query, params = table_queries.get_table_query(table_name, select_columns, {}, {}, [], 1, 1000000)
                data = model_cursor.execute(query, params).fetchall()
                sheet_name = re.sub(r"[\[\]:*?/\\]", "_", table_name)
                sheet_name = sheet_name.strip("'")
                sheet_name = sheet_name[:31] or "Sheet1"
                base_name = sheet_name[:28]
                if sheet_name.lower() in used_table_names:
                    suffix = 1
                    while sheet_name.lower() in used_table_names:
                        suffix += 1
                        sheet_name = f"{base_name}_{suffix}"
                used_table_names.add(sheet_name.lower())
                worksheet = wb.add_worksheet(sheet_name)
                _write_to_worksheet(wb, worksheet, table_headers, data, column_formatting)

    return responses.FileResponse(
        path=excel_file_name,
        filename=this_file_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _write_to_worksheet(workbook, worksheet, table_headers, data, column_formats):
    """
    Populate an xlsxwriter worksheet with table headers, sized columns, and formatted cell values.

    Parameters:
        workbook: xlsxwriter Workbook instance used to create Format objects.
        worksheet: xlsxwriter Worksheet instance to write into.
        table_headers (list[tuple[str, str]]): Sequence of (column_name, data_type) pairs used for header labels and default formatting decisions.
        data (iterable[iterable]): Rows of table data; each row is an ordered sequence of cell values matching table_headers.
        column_formats (dict|None): Optional per-column formatting metadata keyed by column name. Recognized keys include `column_type` ("date", "datetime", or other), `prefix` (literal string or currency code), `thousand_separator` (truthy to enable grouping), and `decimal_places` (integer or numeric string). Currency codes `USD`, `INR`, `EUR`, `GBP`, `JPY` are mapped to their symbols when used as `prefix`.

    Details:
        - Writes a bold header row and sets each column width to fit the header; enforces minimum widths for `date` (>=12) and `datetime` (>=20) column types.
        - Computes an Excel number/date format for each column from `column_formats`; if absent, applies a default numeric format for numeric data types.
        - Supported formatting features: date/datetime formats, thousand separators, configurable decimal places, and optional prefix (currency symbol or literal).
        - Writes all data rows starting at the second worksheet row, applying the computed per-column format where available.

    """

    currency_symbols = {
        "USD": "$",
        "INR": "\u20b9",
        "EUR": "\u20ac",
        "GBP": "\u00a3",
        "JPY": "\u00a5",
    }

    column_formats = column_formats or {}

    # Write header row and size each column to fit its header text
    header_format = workbook.add_format({"bold": True})
    for col_idx, (column_name, _) in enumerate(table_headers):
        column_width = len(str(column_name))
        column_type = column_formats.get(column_name, {}).get("column_type", "").lower()
        if column_type == "date":
            column_width = max(column_width, 12)
        elif column_type == "datetime":
            column_width = max(column_width, 20)
        worksheet.set_column(col_idx, col_idx, column_width)
        worksheet.write(0, col_idx, column_name, header_format)

    # Pre-compute per-column cell format
    column_cell_formats = []
    for column_name, data_type in table_headers:
        data_type_upper = (data_type or "").upper()
        col_spec = column_formats.get(column_name)

        prefix = column_formats.get(column_name, {}).get("prefix", None)
        thousand_separator = column_formats.get(column_name, {}).get("thousand_separator", None)
        decimal_places = column_formats.get(column_name, {}).get("decimal_places", None)
        column_type = column_formats.get(column_name, {}).get("column_type", None)

        num_format_str = None

        if col_spec is None:
            # No user-defined formatting for this column - apply defaults based on data_type
            if data_type_upper in ("NUMERIC", "FLOAT", "REAL", "NUMBER"):
                num_format_str = "#,##0.00"
            # INT/INTEGER and other types: no formatting
        else:
            # User-defined formatting exists for this column
            col_type_lower = str(column_type).lower() if column_type else ""
            if col_type_lower in ("date", "datetime"):
                num_format_str = "yyyy-mm-dd hh:mm:ss" if col_type_lower == "datetime" else "yyyy-mm-dd"
            else:
                base = "#,##0" if thousand_separator else "0"
                try:
                    decimal_int = int(decimal_places) if decimal_places is not None else 0
                except (ValueError, TypeError):
                    decimal_int = 0
                if decimal_int > 0:
                    base += "." + "0" * decimal_int

                prefix_str = ""
                if prefix:
                    prefix_key = str(prefix).upper()
                    if prefix_key in currency_symbols:
                        prefix_str = f'"{currency_symbols[prefix_key]}"'
                    else:
                        prefix_str = f'"{prefix}"'

                if prefix_str or thousand_separator or decimal_places is not None:
                    num_format_str = prefix_str + base

        cell_format = workbook.add_format({"num_format": num_format_str}) if num_format_str else None
        column_cell_formats.append(cell_format)

    # Write data rows
    for row_idx, row in enumerate(data, start=1):
        for col_idx, value in enumerate(row):
            cell_format = column_cell_formats[col_idx]
            if cell_format is not None:
                worksheet.write(row_idx, col_idx, value, cell_format)
            else:
                worksheet.write(row_idx, col_idx, value)


def upload_excel(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    file: UploadFile,
):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
    if access_level is None or access_level[0] in ("read", "reader", "readonly"):
        raise HTTPException(status_code=403, detail="User does not have permission to modify the model")
    with sql_connection(model_id, model_path) as model_cursor:
        object_type = _validate_table_and_column_names(model_cursor, table_name, [])
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"View: {table_name} is not updatable")
        table_headers = _get_table_headers_with_types(model_cursor, table_name)
        column_formats = _get_column_formatting(model_cursor, table_name)
        workbook = CalamineWorkbook.from_object(file.file)
        if table_name not in workbook.sheet_names:
            raise HTTPException(status_code=404, detail=f"Worksheet named '{table_name}' not found in the Excel file")
        table_rows = workbook.get_sheet_by_name(table_name).to_python()
        if not table_rows or len(table_rows) < 1:
            raise HTTPException(status_code=400, detail="The Excel file must contain at least a header row")
        return _import_excel_to_table(model_cursor, table_rows, table_name, table_headers, column_formats)


def _import_excel_to_table(model_cursor, all_rows, table_name, table_headers, column_formats):

    excel_headers = [str(cell).strip() for cell in all_rows[0]]
    table_column_names = [col[0] for col in table_headers]

    common_column_idxs = tuple(idx for idx, col in enumerate(excel_headers) if col in table_column_names)
    common_columns = tuple(excel_headers[idx] for idx in common_column_idxs)

    common_column_data_types = tuple(table_headers[table_column_names.index(col)][1] for col in common_columns)
    common_column_formats = tuple(column_formats.get(col, {}).get("column_type", None) for col in common_columns)

    if len(common_column_idxs) == 0:
        raise HTTPException(
            status_code=400, detail="No matching columns found between the Excel file and the target table"
        )

    default_values = {}
    for coumn_name, default_value in model_cursor.execute(
        table_queries.get_default_values_query, (table_name,)
    ).fetchall():
        default_values[coumn_name] = default_value

    delete_query, insert_query = table_queries.get_excel_upload_insert_query(table_name, common_columns, default_values)

    insert_rows = []
    for row_idx, row in enumerate(all_rows[1:]):
        values = []
        for serial_idx, idx in enumerate(common_column_idxs):
            cell_value = _get_cell_value(
                row[idx],
                common_column_data_types[serial_idx],
                common_column_formats[serial_idx],
                row_idx,
                idx,
                table_name,
            )
            values.append(cell_value)
        insert_rows.append(values)
    rows_inserted = len(insert_rows)
    model_cursor.execute(delete_query)
    if rows_inserted > 0:
        model_cursor.executemany(insert_query, insert_rows)
    model_cursor.intermediate_commit()
    return rows_inserted


def _get_cell_value(value, data_type, column_type, row_idx, col_idx, table_name):
    if value is None:
        return None
    if str(value).strip() == "":
        return None

    if data_type.upper() in ("STRING", "TEXT", "VARCHAR", "CHAR"):
        if column_type is None or column_type.lower() not in ("date", "datetime"):
            return str(value)
        if column_type.lower() == "date":
            if isinstance(value, (int, float)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid date value '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': expected a date string, not a numeric value",
                )
            if isinstance(value, datetime.datetime) or isinstance(value, datetime.date):
                return value.strftime("%Y-%m-%d")
            try:
                parsed_date = datetime.datetime.strptime(str(value)[:10], "%Y-%m-%d")
                return parsed_date.strftime("%Y-%m-%d")
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid date string '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': expected format YYYY-MM-DD",
                )
        if column_type.lower() == "datetime":
            if isinstance(value, (int, float)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid datetime value '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': expected a datetime string, not a numeric value",
                )
            if isinstance(value, datetime.datetime) or isinstance(value, datetime.date):
                return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    if data_type.upper() in ("INT", "INTEGER", "BIGINT", "SMALLINT"):
        if isinstance(value, datetime.datetime) or isinstance(value, datetime.date):
            return int(_datetime_to_excel_float(value))
        try:
            return int(value)
        except Exception as ex:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid integer value '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': {str(ex)}",
            )
    if data_type.upper() in ("NUMERIC", "FLOAT", "REAL", "NUMBER"):
        if isinstance(value, datetime.datetime) or isinstance(value, datetime.date):
            return _datetime_to_excel_float(value)
        try:
            return float(value)
        except Exception as ex:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid numeric value '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': {str(ex)}",
            )
    return value


def _datetime_to_excel_float(dt):
    # Excel's base date is Dec 30, 1899
    if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
        dt = datetime.datetime.combine(dt, datetime.time())
    base_date = datetime.datetime(1899, 12, 30)
    delta = dt - base_date
    # Convert the time difference to total days (including fractional time)
    return delta.total_seconds() / 86400.0
