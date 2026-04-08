import json

from fastapi import HTTPException

from app.connection import sql_connection
from app.routers.models.methods import get_model_id_and_path

from . import queries as table_queries


def get_table_headers(
    cursor, user_email: str, model_name: str, project_name: str, table_name: str
) -> list[tuple[str, str]]:
    """Return the headers of the specified table for the authenticated user."""
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
    """Return the data of the specified table for the authenticated user."""
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
    """Return the distinct values of the specified column in the specified table for the authenticated user."""
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    query, params = table_queries.get_distinct_column_values_query(
        table_name, column_name, select_filters, text_filters, page_size
    )

    with sql_connection(model_id, model_path) as model_cursor:
        values = model_cursor.execute(query, params).fetchall()
        return [row[0] for row in values]
