from fastapi import HTTPException

get_table_columns = "select name, type from pragma_table_xinfo(?) where UPPER(type) != 'BLOB' "

get_column_order = (
    "select ifnull(ColumnOrder, '[]') as ColumnOrder from S_TableGroup WHERE TableName = ? collate nocase"
)

get_access_level = (
    "select ifnull(lower(AccessLevel), 'read') from S_UserModels WHERE ModelId = ? and UserEmail = ? collate nocase"
)

update_column_order = "UPDATE S_TableGroup SET ColumnOrder = ? WHERE TableName = ? RETURNING rowid"

insert_column_order = "INSERT INTO S_TableGroup (GroupName, TableName, ColumnOrder) VALUES (?, ?, ?) RETURNING rowid"

check_if_table_exists = "select 1 from sqlite_master where type='table' and name=? collate nocase"

add_new_column = "ALTER TABLE [{table_name}] ADD COLUMN [{column_name}] {column_type}"

check_if_table_column_exists = "SELECT 1 FROM pragma_table_xinfo(?) WHERE name = ? COLLATE NOCASE"


def get_table_query(
    table_name: str,
    column_names: list[str],
    select_filters: dict[str, list[str]],
    text_filters: dict[str, str],
    sort_columns: list[list[str, str]],
    page_number: int,
    page_size: int,
) -> tuple[str, list]:
    """
    Builds a parameterized SQLite SELECT query that returns rowid and the specified columns, applying optional exact-match filters, case-insensitive substring filters, sorting, and pagination.

    Parameters:
        table_name (str): Name of the table to query.
        column_names (list[str]): Columns to include in the SELECT; must contain at least one name.
        select_filters (dict[str, list[str]]): Exact-match filters mapping column -> list of allowed values. Empty lists are ignored. If a filter list contains `None` along with other values, the condition becomes `IN (...) OR IS NULL`; if it contains only `None`, the condition becomes `IS NULL`.
        text_filters (dict[str, str]): Case-insensitive substring filters mapping column -> substring; each becomes `UPPER(column) LIKE '%SUBSTRING%'`. Falsy/empty values are ignored.
        sort_columns (list[list[str, str]]): Columns to sort by, each element is a list of [column_name, direction] where direction is 'ASC' or 'DESC'.
        page_number (int): 1-based page index used to compute OFFSET.
        page_size (int): Number of rows per page for LIMIT.

    Returns:
        tuple[str, list]: A parameterized SQL query string using `?` placeholders and the ordered list of parameter values to bind.

    Raises:
        HTTPException: If `column_names` is empty, or if `page_size` or `page_number` is less than or equal to zero.
    """
    params = []

    if len(column_names) == 0:
        raise HTTPException(status_code=400, detail="At least one column must be specified")

    if page_size <= 0:
        raise HTTPException(status_code=400, detail="Page size must be greater than 0")

    if page_number <= 0:
        raise HTTPException(status_code=400, detail="Page number must be greater than 0")

    select_query = f"SELECT rowid, [{'], ['.join(_escape_identifier(col) for col in column_names)}] FROM [{_escape_identifier(table_name)}] WHERE 1=1 "

    for filter_col, filter_values in select_filters.items():
        if not filter_values:
            continue  # Skip empty filter lists to avoid syntax errors in the SQL query
        if None in filter_values:
            non_null_values = [value for value in filter_values if value is not None]
            if non_null_values:
                select_query += f"AND ([{_escape_identifier(filter_col)}] IN ({', '.join('?' for _ in non_null_values)}) OR [{_escape_identifier(filter_col)}] IS NULL) "
                params.extend(non_null_values)
            else:
                select_query += f"AND [{_escape_identifier(filter_col)}] IS NULL "
        else:
            select_query += f"AND [{_escape_identifier(filter_col)}] IN ({', '.join('?' for _ in filter_values)}) "
            params.extend(filter_values)

    for column_name, text in text_filters.items():
        if not text:
            continue  # Skip empty text filters to avoid unnecessary conditions
        select_query += f"AND UPPER([{_escape_identifier(column_name)}]) LIKE ? "
        params.append(f"%{text.upper()}%")

    offset = (page_number - 1) * page_size
    if len(sort_columns) > 0:
        select_query += "ORDER BY "
    for column_name, direction in sort_columns:
        if direction.upper() not in ("ASC", "DESC"):
            raise HTTPException(
                status_code=400, detail=f"Invalid sort direction '{direction}' for column '{column_name}'"
            )
        select_query += f"[{_escape_identifier(column_name)}] {direction.upper()}, "
    select_query = select_query.rstrip(", ")  # Remove trailing comma and space if sort_columns were added
    select_query += " LIMIT ? OFFSET ?"
    params.extend([page_size, offset])

    print("Generated SQL Query:", select_query)
    return select_query, params


def get_distinct_column_values_query(
    table_name: str,
    column_name: str,
    select_filters: dict[str, list[str | int | float | bool | None]],
    text_filters: dict[str, str],
    page_size: int,
) -> tuple[str, list]:
    """
    Return distinct values for a single column from a table applying exact-match and case-insensitive substring filters, limited to page_size.

    Parameters:
        table_name (str): Table to query.
        column_name (str): Target column for distinct values; must be non-empty or a 400 HTTPException is raised.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters keyed by column. Empty lists are ignored. If a filter list contains `None`, the generated condition is `IS NULL` when all values are `None`, or `IN (...) OR IS NULL` when mixed with non-null values. Filters on the target `column_name` are skipped.
        text_filters (dict[str, str]): Case-insensitive substring filters keyed by column; falsy/empty values are ignored and remaining values are applied as `UPPER(col) LIKE '%VALUE%'`.
        page_size (int): Maximum number of distinct values to return; must be greater than 0 or a 400 HTTPException is raised.

    Returns:
        tuple[str, list]: SQL query string with `?` placeholders and the ordered list of parameters to bind.
    """
    params = []

    if not column_name or column_name.strip() == "":
        raise HTTPException(status_code=400, detail="Column name must be specified")

    if page_size <= 0:
        raise HTTPException(status_code=400, detail="Page size must be greater than 0")

    query = f"SELECT DISTINCT [{_escape_identifier(column_name)}] FROM [{_escape_identifier(table_name)}] WHERE 1=1 "

    for filter_col, filter_values in select_filters.items():
        if filter_col.upper() == column_name.upper():
            continue  # Skip filters on the target column for distinct values
        if not filter_values:
            continue  # Skip empty filter lists to avoid syntax errors in the SQL query
        if None in filter_values:
            non_null_values = [value for value in filter_values if value is not None]
            if non_null_values:
                query += f"AND ([{_escape_identifier(filter_col)}] IN ({', '.join('?' for _ in non_null_values)}) OR [{_escape_identifier(filter_col)}] IS NULL) "
                params.extend(non_null_values)
            else:
                query += f"AND [{_escape_identifier(filter_col)}] IS NULL "
        else:
            query += f"AND [{_escape_identifier(filter_col)}] IN ({', '.join('?' for _ in filter_values)}) "
            params.extend(filter_values)

    for filter_col, text in text_filters.items():
        if not text:
            continue  # Skip empty text filters to avoid unnecessary conditions
        query += f"AND UPPER([{_escape_identifier(filter_col)}]) LIKE ? "
        params.append(f"%{text.upper()}%")

    query += " ORDER BY 1 COLLATE NOCASE"
    query += " LIMIT ?"
    params.append(page_size)

    return query, params


def get_row_count_query(
    table_name: str, select_filters: dict[str, list[str | int | float | bool | None]], text_filters: dict[str, str]
) -> tuple[str, list]:
    """
    Build a parameterized COUNT(*) SQL query for a table applying exact-match and case-insensitive substring filters.

    Parameters:
        table_name (str): Target table name; must be non-empty.
        select_filters (dict[str, list[str | int | float | bool | None]]): Mapping of column names to allowed exact-match values. Empty lists are skipped. If a filter list contains `None`, the function emits either:
            - `AND [col] IS NULL` when all values are `None`, or
            - `AND ([col] IN (?, ...) OR [col] IS NULL)` when there are both non-null values and `None`.
            Non-null values are appended to the parameter list in placeholder order.
        text_filters (dict[str, str]): Mapping of column names to substring filters; empty or falsy values are skipped. Each entry is rendered as `AND UPPER([col]) LIKE ?` with the parameter value `'%VALUE_UPPERCASE%'`.

    Returns:
        tuple[str, list]: (query, params) where `query` is the SQL string containing `?` placeholders and `params` is the ordered list of parameter values to bind.

    Raises:
        HTTPException: status 400 if `table_name` is missing or empty.
    """
    params = []

    if not table_name or table_name.strip() == "":
        raise HTTPException(status_code=400, detail="Table name must be specified")

    query = f"SELECT COUNT(*) FROM [{_escape_identifier(table_name)}] WHERE 1=1 "

    for filter_col, filter_values in select_filters.items():
        if not filter_values:
            continue  # Skip empty filter lists to avoid syntax errors in the SQL query
        if None in filter_values:
            non_null_values = [value for value in filter_values if value is not None]
            if non_null_values:
                query += f"AND ([{_escape_identifier(filter_col)}] IN ({', '.join('?' for _ in non_null_values)}) OR [{_escape_identifier(filter_col)}] IS NULL) "
                params.extend(non_null_values)
            else:
                query += f"AND [{_escape_identifier(filter_col)}] IS NULL "
        else:
            query += f"AND [{_escape_identifier(filter_col)}] IN ({', '.join('?' for _ in filter_values)}) "
            params.extend(filter_values)

    for filter_col, text in text_filters.items():
        if not text:
            continue  # Skip empty text filters to avoid unnecessary conditions
        query += f"AND UPPER([{_escape_identifier(filter_col)}]) LIKE ? "
        params.append(f"%{text.upper()}%")

    return query, params


def _escape_identifier(name: str) -> str:
    """
    Escape a SQLite bracket-quoted identifier by doubling any ']' characters.

    Parameters:
        name (str): Identifier to escape.

    Returns:
        str: The escaped identifier with each ']' replaced by ']]'.
    """
    return name.replace("]", "]]")
