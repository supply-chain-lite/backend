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
    select_filters: dict[str, list[str]],
    text_filters: dict[str, str],
    page_number: int,
    page_size: int,
) -> list[tuple[str | int | float | bool | None, ...]]:
    """
    Fetches rows from a table using the provided columns, filters, and pagination.

    Returns:
        A list of rows; each row is a tuple of column values corresponding to the requested columns. Elements may be `str`, `int`, `float`, `bool`, or `None`.

    Raises:
        HTTPException: with status code 404 when the model cannot be resolved for the given user/model/project.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    query, params = table_queries.get_table_query(
        table_name, column_names, select_filters, text_filters, page_number, page_size
    )

    with sql_connection(model_id, model_path) as model_cursor:
        data = model_cursor.execute(query, params).fetchall()
        return data


def get_distinct_column_values(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    column_name: str,
    select_filters: dict[str, list[str]],
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
        select_filters (dict[str, list[str]]): Exact-match filters keyed by column name.
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

    with sql_connection(model_id, model_path) as model_cursor:
        values = model_cursor.execute(query, params).fetchall()
        return [row[0] for row in values]


def get_row_count(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    table_name: str,
    select_filters: dict[str, list[str]],
    text_filters: dict[str, str],
) -> int:
    """
    Compute the number of rows in a table that match the given selection and text filters.

    Parameters:
        user_email (str): Email of the authenticated user owning the model.
        model_name (str): Name of the model containing the table.
        project_name (str): Project name containing the model.
        table_name (str): Table to query.
        select_filters (dict[str, list[str]]): Exact-match filters keyed by column name; each key maps to allowed values for that column.
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

    with sql_connection(model_id, model_path) as model_cursor:
        row = model_cursor.execute(query, params).fetchone()
        return row[0] if row else 0
