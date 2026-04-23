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

check_if_table_exists = (
    "select type from sqlite_master where type in ('table', 'view') collate nocase and name=? collate nocase"
)

add_new_column = "ALTER TABLE [{table_name}] ADD COLUMN [{column_name}] {column_type}"

check_if_table_column_exists = "SELECT 1 FROM pragma_table_xinfo(?) WHERE name = ? COLLATE NOCASE"

set_column_formatting = """UPDATE S_TableParameters Set ParameterType = ?, ParameterValue = ?
                            WHERE TableName = ? COLLATE NOCASE and ColumnName = ? COLLATE NOCASE RETURNING rowid"""

insert_column_formatting = """INSERT INTO S_TableParameters (TableName, ColumnName, ParameterType, ParameterValue)
                            VALUES (?, ?, ?, ?) RETURNING rowid"""

get_column_formatting = """SELECT ColumnName, ParameterType, ParameterValue FROM S_TableParameters
                            WHERE TableName = ? COLLATE NOCASE """


get_default_values_query = """select name, [dflt_value] from pragma_table_xinfo(?)
                              WHERE [dflt_value] is not null;"""

get_generated_columns = """select name from pragma_table_xinfo(?)
                              WHERE hidden in (2, 3);"""

operation_dict = {
    "gte": ">=",
    "lte": "<=",
    "eq": "=",
    "gt": ">",
    "lt": "<",
}


def get_table_query(
    table_name: str,
    column_names: list[str],
    select_filters: dict[str, list[str]],
    text_filters: dict[str, str],
    date_columns: list[str],
    numeric_filters: list[tuple[str, str, str | int | float]],
    sort_columns: list[list[str, str]],
    page_number: int,
    page_size: int,
) -> tuple[str, list]:
    """
    Builds a parameterized SQLite SELECT query for the given table and columns, applying exact-match filters, text/date-aware substring filters, sorting, and pagination.

    Parameters:
        table_name (str): Table name used in the FROM clause.
        column_names (list[str]): Columns to include in the SELECT; must contain at least one name.
        select_filters (dict[str, list[str]]): Exact-match filters mapping column -> list of allowed values. Empty lists are ignored. If a filter list contains `None` alongside other values the condition becomes `([col] IN (...) OR [col] IS NULL)`; if it contains only `None` the condition becomes `[col] IS NULL`.
        text_filters (dict[str, str]): Substring filters mapping column -> substring; falsy or empty values are ignored and non-empty values are bound as `%<text>%`. Columns listed in `date_columns` are filtered against `DATE([column] + julianday('1899-12-30'))`; all others use `LIKE ? COLLATE NOCASE`.
        date_columns (list[str]): Columns from `text_filters` that should be matched as dates after converting Excel-style serial values to SQLite dates.
        sort_columns (list[list[str, str]]): Sort directives as lists of `[column_name, direction]` where `direction` must be `'ASC'` or `'DESC'` (case-insensitive).
        page_number (int): 1-based page index used to compute OFFSET; must be greater than 0.
        page_size (int): Number of rows per page used for LIMIT; must be greater than 0.

    Returns:
        tuple[str, list]: A parameterized SQL query string using `?` placeholders and the ordered list of parameter values to bind.

    Raises:
        HTTPException: If `column_names` is empty, or if `page_size` or `page_number` is less than or equal to zero, or if a sort direction is invalid.
    """
    params = []

    if len(column_names) == 0:
        raise HTTPException(status_code=400, detail="At least one column must be specified")

    if page_size <= 0:
        raise HTTPException(status_code=400, detail="Page size must be greater than 0")

    if page_number <= 0:
        raise HTTPException(status_code=400, detail="Page number must be greater than 0")

    select_query = f"SELECT [{'], ['.join(col for col in column_names)}] FROM [{table_name}] WHERE 1=1 "

    for filter_col, filter_values in select_filters.items():
        if not filter_values:
            continue  # Skip empty filter lists to avoid syntax errors in the SQL query
        if None in filter_values:
            non_null_values = [value for value in filter_values if value is not None]
            if non_null_values:
                select_query += (
                    f"AND ([{filter_col}] IN ({', '.join('?' for _ in non_null_values)}) OR [{filter_col}] IS NULL) "
                )
                params.extend(non_null_values)
            else:
                select_query += f"AND [{filter_col}] IS NULL "
        else:
            select_query += f"AND [{filter_col}] IN ({', '.join('?' for _ in filter_values)}) "
            params.extend(filter_values)

    for column_name, text in text_filters.items():
        if not text:
            continue  # Skip empty text filters to avoid unnecessary conditions
        if column_name in date_columns:
            select_query += f"AND DATE([{column_name}] + julianday('1899-12-30')) LIKE ? "
        else:
            select_query += f"AND [{column_name}] LIKE ? COLLATE NOCASE "
        params.append(f"%{text}%")

    for column_name, operator, value in numeric_filters:
        if operator not in operation_dict:
            raise HTTPException(
                status_code=400, detail=f"Invalid operator '{operator}' for numeric filter on column '{column_name}'"
            )
        sql_operator = operation_dict[operator]
        select_query += f"AND [{column_name}] {sql_operator} ? "
        params.append(value)

    offset = (page_number - 1) * page_size
    if len(sort_columns) > 0:
        select_query += "ORDER BY "
    for column_name, direction in sort_columns:
        if direction.upper() not in ("ASC", "DESC"):
            raise HTTPException(
                status_code=400, detail=f"Invalid sort direction '{direction}' for column '{column_name}'"
            )
        select_query += f"[{column_name}] {direction.upper()}, "
    select_query = select_query.rstrip(", ")  # Remove trailing comma and space if sort_columns were added
    select_query += " LIMIT ? OFFSET ?"
    params.extend([page_size, offset])

    return select_query, params


def get_distinct_column_values_query(
    table_name: str,
    column_name: str,
    select_filters: dict[str, list[str | int | float | bool | None]],
    text_filters: dict[str, str],
    date_columns: list[str],
    numeric_filters: list[tuple[str, str, str | int | float]],
    page_size: int,
) -> tuple[str, list]:
    """
    Get distinct values of a single column from a table applying exact-match, text/date substring, and numeric filters, limited by page_size.
    
    Parameters:
        table_name (str): Table to query.
        column_name (str): Target column whose distinct values to return; must be non-empty.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters keyed by column. Empty lists are ignored. If a filter list contains `None` and also non-null values, the filter matches rows where the column is in the non-null list or is NULL; if the list contains only `None`, the filter matches NULL. Filters for `column_name` are ignored.
        text_filters (dict[str, str]): Substring filters keyed by column; falsy/empty values are ignored. Columns listed in `date_columns` are filtered against converted date strings, while all others use case-insensitive substring matching.
        date_columns (list[str]): Columns from `text_filters` that should be matched as dates after converting Excel-style serial values to SQLite dates.
        numeric_filters (list[tuple[str, str, str | int | float]]): Numeric comparisons as (column_name, operator, value); `operator` must be one of the keys in `operation_dict`.
        page_size (int): Maximum number of distinct values to return; must be greater than 0.
    
    Returns:
        tuple[str, list]: Parameterized SQL SELECT DISTINCT query (with `?` placeholders) and the ordered list of parameters; results are ordered case-insensitively and limited to `page_size`.
    
    Raises:
        HTTPException: If `column_name` is missing/blank, if `page_size <= 0`, or if a numeric filter `operator` is invalid.
    """
    params = []

    if not column_name or column_name.strip() == "":
        raise HTTPException(status_code=400, detail="Column name must be specified")

    if page_size <= 0:
        raise HTTPException(status_code=400, detail="Page size must be greater than 0")

    query = f"SELECT DISTINCT [{column_name}] FROM [{table_name}] WHERE 1=1 "

    for filter_col, filter_values in select_filters.items():
        if filter_col.upper() == column_name.upper():
            continue  # Skip filters on the target column for distinct values
        if not filter_values:
            continue  # Skip empty filter lists to avoid syntax errors in the SQL query
        if None in filter_values:
            non_null_values = [value for value in filter_values if value is not None]
            if non_null_values:
                query += (
                    f"AND ([{filter_col}] IN ({', '.join('?' for _ in non_null_values)}) OR [{filter_col}] IS NULL) "
                )
                params.extend(non_null_values)
            else:
                query += f"AND [{filter_col}] IS NULL "
        else:
            query += f"AND [{filter_col}] IN ({', '.join('?' for _ in filter_values)}) "
            params.extend(filter_values)

    for filter_col, text in text_filters.items():
        if not text:
            continue  # Skip empty text filters to avoid unnecessary conditions
        if filter_col in date_columns:
            query += f"AND DATE([{filter_col}] + julianday('1899-12-30')) LIKE ? "
        else:
            query += f"AND [{filter_col}] LIKE ? COLLATE NOCASE "
        params.append(f"%{text}%")

    for column_name, operator, value in numeric_filters:
        if operator not in operation_dict:
            raise HTTPException(
                status_code=400, detail=f"Invalid operator '{operator}' for numeric filter on column '{column_name}'"
            )
        sql_operator = operation_dict[operator]
        query += f"AND [{column_name}] {sql_operator} ? "
        params.append(value)

    query += " ORDER BY 1 COLLATE NOCASE"
    query += " LIMIT ?"
    params.append(page_size)

    return query, params


def get_row_count_query(
    table_name: str,
    select_filters: dict[str, list[str | int | float | bool | None]],
    text_filters: dict[str, str],
    date_columns: list[str],
    numeric_filters: list[tuple[str, str, str | int | float]],
) -> tuple[str, list]:
    """
    Build a parameterized COUNT(*) SQL query for a table applying exact-match (including nullable) and text/date-aware substring filters.

    Parameters:
        table_name (str): Target table name; must be non-empty.
        select_filters (dict[str, list[str | int | float | bool | None]]): Mapping of column names to allowed exact-match values. Empty lists are ignored. If a filter list contains `None`:
            - when all values are `None`, the query will filter for `IS NULL`;
            - when mixed with non-null values, the query will filter for `IN (...) OR IS NULL`.
            Non-null values are added to the returned parameter list in placeholder order.
        text_filters (dict[str, str]): Mapping of column names to substring filters; falsy or empty values are ignored. Columns listed in `date_columns` are filtered against converted date strings, while all others use case-insensitive substring matching.
        date_columns (list[str]): Columns from `text_filters` that should be matched as dates after converting Excel-style serial values to SQLite dates.

    Returns:
        tuple[str, list]: (query, params) where `query` is the SQL string with `?` placeholders and `params` is the ordered list of parameter values to bind.

    Raises:
        HTTPException: status 400 if `table_name` is missing or empty.
    """
    params = []

    if not table_name or table_name.strip() == "":
        raise HTTPException(status_code=400, detail="Table name must be specified")

    query = f"SELECT COUNT(*) FROM [{table_name}] WHERE 1=1 "

    for filter_col, filter_values in select_filters.items():
        if not filter_values:
            continue  # Skip empty filter lists to avoid syntax errors in the SQL query
        if None in filter_values:
            non_null_values = [value for value in filter_values if value is not None]
            if non_null_values:
                query += (
                    f"AND ([{filter_col}] IN ({', '.join('?' for _ in non_null_values)}) OR [{filter_col}] IS NULL) "
                )
                params.extend(non_null_values)
            else:
                query += f"AND [{filter_col}] IS NULL "
        else:
            query += f"AND [{filter_col}] IN ({', '.join('?' for _ in filter_values)}) "
            params.extend(filter_values)

    for filter_col, text in text_filters.items():
        if not text:
            continue  # Skip empty text filters to avoid unnecessary conditions
        if filter_col in date_columns:
            query += f"AND DATE([{filter_col}] + julianday('1899-12-30')) LIKE ? "
        else:
            query += f"AND [{filter_col}] LIKE ? COLLATE NOCASE "
        params.append(f"%{text}%")

    for column_name, operator, value in numeric_filters:
        if operator not in operation_dict:
            raise HTTPException(
                status_code=400, detail=f"Invalid operator '{operator}' for numeric filter on column '{column_name}'"
            )
        sql_operator = operation_dict[operator]
        query += f"AND [{column_name}] {sql_operator} ? "
        params.append(value)

    return query, params


def update_row(table_name, row_id, updates):
    """
    Builds a parameterized SQLite UPDATE statement that sets multiple columns for a row identified by `rowid`.

    Parameters:
        table_name (str): Name of the table to update.
        row_id: The `rowid` value of the row to update.
        updates (dict[str, Any]): Mapping of column names to new values; iteration order determines the parameter order.

    Returns:
        tuple[str, list]: SQL string with bracket-quoted identifiers and a list of parameters: the update values in iteration order followed by `row_id`.
    """
    params = []
    update_query = f"UPDATE [{table_name}] SET "
    if len(updates) == 0:
        raise HTTPException(status_code=400, detail="No columns provided for update")
    for column, value in updates.items():
        update_query += f"[{column}] = ?, "
        params.append(value)
    update_query = update_query.rstrip(", ")  # Remove trailing comma and space
    update_query += " WHERE rowid = ?"
    params.extend([row_id])
    return update_query, params


def update_rows(
    table_name, row_ids, column_name, column_value, select_filters, text_filters, date_columns, numeric_filters
):
    """
    Builds a parameterized UPDATE statement that sets a single column's value, optionally restricted by rowids and filters.
    
    Parameters:
        table_name (str): Table to update.
        row_ids (Sequence): Iterable of rowid values to restrict the update; if empty, no rowid restriction is applied (the update is constrained only by the provided filters).
        column_name (str): Name of the column to set.
        column_value: Value to bind for the column.
        select_filters (dict[str, list[str | int | float | bool | None]]): Exact-match filters where each key is a column name and each value is a list of allowed values. If a filter list contains None, the clause becomes `IN (...) OR IS NULL` when there are non-null values, or `IS NULL` when None is the only value.
        text_filters (dict[str, str]): Substring filters where each key is a column name and each value is the text to match; empty strings are ignored. For columns listed in `date_columns`, matching uses a date conversion (`DATE([col] + julianday('1899-12-30')) LIKE ?`); otherwise it uses `LIKE ? COLLATE NOCASE`.
        date_columns (list[str]): Column names (from text_filters) that should be matched as converted dates.
        numeric_filters (list[tuple[str, str, str | int | float]]): Numeric comparisons as tuples of (column_name, operator, value). `operator` must be a key in `operation_dict`; an invalid operator raises HTTPException(status_code=400).
    
    Returns:
        tuple[str, list]: The SQL UPDATE string with bracket-quoted identifiers and the ordered list of bound parameters.
    """
    params = []
    update_query = f"UPDATE [{table_name}] SET [{column_name}] = ? WHERE 1=1 "
    params.append(column_value)
    # Empty row_ids is intentional: it means update all rows (subject to select_filters/text_filters)
    if len(row_ids) > 0:
        update_query += f"AND rowid IN ({', '.join('?' for _ in row_ids)}) "
        params.extend(row_ids)

    for filter_col, filter_values in select_filters.items():
        if not filter_values:
            continue  # Skip empty filters to avoid unnecessary conditions
        if None in filter_values:
            non_null_values = [v for v in filter_values if v is not None]
            if non_null_values:
                update_query += (
                    f"AND ([{filter_col}] IN ({', '.join('?' for _ in non_null_values)}) OR [{filter_col}] IS NULL) "
                )
                params.extend(non_null_values)
            else:
                update_query += f"AND [{filter_col}] IS NULL "
        else:
            update_query += f"AND [{filter_col}] IN ({', '.join('?' for _ in filter_values)}) "
            params.extend(filter_values)

    for filter_col, text in text_filters.items():
        if not text:
            continue  # Skip empty text filters to avoid unnecessary conditions
        if filter_col in date_columns:
            update_query += f"AND DATE([{filter_col}] + julianday('1899-12-30')) LIKE ? "
        else:
            update_query += f"AND [{filter_col}] LIKE ? COLLATE NOCASE "
        params.append(f"%{text}%")

    for column_name, operator, value in numeric_filters:
        if operator not in operation_dict:
            raise HTTPException(
                status_code=400, detail=f"Invalid operator '{operator}' for numeric filter on column '{column_name}'"
            )
        sql_operator = operation_dict[operator]
        update_query += f"AND [{column_name}] {sql_operator} ? "
        params.append(value)

    return update_query, params


def delete_rows(table_name, row_ids, select_filters, text_filters, date_columns, numeric_filters):
    """
    Build a parameterized DELETE SQL statement for a table with optional rowid, exact-match (including NULL), text/date substring, and numeric filters.
    
    Parameters:
        table_name (str): Target table name inserted as a bracket-quoted identifier.
        row_ids (Sequence): If non-empty, restricts deletion to rows whose `rowid` is in this sequence; if empty, no rowid restriction is applied.
        select_filters (Mapping[str, Sequence]): Exact-match filters mapping column -> list of values. Empty lists are ignored. If a list contains `None` and other values, the condition becomes `([col] IN (...) OR [col] IS NULL)`; if the list contains only `None`, the condition becomes `[col] IS NULL`.
        text_filters (Mapping[str, str]): Substring filters mapping column -> text; falsy or empty values are ignored. For columns listed in `date_columns`, matches use `DATE([col] + julianday('1899-12-30')) LIKE ?`; otherwise matches use `LIKE ? COLLATE NOCASE`.
        date_columns (list[str]): Columns from `text_filters` that should be compared as converted Excel-style serial dates.
        numeric_filters (list[tuple[str, str, int | float | str]]): Numeric comparisons as tuples of `(column_name, operator_key, value)`. `operator_key` must be present in `operation_dict` or a 400 HTTPException is raised.
    
    Returns:
        tuple: `(query, params)` where `query` is the DELETE SQL with `?` placeholders and `params` is the list of bound values in order.
    """
    params = []
    delete_query = f"DELETE FROM [{table_name}] WHERE 1=1 "
    # Empty row_ids is intentional: it means delete all rows (subject to select_filters/text_filters)
    if len(row_ids) > 0:
        delete_query += f"AND rowid IN ({', '.join('?' for _ in row_ids)}) "
        params.extend(row_ids)

    for filter_col, filter_values in select_filters.items():
        if not filter_values:
            continue  # Skip empty filters to avoid unnecessary conditions
        if None in filter_values:
            non_null_values = [v for v in filter_values if v is not None]
            if non_null_values:
                delete_query += (
                    f"AND ([{filter_col}] IN ({', '.join('?' for _ in non_null_values)}) OR [{filter_col}] IS NULL) "
                )
                params.extend(non_null_values)
            else:
                delete_query += f"AND [{filter_col}] IS NULL "
        else:
            delete_query += f"AND [{filter_col}] IN ({', '.join('?' for _ in filter_values)}) "
            params.extend(filter_values)

    for filter_col, text in text_filters.items():
        if not text:
            continue  # Skip empty text filters to avoid unnecessary conditions
        if filter_col in date_columns:
            delete_query += f"AND DATE([{filter_col}] + julianday('1899-12-30')) LIKE ? "
        else:
            delete_query += f"AND [{filter_col}] LIKE ? COLLATE NOCASE "
        params.append(f"%{text}%")

    for column_name, operator, value in numeric_filters:
        if operator not in operation_dict:
            raise HTTPException(
                status_code=400, detail=f"Invalid operator '{operator}' for numeric filter on column '{column_name}'"
            )
        sql_operator = operation_dict[operator]
        delete_query += f"AND [{column_name}] {sql_operator} ? "
        params.append(value)

    return delete_query, params


def get_summary_stats_query(table_name, column_names, select_filters, text_filters, date_columns, numeric_filters):
    """
    Builds a parameterized SQL SELECT that returns aggregate statistics for the given columns, applying exact-match, text/date-aware substring, and numeric comparison filters.
    
    Parameters:
        table_name (str): Table to query.
        column_names (dict[str, str]): Mapping of column name -> aggregate function name (e.g., {"age": "MAX", "salary": "AVG"}).
        select_filters (dict[str, list]): Exact-match filters where each key is a column and the value is a list of allowed values; include `None` in the list to allow NULL values (combined as `IN (...) OR IS NULL` when mixed with non-null values).
        text_filters (dict[str, str]): Substring filters where each key is a column and the value is the text to match; columns listed in `date_columns` use date conversion before matching, others use case-insensitive `LIKE`.
        date_columns (list[str]): Columns from `text_filters` that should be compared as dates using `DATE([col] + julianday('1899-12-30'))`.
        numeric_filters (list[tuple[str, str, int | float | str]]): Numeric comparisons as tuples of `(column_name, operator_key, value)`. `operator_key` must be one of the keys in `operation_dict` (e.g., "gte", "lt").
    
    Returns:
        tuple[str, list]: The SQL query string and the ordered list of parameters to bind.
    
    Raises:
        HTTPException: If a numeric filter uses an operator not present in `operation_dict` (status code 400).
    """
    params = []
    stats_query = "SELECT "
    for column_name, stat in column_names.items():
        stats_query += f"{stat}([{column_name}]), "

    stats_query = stats_query.rstrip(", ")  # Remove trailing comma and space
    stats_query += f" FROM [{table_name}] WHERE 1=1 "

    for filter_col, filter_values in select_filters.items():
        if not filter_values:
            continue  # Skip empty filters to avoid unnecessary conditions
        if None in filter_values:
            non_null_values = [v for v in filter_values if v is not None]
            if non_null_values:
                stats_query += (
                    f"AND ([{filter_col}] IN ({', '.join('?' for _ in non_null_values)}) OR [{filter_col}] IS NULL) "
                )
                params.extend(non_null_values)
            else:
                stats_query += f"AND [{filter_col}] IS NULL "
        else:
            stats_query += f"AND [{filter_col}] IN ({', '.join('?' for _ in filter_values)}) "
            params.extend(filter_values)

    for filter_col, text in text_filters.items():
        if not text:
            continue  # Skip empty text filters to avoid unnecessary conditions
        if filter_col in date_columns:
            stats_query += f"AND DATE([{filter_col}] + julianday('1899-12-30')) LIKE ? "
        else:
            stats_query += f"AND [{filter_col}] LIKE ? COLLATE NOCASE "
        params.append(f"%{text}%")

    for column_name, operator, value in numeric_filters:
        if operator not in operation_dict:
            raise HTTPException(
                status_code=400, detail=f"Invalid operator '{operator}' for numeric filter on column '{column_name}'"
            )
        sql_operator = operation_dict[operator]
        stats_query += f"AND [{column_name}] {sql_operator} ? "
        params.append(value)

    return stats_query, params


def add_row(table_name, values, generated_columns):
    """
    Builds a parameterized INSERT statement for the given table using only non-null values.

    Parameters:
        table_name (str): Target table name.
        values (dict): Mapping of column names to values; entries with value `None` are omitted from the INSERT.

    Returns:
        tuple: `(insert_query, params)` where `insert_query` is the SQL INSERT string with `?` placeholders and `params` is the list of bound values in the same column order.

    Raises:
        HTTPException: status 400 if no non-null values are provided.
    """
    params = []
    column_names = [col for col in values.keys() if values[col] is not None]
    if len(column_names) == 0:
        raise HTTPException(status_code=400, detail="At least one non-null value must be provided to add a row")
    column_names = [col for col in column_names if col.lower() not in generated_columns]
    if len(column_names) == 0:
        raise HTTPException(
            status_code=400, detail="No valid columns provided for new row after excluding generated columns"
        )
    columns = ", ".join(f"[{col}]" for col in column_names)
    placeholders = ", ".join("?" for _ in column_names)
    insert_query = f"INSERT INTO [{table_name}] ({columns}) VALUES ({placeholders})"
    params.extend(values[col] for col in column_names)
    if len(params) == 0:
        raise HTTPException(status_code=400, detail="At least one non-null value must be provided to add a row")
    return insert_query, params


def get_excel_upload_insert_query(table_name, column_names, default_values):
    """
    Prepare companion DELETE and INSERT SQL statements for bulk uploading Excel rows into a table.

    Builds:
    - A DELETE statement to remove all rows from the target table.
    - An INSERT statement for the provided columns using `?` placeholders for parameter binding; for any column present in `default_values` whose string form does not contain `;`, the corresponding placeholder is wrapped as `COALESCE(?, <default>)` so a bound NULL will fall back to the SQL literal default.

    Parameters:
        table_name (str): Target table name.
        column_names (list[str]): Ordered list of column names to insert; must contain at least one column.
        default_values (dict): Mapping of column names to SQL literal defaults (used when present and safe to inline).

    Returns:
        tuple[str, str]: `(delete_query, insert_query)` where `delete_query` is `DELETE FROM [table_name]` and `insert_query` is `INSERT INTO [table_name] ([col...]) VALUES (...)`.

    Raises:
        fastapi.HTTPException: Raised with status code 400 if `column_names` is empty.
    """
    if len(column_names) == 0:
        raise HTTPException(status_code=400, detail="At least one column must be specified for Excel upload")
    columns = ", ".join(f"[{col}]" for col in column_names)
    placeholders = ""
    for column_name in column_names:
        if column_name in default_values and ";" not in str(default_values[column_name]):
            placeholders += f"COALESCE(?, {default_values[column_name]}), "
        else:
            placeholders += "?, "
    placeholders = placeholders.rstrip(", ")
    insert_query = f"INSERT INTO [{table_name}] ({columns}) VALUES ({placeholders})"
    delete_query = f"DELETE FROM [{table_name}]"
    return delete_query, insert_query
