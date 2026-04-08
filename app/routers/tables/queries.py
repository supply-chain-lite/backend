from fastapi import HTTPException

get_table_columns = "select name, type from pragma_table_xinfo(?) "

get_column_order = "select ifnull(ColumnOrder, '[]') as ColumnOrder from S_TableGroup WHERE TableName = ?"


def get_table_query(
    table_name: str,
    column_names: list[str],
    select_filters: dict[str, list[str]],
    text_filters: dict[str, str],
    page_number: int,
    page_size: int,
) -> tuple[str, list]:
    params = []

    if len(column_names) == 0:
        raise HTTPException(status_code=400, detail="At least one column must be specified")

    if page_size <= 0:
        raise HTTPException(status_code=400, detail="Page size must be greater than 0")

    if page_number <= 0:
        raise HTTPException(status_code=400, detail="Page number must be greater than 0")

    select_query = f"SELECT rowid, [{'], ['.join(_escape_identifier(col) for col in column_names)}] FROM [{_escape_identifier(table_name)}] WHERE 1=1 "

    for column_name in select_filters:
        select_query += (
            f"AND [{_escape_identifier(column_name)}] IN ({', '.join('?' for _ in select_filters[column_name])}) "
        )
        params.extend(select_filters[column_name])

    for column_name, text in text_filters.items():
        select_query += f"AND UPPER([{_escape_identifier(column_name)}]) LIKE ? "
        params.append(f"%{text.upper()}%")

    offset = (page_number - 1) * page_size
    select_query += " LIMIT ? OFFSET ?"
    params.extend([page_size, offset])

    return select_query, params


def get_distinct_column_values_query(
    table_name: str,
    column_name: str,
    select_filters: dict[str, list[str]],
    text_filters: dict[str, str],
    page_size: int,
) -> tuple[str, list]:
    params = []

    if not column_name or column_name.strip() == "":
        raise HTTPException(status_code=400, detail="Column name must be specified")

    if page_size <= 0:
        raise HTTPException(status_code=400, detail="Page size must be greater than 0")

    query = f"SELECT DISTINCT [{_escape_identifier(column_name)}] FROM [{_escape_identifier(table_name)}] WHERE 1=1 "

    for filter_col, filter_values in select_filters.items():
        query += f"AND [{_escape_identifier(filter_col)}] IN ({', '.join('?' for _ in filter_values)}) "
        params.extend(filter_values)

    for filter_col, text in text_filters.items():
        query += f"AND UPPER([{_escape_identifier(filter_col)}]) LIKE ? "
        params.append(f"%{text.upper()}%")

    query += " LIMIT ?"
    params.append(page_size)

    return query, params


def _escape_identifier(name: str) -> str:
    """Escape a SQLite bracket-quoted identifier by doubling ] characters."""
    return name.replace("]", "]]")
