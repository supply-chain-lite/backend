from . import queries as queries


def get_table_groups(cursor):
    try:
        rows = cursor.execute(queries.get_table_groups).fetchall()
    except Exception:
        rows = cursor.execute(queries.get_table_group_from_sqlite_master).fetchall()
    table_groups = {}
    for group_name, table_name, table_display_name, _ in rows:
        if group_name not in table_groups:
            table_groups[group_name] = []
        table_groups[group_name].append((table_name, table_display_name))
    return table_groups
