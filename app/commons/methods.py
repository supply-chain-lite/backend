from . import queries as queries


def get_table_groups(cursor):
    """
    Builds a mapping from group name to a list of (table_name, table_display_name) tuples.

    Parameters:
        cursor: Database cursor used to execute queries that retrieve table grouping information.

    Returns:
        dict: Keys are group_name (str); values are lists of (table_name, table_display_name) tuples.
    """
    try:
        rows = cursor.execute(queries.get_table_groups).fetchall()
    except Exception:
        rows = cursor.execute(queries.get_table_group_from_sqlite_master).fetchall()
    table_groups = {}
    for group_name, table_name, table_display_name, _ in rows:
        if table_display_name is None:
            table_display_name = table_name
        if group_name not in table_groups:
            table_groups[group_name] = []
        table_groups[group_name].append((table_name, table_display_name))
    return table_groups
