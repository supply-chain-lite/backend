from . import queries as queries


def get_table_groups(cursor):
    """
    Create a dictionary mapping each group name to a list of (table_name, table_display_name) tuples.

    Parameters:
        cursor: Database cursor used to execute queries that retrieve table grouping information.

    Returns:
        dict: Mapping where keys are group_name (str) and values are lists of tuples (table_name (str), table_display_name (str)). If a row's display name is None, the display name is replaced with the table_name.
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
