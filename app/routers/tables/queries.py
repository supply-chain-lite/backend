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
    """
    Builds a parameterized SQLite SELECT query for a table with optional exact-match and case-insensitive text filters, and applies pagination.
    
    Parameters:
    	table_name (str): Table name to query.
    	column_names (list[str]): Columns to select; must contain at least one name.
    	select_filters (dict[str, list[str]]): Exact-match filters where each key is a column name and the value is a list of allowed values; each list element becomes a `?` placeholder inside an `IN (...)` predicate.
    	text_filters (dict[str, str]): Case-insensitive substring filters where each key is a column name and the value is the substring to match (translated to `UPPER(column) LIKE ?` with surrounding `%`).
    	page_number (int): 1-based page index used to compute OFFSET.
    	page_size (int): Number of rows per page used for LIMIT.
    
    Returns:
    	tuple[str, list]: A tuple of the SQL query string (with `?` placeholders) and the ordered list of parameters to bind.
    
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
    """
    Builds a parameterized SQL query to retrieve distinct values of a single column with optional exact-match and case-insensitive substring filters and a result limit.
    
    Parameters:
        table_name (str): Name of the table to query.
        column_name (str): Name of the column whose distinct values to return.
        select_filters (dict[str, list[str]]): Mapping of column names to lists of allowed exact-match values; each entry is rendered as `AND [col] IN (?, ..., ?)`.
        text_filters (dict[str, str]): Mapping of column names to substring filters; each entry is rendered as `AND UPPER([col]) LIKE ?` with the filter value wrapped as `%VALUE%` and upper-cased.
        page_size (int): Maximum number of distinct values to return (applied as `LIMIT`).
    
    Returns:
        tuple[str, list]: A pair where the first element is the SQL query string (with `?` parameter placeholders) and the second element is the ordered list of parameter values to bind to the query.
    
    Raises:
        HTTPException: status 400 if `column_name` is missing/empty or if `page_size` is not greater than 0.
    """
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
    """
    Escape a SQLite bracket-quoted identifier by doubling any ']' characters.
    
    Parameters:
        name (str): Identifier to escape.
    
    Returns:
        str: The escaped identifier with each ']' replaced by ']]'.
    """
    return name.replace("]", "]]")
