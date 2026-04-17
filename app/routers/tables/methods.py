import json

from fastapi import HTTPException

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
        all_rows = model_cursor.execute(table_queries.get_table_columns, (table_name,)).fetchall()
        if len(all_rows) == 0:
            raise HTTPException(status_code=404, detail=f"Table not found: {table_name}")

        try:
            column_order_row = model_cursor.execute(table_queries.get_column_order, (table_name,)).fetchone()
            column_order = json.loads(column_order_row[0]) if column_order_row else []
        except Exception:
            column_order = []

    if len(column_order) == 0:
        return all_rows

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
    Fetch rows from a table applying selected columns, filters, sorting, and pagination.

    Parameters:
        cursor: Database cursor used to resolve the target model.
        user_email (str): Requesting user's email used for model resolution.
        model_name (str): Name of the model containing the table.
        project_name (str): Project name containing the model.
        table_name (str): Target table name.
        column_names (list[str]): Columns to select, in the requested order.
        select_filters (dict[str, list[str]]): Exact-match filters mapping column names to a list of permitted values.
        text_filters (dict[str, str]): Substring/text filters mapping column names to search terms.
        sort_columns (list[list[str, str]]): Sort specification as a list of [column_name, direction], where direction is typically "asc" or "desc".
        page_number (int): 1-based page number for pagination.
        page_size (int): Number of rows per page.

    Returns:
        list[tuple[str | int | float | bool | None, ...]]: Rows matching the query; each row is a tuple of column values in the same order as `column_names`. Elements may be `str`, `int`, `float`, `bool`, or `None`.

    Raises:
        HTTPException: with status code 404 if the model cannot be resolved for the given user/model/project.
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
    Get distinct values for a specific column in a table, applying selection and text filters and limiting results to page_size.

    Parameters:
        cursor: Database cursor or connection used to resolve the target model.
        user_email (str): Email of the authenticated user owning the model.
        model_name (str): Name of the model containing the table.
        project_name (str): Project name containing the model.
        table_name (str): Table to query.
        column_name (str): Column whose distinct values to retrieve.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters keyed by column name.
        text_filters (dict[str, str]): Full-text or substring filters keyed by column name.
        page_size (int): Maximum number of distinct values to return.

    Returns:
        list[str | int | float | bool | None]: Distinct values (each taken from the first column of each result row) in the order produced by the database, limited to page_size.

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

    with sql_connection(model_id, model_path) as model_cursor:
        object_type = _validate_table_and_column_names(model_cursor, table_name, [])
        if object_type != "table":
            raise HTTPException(status_code=404, detail=f"Cannot add column to view:{table_name}")
        row = model_cursor.execute(table_queries.check_if_table_column_exists, (table_name, column_name)).fetchone()
        if row:
            raise HTTPException(status_code=400, detail=f"Cannot add column: Column already exists: {column_name}")
        if column_type.upper() not in ("TEXT", "INTEGER", "REAL", "NUMERIC", "VARCHAR", "BOOLEAN"):
            raise HTTPException(status_code=400, detail=f"Cannot add column: Invalid column type: {column_type}")

        if "[" in column_name or "]" in column_name:
            raise HTTPException(status_code=400, detail=f"Cannot add column: Invalid column name: {column_name}")
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
            except json.JSONDecodeError:
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
    Update specified columns for a single row in the resolved model table.

    Parameters:
        cursor: Database cursor used to resolve the model and access control.
        user_email (str): Email of the requesting user.
        model_name (str): Name of the model containing the target table.
        project_name (str): Project that scopes the model.
        table_name (str): Target table within the model.
        row_id (int): Identifier of the row to update.
        updates (dict[str, str | int | float | bool | None]): Mapping of column names to new values; keys are column identifiers and values are the new cell values (None to set NULL).

    Raises:
        HTTPException(404): "Model not found" when the model cannot be resolved.
        HTTPException(403): "User does not have permission to modify the model" when the user lacks write access.
        HTTPException(404): "Table not found" when the target table does not exist in the model.
        HTTPException(400): "No valid columns provided for update" when the provided updates contain no updatable columns.
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
    Update a single column for multiple rows in the resolved model table and return how many rows were modified.

    Parameters:
        user_email (str): Email of the requesting user used to resolve model access.
        model_name (str): Name of the model containing the target table.
        project_name (str): Name of the project containing the model.
        table_name (str): Name of the table to update.
        row_ids (list[int]): List of row primary-key IDs to update.
        column_name (str): Name of the column to set.
        column_value (str | int | float | bool | None): Value to assign to the column for each specified row.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters to apply in conjunction with the row_ids; keys are column names and values are lists of allowed values for those columns. Only rows matching the specified row_ids and satisfying these filters will be updated.
        text_filters (dict[str, str]): Substring/text filters to apply in conjunction with the row_ids; keys are column names and values are the text to search for in those columns. Only rows matching the specified row_ids and satisfying these filters will be updated.

    Returns:
        int: Number of rows modified by the update.

    Raises:
        HTTPException(404): If the model cannot be resolved or the target table does not exist.
        HTTPException(403): If the user does not have permission to modify the model.
        HTTPException(400): If no valid columns were provided for the update.
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
    Validate that the specified table and columns exist in the database.

    Raises:
        HTTPException(404): If the table does not exist.
        HTTPException(404): If any of the specified columns do not exist on the table.
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
