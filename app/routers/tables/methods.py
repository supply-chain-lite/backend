import datetime
import json
import re
import tempfile

import pandas as pd
import xlsxwriter as xw
from fastapi import HTTPException, UploadFile, responses
from python_calamine import CalamineWorkbook

from app.connection import sql_connection
from app.routers.models.methods import get_model_id_and_path

from . import queries as table_queries

SQLITE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ ]*$")


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


def _get_table_headers_with_types(cursor, table_name: str, get_all_columns=False) -> list[tuple[str, str]]:
    """
    Return the table's column headers with their SQL types, using a persisted column order when available.

    If a persisted column order exists and decodes to a list, headers are returned in that order including only columns that actually exist in the table. If no persisted order is present or none of its entries match existing columns, the database-defined column order is returned. JSON parsing errors for the persisted order are ignored and treated as no persisted order.

    If `get_all_columns` is True, the full list of columns from the database is returned in the database-defined order, ignoring any persisted column order.

    Returns:
        list[tuple[str, str]]: List of (column_name, column_type) tuples in the chosen order.
    """
    all_rows = cursor.execute(table_queries.get_table_columns, (table_name,)).fetchall()

    if get_all_columns:
        return all_rows
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
    date_columns: list[str],
    numeric_filters: list[tuple[str, str, str | int | float]],
    sort_columns: list[list[str, str]],
    page_number: int,
    page_size: int,
) -> list[tuple[str | int | float | bool | None, ...]]:
    """
    Fetch rows from a table applying selection, filters, sorting, and pagination.

    Parameters:
        user_email (str): Requesting user's email used for model resolution and access checks.
        model_name (str): Name of the model containing the table.
        project_name (str): Project name containing the model.
        table_name (str): Target table name.
        column_names (list[str]): Columns to return in the requested order; must contain at least one column.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters mapping column names to allowed values.
        text_filters (dict[str, str]): Substring/text filters mapping column names to search terms.
        date_columns (list[str]): Columns from `text_filters` that should be interpreted and compared as dates.
        numeric_filters (list[tuple[str, str, str | int | float]]): Numeric filter tuples referencing columns to include in validation and query construction.
        sort_columns (list[list[str, str]]): List of [column_name, direction] pairs specifying sort order (e.g., ["col", "asc"]).
        page_number (int): 1-based page number for pagination.
        page_size (int): Number of rows per page.

    Returns:
        list[tuple[str | int | float | bool | None, ...]]: Rows matching the query; each tuple contains column values in the same order as `column_names`.

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
    query_columns.extend([col for col, _, _ in numeric_filters])

    with sql_connection(model_id, model_path) as model_cursor:
        object_type = _validate_table_and_column_names(model_cursor, table_name, query_columns)
        access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
        if access_level is None or access_level[0] in ("read", "reader", "readonly"):
            object_type = "read_only_object"
        select_columns = ["rowid", *column_names] if object_type == "table" else list(column_names or [])
        query, params = table_queries.get_table_query(
            table_name,
            select_columns,
            select_filters,
            text_filters,
            date_columns,
            numeric_filters,
            sort_columns,
            page_number,
            page_size,
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
    date_columns: list[str],
    numeric_filters: list[tuple[str, str, str | int | float]],
    page_size: int,
) -> list[str | int | float | bool | None]:
    """
    Retrieve distinct values for a column applying exact-match, text, date, and numeric filters, limited to page_size.

    Parameters:
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters keyed by column name.
        text_filters (dict[str, str]): Text filters keyed by column name; columns listed in `date_columns` are matched against converted date strings.
        date_columns (list[str]): Columns from `text_filters` that should be interpreted as dates.
        numeric_filters (list[tuple[str, str, str | int | float]]): Numeric filter tuples (column, operator, value) to include in validation and query construction.
        page_size (int): Maximum number of distinct values to return.

    Returns:
        list[str | int | float | bool | None]: Distinct values for the specified column as produced by the database, ordered by the database and limited to `page_size`.

    Raises:
        HTTPException: Raised with status_code 404 and detail "Model not found" when the model cannot be resolved for the given user.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    query, params = table_queries.get_distinct_column_values_query(
        table_name, column_name, select_filters, text_filters, date_columns, numeric_filters, page_size
    )

    column_names = [column_name]
    column_names.extend(select_filters.keys())
    column_names.extend(text_filters.keys())
    column_names.extend([col for col, _, _ in numeric_filters])
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
    date_columns: list[str],
    numeric_filters: list[tuple[str, str, str | int | float]],
) -> int:
    """
    Compute the number of rows in a table that match the given selection and text filters.

    Parameters:
        user_email (str): Email of the authenticated user owning the model.
        model_name (str): Name of the model containing the table.
        project_name (str): Project name containing the model.
        table_name (str): Table to query.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters keyed by column name; each key maps to allowed values for that column.
        text_filters (dict[str, str]): Text filters keyed by column name. Filters for columns listed in `date_columns` are applied against converted date strings.
        date_columns (list[str]): Columns from `text_filters` that should be matched as dates after converting Excel-style serial values to SQLite dates.

    Returns:
        int: Count of rows matching the filters.

    Raises:
        HTTPException: Raised with status_code 404 and detail "Model not found" when the model cannot be resolved for the given user.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    query, params = table_queries.get_row_count_query(
        table_name, select_filters, text_filters, date_columns, numeric_filters
    )

    column_names = list(select_filters.keys())
    column_names.extend(text_filters.keys())
    column_names.extend([col for col, _, _ in numeric_filters])
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

    if not SQLITE_IDENTIFIER_RE.fullmatch(column_name):
        raise HTTPException(status_code=400, detail="Invalid characters in column name")

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
        status = _set_column_formatting(model_cursor, table_name, column_name, column_type, column_formatting)
        if status == 0:
            raise HTTPException(status_code=404, detail="Cannot set column format: Table not found: S_TableParameters")


def _set_column_formatting(
    model_cursor,
    table_name: str,
    column_name: str,
    column_type: str,
    column_formatting: dict[str, str | int | float | bool | None],
):
    row = model_cursor.execute(table_queries.check_if_table_exists, ("S_TableParameters",)).fetchone()
    if not row:
        return 0
    format_json = json.dumps(column_formatting)
    all_rows = model_cursor.execute(
        table_queries.set_column_formatting, (column_type, format_json, table_name, column_name)
    ).fetchall()
    if len(all_rows) == 0:
        model_cursor.execute(
            table_queries.insert_column_formatting, (table_name, column_name, column_type, format_json)
        )
    return 1


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
        generated_columns = _get_generated_columns(model_cursor, table_name)
        common_columns = [col for col in column_names if col.lower() in generated_columns]
        if common_columns:
            raise HTTPException(status_code=400, detail=f"Cannot update generated columns: {', '.join(common_columns)}")
        object_type = _validate_table_and_column_names(model_cursor, table_name, column_names)
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"View: {table_name} is not updatable")
        query, values = table_queries.update_row(table_name, row_id, updates)
        if len(values) <= 1:
            raise HTTPException(status_code=400, detail="No valid columns provided for update")
        model_cursor.execute(query, values)


def _get_generated_columns(cursor, table_name: str) -> list[str]:
    """
    Retrieve the list of generated columns for a given table.

    Parameters:
        cursor: Database cursor to execute the query.
        table_name (str): Name of the table to check for generated columns.
    Returns:
        list[str]: A list of generated column names for the specified table.
    """
    rows = cursor.execute(table_queries.get_generated_columns, (table_name,)).fetchall()
    generated_columns = [row[0].lower() for row in rows]
    return generated_columns


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
    date_columns: list[str],
    numeric_filters: list[tuple[str, str, str | int | float]],
):
    """
    Update a single column for multiple rows in a model table.

    Parameters:
        row_ids (list[int]): Primary-key IDs of rows targeted for the update; only these rows are considered.
        column_name (str): Name of the column to set.
        column_value (str | int | float | bool | None): Value to assign to the column for each specified row.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters whose keys are column names and values are lists of allowed values; rows must match these in addition to being in `row_ids`.
        text_filters (dict[str, str]): Text-search filters whose keys are column names and values are the substring to match; for columns listed in `date_columns`, matching is performed against converted date strings.
        date_columns (list[str]): Column names from `text_filters` that should be interpreted and matched as dates.
        numeric_filters (list[tuple[str, str, str | int | float]]): Numeric filter tuples (column, operator, value) whose referenced columns are validated and applied together with other filters.

    Returns:
        int: Number of rows modified by the update.

    Raises:
        HTTPException(404): If the model cannot be resolved, the target table does not exist, or the target is a non-updatable view.
        HTTPException(403): If the user does not have permission to modify the model.
        HTTPException(400): If attempting to update a generated column or if provided filters/values are invalid.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
    if access_level is None or access_level[0] in ("read", "reader", "readonly"):
        raise HTTPException(status_code=403, detail="User does not have permission to modify the model")
    with sql_connection(model_id, model_path) as model_cursor:
        generated_columns = _get_generated_columns(model_cursor, table_name)
        if column_name.lower() in generated_columns:
            raise HTTPException(status_code=400, detail=f"Cannot update generated column: {column_name}")
        column_names = [column_name]
        column_names.extend(select_filters.keys())
        column_names.extend(text_filters.keys())
        column_names.extend([col for col, _, _ in numeric_filters])
        object_type = _validate_table_and_column_names(model_cursor, table_name, column_names)
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"View: {table_name} is not updatable")
        query, values = table_queries.update_rows(
            table_name, row_ids, column_name, column_value, select_filters, text_filters, date_columns, numeric_filters
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
    date_columns: list[str],
    numeric_filters: list[tuple[str, str, str | int | float]],
):
    """
    Delete rows from a table that match the provided row IDs and filter criteria.

    Parameters:
        table_name (str): Target table name.
        row_ids (list[int]): Row IDs to delete.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters mapping column names to lists of allowed values.
        text_filters (dict[str, str]): Text-match filters mapping column names to search strings; columns listed in `date_columns` are matched as dates after conversion.
        date_columns (list[str]): Column names from `text_filters` that should be interpreted and matched as dates.
        numeric_filters (list[tuple[str, str, str | int | float]]): Numeric-range or comparison filters as tuples (column_name, operator, value).

    Returns:
        Number of rows deleted.

    Raises:
        fastapi.HTTPException:
            - 404 if the model is not found, the target is a view (not updatable), or a referenced table/column is missing.
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
        column_names.extend([col for col, _, _ in numeric_filters])
        object_type = _validate_table_and_column_names(model_cursor, table_name, column_names)
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"View: {table_name} is not updatable")
        query, values = table_queries.delete_rows(
            table_name, row_ids, select_filters, text_filters, date_columns, numeric_filters
        )
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
    date_columns: list[str],
    numeric_filters: list[tuple[str, str, str | int | float]],
):
    """
    Compute selected aggregate statistics for specified columns of a table.

    Parameters:
        column_names (dict[str, str]): Mapping of target column names to aggregate functions to compute. Only the functions "count", "avg", "sum", "min", and "max" (case-insensitive) are honored; others are ignored.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters applied to the query; filter columns are validated against the table.
        text_filters (dict[str, str]): Text-search filters applied to the query; filter columns are validated. Entries listed in `date_columns` are matched as dates (converted from Excel-style serials when applicable).
        date_columns (list[str]): Column names from `text_filters` that should be treated and matched as dates.
        numeric_filters (list[tuple[str, str, str | int | float]]): Numeric filters as tuples of (column, operator, value); referenced columns are validated and forwarded to the query builder.

    Returns:
        dict[str, Any]: Mapping from each requested column name (that used an allowed aggregate function) to its computed aggregate value.

    Raises:
        fastapi.HTTPException: 404 if the model, table, or any referenced column is not found; 400 if no valid aggregate functions are provided.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    with sql_connection(model_id, model_path) as model_cursor:
        column_names_list = list(column_names.keys())
        column_names_list.extend(select_filters.keys())
        column_names_list.extend(text_filters.keys())
        column_names_list.extend([col for col, _, _ in numeric_filters])
        _validate_table_and_column_names(model_cursor, table_name, column_names_list)
        validated_columns = {}
        allowed_functions = {"count", "avg", "sum", "min", "max"}
        for column_name, summary_function in column_names.items():
            if summary_function.lower() in allowed_functions:
                validated_columns[column_name] = summary_function

        if not validated_columns:
            raise HTTPException(status_code=400, detail="No valid summary functions provided")
        query, values = table_queries.get_summary_stats_query(
            table_name, validated_columns, select_filters, text_filters, date_columns, numeric_filters
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
        generated_columns = _get_generated_columns(model_cursor, table_name)
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"View: {table_name} is not updatable")
        query, query_values = table_queries.add_row(table_name, values, generated_columns)
        model_cursor.execute(query, query_values)


def export_tables_to_excel(cursor, user_email: str, model_name: str, project_name: str, table_names: list[str]):
    """
    Export one or more tables from the resolved model into a temporary Excel (.xlsx) file for download.

    Parameters:
        cursor: Database cursor used to resolve the model and read table data.
        user_email (str): Email of the requesting user used for model resolution.
        model_name (str): Name of the model containing the tables.
        project_name (str): Project name used in model resolution.
        table_names (list[str]): List of table names to export; must contain at least one name. Duplicate names are skipped case-insensitively.

    Returns:
        fastapi.responses.FileResponse: A response that serves a temporary .xlsx file. When a single table is exported the response filename is a sanitized version of that table name; when multiple tables are exported the response filename is a sanitized version of the model name.

    Raises:
        HTTPException(404): If the model cannot be resolved or a requested table does not exist.
        HTTPException(400): If `table_names` is empty.

    Notes:
        - Each table is written to its own worksheet; worksheet names are sanitized, limited to 31 characters, and made unique by appending a numeric suffix when necessary.
        - The export reads up to 1,000,000 rows per table and applies any per-column formatting metadata found in the model.
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
                query, params = table_queries.get_table_query(
                    table_name, select_columns, {}, {}, [], [], [], 1, 1000000
                )
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
    Write headers and rows into an xlsxwriter worksheet applying per-column sizing and formatting.

    Parameters:
        workbook: xlsxwriter Workbook used to create cell Format objects.
        worksheet: xlsxwriter Worksheet to write into.
        table_headers (list[tuple[str, str]]): Ordered sequence of (column_name, sql_type) used for header labels and default formatting decisions.
        data (iterable[iterable]): Iterable of rows; each row is an ordered sequence of cell values corresponding to table_headers.
        column_formats (dict|None): Optional per-column formatting metadata keyed by column name. Recognized keys:
            - column_type: "date", "datetime", or other (affects date/time formats)
            - prefix: literal string or currency code (USD/INR/EUR/GBP/JPY mapped to symbols)
            - thousand_separator: truthy to enable grouping
            - decimal_places: integer or numeric string controlling decimal digits

    Notes:
        - Header row is written in bold; column widths are set to fit header text with enforced minimums for date (>=12) and datetime (>=20).
        - Per-column Excel formats are computed from column_formats or inferred defaults (numeric format for numeric SQL types).
        - Supported formatting: date/datetime patterns, thousand separators, configurable decimal places, and optional prefix (currency or literal).
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
    sheet_actions: dict[str, str],
    file: UploadFile,
):
    """
    Import rows from the Excel worksheet named exactly as table_name into the specified database table, replacing existing rows.

    Parameters:
        file (UploadFile): The uploaded Excel file to read; must contain a worksheet named exactly `table_name`.
        table_name (str): Target table name and required worksheet name in the workbook.

    Returns:
        int: Number of rows inserted from the Excel worksheet (excluding the header row).

    Raises:
        HTTPException: 404 if the model is not found, if the worksheet is missing, or if the target is a non-updatable view;
                       403 if the user lacks modification permission;
                       400 if the Excel file does not contain at least a header row or other input validation fails.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")
    access_level = cursor.execute(table_queries.get_access_level, (model_id, user_email)).fetchone()
    if access_level is None or access_level[0] in ("read", "reader", "readonly"):
        raise HTTPException(status_code=403, detail="User does not have permission to modify the model")
    with sql_connection(model_id, model_path) as model_cursor:
        workbook = CalamineWorkbook.from_object(file.file)
        response_status = {}
        for table_name, action in sheet_actions.items():
            if action == "ignore":
                continue
            if action == "create":
                row = model_cursor.execute(table_queries.check_if_table_exists, (table_name,)).fetchone()
                if row:
                    response_status[table_name] = {"status": "failed", "reason": "object already exists"}
                    continue
                if table_name not in workbook.sheet_names:
                    response_status[table_name] = {"status": "failed", "reason": "worksheet not found"}
                    continue
                table_rows = workbook.get_sheet_by_name(table_name).to_python()
                if not table_rows or len(table_rows) < 1:
                    response_status[table_name] = {
                        "status": "failed",
                        "reason": "The Excel file must contain at least a header row",
                    }
                    continue
                try:
                    table_headers = _create_table_from_excel(model_cursor, table_name, table_rows)
                    column_formats = _get_column_formatting(model_cursor, table_name)
                    rows_imported = _import_excel_to_table(
                        model_cursor, table_rows, table_name, table_headers, column_formats
                    )
                    response_status[table_name] = {"rows_imported": rows_imported, "status": "success"}
                except Exception as e:
                    model_cursor.rollback_changes()
                    response_status[table_name] = {"status": "failed", "reason": str(e)}
                continue
            try:
                object_type = _validate_table_and_column_names(model_cursor, table_name, [])
            except Exception as e:
                model_cursor.rollback_changes()
                response_status[table_name] = {"status": "failed", "reason": str(e)}
                continue
            if object_type != "table" and action in ("upload", "delete", "create"):
                response_status[table_name] = {"status": "failed", "reason": "not a table"}
                continue
            if action == "delete":
                delete_query, _ = table_queries.delete_rows(table_name, [], {}, {}, [], [])
                model_cursor.execute(delete_query)
                rows_deleted = model_cursor.rowcount()
                model_cursor.intermediate_commit()
                response_status[table_name] = {"rows_deleted": rows_deleted, "status": "success"}
                continue
            if action == "upload":
                if table_name not in workbook.sheet_names:
                    response_status[table_name] = {"status": "failed", "reason": "worksheet not found"}
                    continue
                table_rows = workbook.get_sheet_by_name(table_name).to_python()
                if not table_rows or len(table_rows) < 1:
                    response_status[table_name] = {
                        "status": "failed",
                        "reason": "The Excel file must contain at least a header row",
                    }
                    continue
                try:
                    table_headers = _get_table_headers_with_types(model_cursor, table_name, True)
                    column_formats = _get_column_formatting(model_cursor, table_name)
                    rows_imported = _import_excel_to_table(
                        model_cursor, table_rows, table_name, table_headers, column_formats
                    )
                    response_status[table_name] = {"rows_imported": rows_imported, "status": "success"}
                except Exception as e:
                    model_cursor.rollback_changes()
                    response_status[table_name] = {"status": "failed", "reason": str(e)}
        return response_status


def _import_excel_to_table(model_cursor, all_rows, table_name, table_headers, column_formats):
    """
    Import rows from an Excel worksheet into the specified database table by matching Excel headers to table columns, replacing existing table rows with the imported data.

    Parameters:
        model_cursor: Database cursor for the target model; used to query defaults, execute delete/insert, and commit.
        all_rows (list[list]): Excel sheet rows as returned by the workbook reader; the first row is expected to be the header row.
        table_name (str): Target database table name.
        table_headers (list[tuple]): Ordered table columns as (column_name, sql_type).
        column_formats (dict): Per-column formatting metadata keyed by column name; used to guide value conversions.

    Behavior:
        - Matches Excel header names exactly to table column names and imports only those common columns in the Excel column order.
        - Loads database default values for non-provided columns, constructs a delete+insert payload, deletes all existing rows in the table, then bulk-inserts the converted Excel rows.
        - Calls the cursor's intermediate_commit() after successful insert.
        - If no Excel headers match any table columns, raises an HTTPException with status 400.

    Returns:
        int: Number of rows imported from the Excel worksheet (number of inserted rows).

    Raises:
        HTTPException(400): If no matching columns are found between the Excel sheet and the table, or if cell value conversion fails for any row/cell.
    """

    generated_columns = _get_generated_columns(model_cursor, table_name)
    excel_headers = [str(cell).strip() for cell in all_rows[0]]
    table_headers = [header for header in table_headers if header[0].lower() not in generated_columns]
    table_column_names = [col[0].lower() for col in table_headers]

    common_column_idxs = tuple(idx for idx, col in enumerate(excel_headers) if col.lower() in table_column_names)
    common_columns = tuple(excel_headers[idx].lower() for idx in common_column_idxs)
    if len(set(common_columns)) != len(common_columns):
        raise Exception(
            "Duplicate Excel headers map to the same table column after case-insensitive matching"
        )

    normalized_column_formats = {
        str(column_name).lower(): spec for column_name, spec in (column_formats or {}).items()
    }
    common_column_data_types = tuple(table_headers[table_column_names.index(col.lower())][1] for col in common_columns)
    common_column_formats = tuple(normalized_column_formats.get(col, {}).get("column_type", None) for col in common_columns)

    if len(common_column_idxs) == 0:
        raise Exception("No matching columns found between the Excel file and the target table")

    default_values = {}
    for column_name, default_value in model_cursor.execute(
        table_queries.get_default_values_query, (table_name,)
    ).fetchall():
        default_values[column_name.lower()] = default_value

    delete_query, insert_query = table_queries.get_excel_upload_insert_query(table_name, common_columns, default_values)
    insert_rows = []
    for row_idx, row in enumerate(all_rows[1:]):
        values = []
        for serial_idx, idx in enumerate(common_column_idxs):
            cell_raw = row[idx] if idx < len(row) else None
            cell_value = _get_cell_value(
                cell_raw,
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
    """
    Convert an Excel cell value into a database-storable value based on the column's SQL type and optional formatting.

    Parameters:
        value: The raw cell value from the Excel sheet; blank strings and None are treated as NULL.
        data_type (str): The SQL type of the target column (e.g., "STRING", "INT", "NUMERIC").
        column_type (str|None): Optional user formatting type (e.g., "date", "datetime"); affects string parsing.
        row_idx (int): Zero-based Excel row index (used for error messages).
        col_idx (int): Zero-based Excel column index (used for error messages).
        table_name (str): Target table name (used for error messages).

    Returns:
        The converted value suitable for insertion into the database:
          - None for empty cells;
          - str for text-like columns (with date/datetime formatted as strings when column_type indicates);
          - int for integer columns;
          - float for numeric columns;
          - the original value for any other SQL types.

    Raises:
        HTTPException: On parse or type mismatches (invalid date/datetime formats, numeric conversion failures, or numeric values provided where a date/datetime string is expected). Error details include 1-based row/column and table name.
    """
    if value is None:
        return None
    if str(value).strip() == "":
        return None

    if data_type.upper() in ("STRING", "TEXT", "VARCHAR", "CHAR", "DATE", "VARDATE"):
        if column_type is None or column_type.lower() not in ("date", "datetime"):
            return str(value)
        if column_type.lower() == "date":
            if isinstance(value, (int, float)):
                raise Exception(
                    f"Invalid date value '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': expected a date string, not a numeric value"
                )
            if isinstance(value, (datetime.datetime, datetime.date)):
                return value.strftime("%Y-%m-%d")
            try:
                parsed_date = datetime.datetime.strptime(str(value)[:10], "%Y-%m-%d")
                return parsed_date.strftime("%Y-%m-%d")
            except Exception:
                raise Exception(
                    f"Invalid date string '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': expected format YYYY-MM-DD"
                )
        if column_type.lower() == "datetime":
            if isinstance(value, (int, float)):
                raise Exception(
                    f"Invalid datetime value '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': expected a datetime string, not a numeric value"
                )
            if isinstance(value, (datetime.datetime, datetime.date)):
                return value.strftime("%Y-%m-%d %H:%M:%S")
            try:
                parsed_date = datetime.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
                return parsed_date.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                raise Exception(
                    f"Invalid datetime string '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': expected format YYYY-MM-DD HH:MM:SS"
                )
        return str(value)

    if data_type.upper() in ("INT", "INTEGER", "BIGINT", "SMALLINT"):
        if isinstance(value, (datetime.datetime, datetime.date)):
            return int(_datetime_to_excel_float(value))
        try:
            return int(value)
        except Exception as ex:
            raise Exception(
                f"Invalid integer value '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': {str(ex)}"
            )
    if data_type.upper() in ("NUMERIC", "FLOAT", "REAL", "NUMBER", "NUMDATE"):
        if isinstance(value, (datetime.datetime, datetime.date)):
            return _datetime_to_excel_float(value)
        try:
            return float(value)
        except Exception as ex:
            raise Exception(
                f"Invalid numeric value '{value}' at row {row_idx + 1}, column {col_idx + 1} in table '{table_name}': {str(ex)}"
            )
    if isinstance(value, (datetime.datetime, datetime.date)):
        if column_type and column_type.lower() == "date":
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def _datetime_to_excel_float(dt):
    # Excel's base date is Dec 30, 1899
    """
    Convert a Python date or datetime to an Excel serial date number.

    Parameters:
        dt (datetime.date | datetime.datetime): The date or datetime to convert. If a plain date is provided it is treated as midnight.

    Returns:
        float: Excel serial date value representing days (and fractional day for time) since 1899-12-30.
    """
    if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
        dt = datetime.datetime.combine(dt, datetime.time())
    base_date = datetime.datetime(1899, 12, 30)
    delta = dt - base_date
    # Convert the time difference to total days (including fractional time)
    return delta.total_seconds() / 86400.0


def check_excel_sheets_exist(cursor, user_email: str, model_name: str, project_name: str, sheet_names: list[str]):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    if len(sheet_names) == 0:
        return {}

    with sql_connection(model_id, model_path) as model_cursor:
        query = table_queries.get_object_types.format(placeholders=",".join(["(?)"] * len(sheet_names)))
        object_types = {}
        for name, obj_type in model_cursor.execute(query, sheet_names).fetchall():
            object_types[name] = obj_type
            if obj_type != "table":
                object_types[name] = "not a table"
        row = model_cursor.execute(table_queries.check_if_table_exists, ("S_TableGroup",)).fetchone()
        if not row:
            return object_types
        query = table_queries.get_table_types.format(placeholders=",".join(["(?)"] * len(sheet_names)))
        for name, obj_type in model_cursor.execute(query, sheet_names).fetchall():
            if object_types.get(name) == "table":
                object_types[name] = obj_type

    return object_types


def _create_table_from_excel(model_cursor, table_name, all_rows):
    """
    Create a new database table based on the header row of an Excel worksheet and insert the worksheet's data.

    Parameters:
        model_cursor: Database cursor for the target model; used to execute create and insert statements.
        table_name (str): Name of the new table to create; also used for error messages.
        all_rows (list[list]): Excel sheet rows as returned by the workbook reader; the first row is expected to be the header row.
    Behavior:
    """
    if not SQLITE_IDENTIFIER_RE.fullmatch(table_name):
        raise Exception(f"Invalid table name '{table_name}'")
    columns = []
    for cell in all_rows[0]:
        if cell is None or str(cell).strip() == "":
            raise Exception("Column names cannot be empty")
        columns.append(str(cell).strip())
    if len(set(columns)) != len(columns):
        raise Exception(f"Duplicate column names found in the header row: {columns}")
    if len(columns) == 0:
        raise Exception("The header row must contain at least one column name")
    for col in columns:
        if not SQLITE_IDENTIFIER_RE.fullmatch(col):
            raise Exception(f"Invalid column name '{col}'")
    data_frame = pd.DataFrame(all_rows[1:], columns=columns)
    column_types = {}
    date_columns = []
    datetime_columns = []
    for column in data_frame.columns:
        if pd.api.types.is_integer_dtype(data_frame[column]):
            column_types[column] = "INTEGER"
        elif pd.api.types.is_float_dtype(data_frame[column]):
            column_types[column] = "NUMERIC"
        elif pd.api.types.is_bool_dtype(data_frame[column]):
            column_types[column] = "INTEGER"
        elif pd.api.types.is_datetime64_any_dtype(data_frame[column]):
            column_types[column] = "NUMERIC"
            sample_values = data_frame[column].dropna().head(100)
            if all(isinstance(val, pd.Timestamp) and val.time() == datetime.time(0, 0) for val in sample_values):
                date_columns.append(column)
            else:
                datetime_columns.append(column)
        elif pd.api.types.is_string_dtype(data_frame[column]):
            column_types[column] = "TEXT"
        elif pd.api.types.is_object_dtype(data_frame[column]):
            sample_values = data_frame[column].dropna().head(100)
            if len(sample_values) == 0:
                column_types[column] = "TEXT"
            elif all(
                (
                    isinstance(val, pd.Timestamp)
                    or (isinstance(val, datetime.datetime) and not isinstance(val, pd.Timestamp))
                )
                and val.time() == datetime.time(0, 0)
                for val in sample_values
            ):
                column_types[column] = "NUMERIC"
                date_columns.append(column)
            elif all(
                isinstance(val, datetime.date) and not isinstance(val, datetime.datetime) for val in sample_values
            ):
                column_types[column] = "NUMERIC"
                date_columns.append(column)
            elif all(isinstance(val, (pd.Timestamp, datetime.datetime)) for val in sample_values):
                column_types[column] = "NUMERIC"
                datetime_columns.append(column)
            else:
                column_types[column] = "TEXT"
        else:
            column_types[column] = "TEXT"

    table_headers = [(col, column_types[col]) for col in columns]
    create_query = table_queries.create_table_query(table_name, table_headers)
    model_cursor.execute(create_query)
    for date_column in date_columns:
        _set_column_formatting(model_cursor, table_name, date_column, "DATE", {})
    for datetime_column in datetime_columns:
        _set_column_formatting(model_cursor, table_name, datetime_column, "DATETIME", {})
    return table_headers
