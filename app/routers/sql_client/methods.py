from fastapi import HTTPException

from app.connection import sql_connection
from app.routers.models.methods import get_model_id_and_path
from app.routers.tables.queries import get_access_level as get_access_level_query

from . import queries as sql_client_queries


def get_sql_objects(cursor, user_email: str, model_name: str, project_name: str):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level, _ = cursor.execute(get_access_level_query, (model_id, user_email)).fetchone()
    if access_level not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="User does not have permission to get SQL objects")
    with sql_connection(model_id, model_path) as model_cursor:
        tables = []
        views = []
        all_rows = model_cursor.execute(sql_client_queries.get_sql_objects).fetchall()
        for obj_type, name in all_rows:
            if obj_type.lower() == "table":
                tables.append(name)
            elif obj_type.lower() == "view":
                views.append(name)
        return tables, views


def get_object_ddl(cursor, user_email: str, model_name: str, project_name: str, object_name: str):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level, _ = cursor.execute(get_access_level_query, (model_id, user_email)).fetchone()
    if access_level not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="User does not have permission to get object DDL")
    with sql_connection(model_id, model_path) as model_cursor:
        ddl_row = model_cursor.execute(sql_client_queries.get_object_ddl, (object_name,)).fetchone()
        if ddl_row is None:
            raise HTTPException(status_code=404, detail="Object not found")
        return ddl_row[0]


def execute_sql_query(cursor, user_email: str, model_name: str, project_name: str, query: str):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level, is_running = cursor.execute(get_access_level_query, (model_id, user_email)).fetchone()
    if access_level not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="User does not have permission to execute SQL queries")

    if is_running and query.strip().lower().startswith(("insert", "update", "delete", "create", "alter", "drop")):
        raise HTTPException(
            status_code=403, detail="Cannot execute modifying SQL query while a task using the model is running"
        )

    with sql_connection(model_id, model_path) as model_cursor:
        desc = ()
        try:
            desc = model_cursor.get_description(query)  # Check if query is valid and get column info
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error validating SQL query: {str(e)}")
        try:
            model_cursor.execute(query)
            if len(desc) == 0:
                count_changes = model_cursor.rowcount()
                if is_running and count_changes > 0:
                    raise HTTPException(
                        status_code=400, detail="Cannot execute modifying query while a task using the model is running"
                    )
                return {"type": "changes", "changes": count_changes, "columns": None, "rows": None}
            columns = [description[0] for description in desc]
            rows = model_cursor.fetchmany(5000)
            count_rows = len(rows)
            rows = [mask_blob_values(row) for row in rows]
            return {"columns": columns, "rows": rows, "type": "rows", "changes": count_rows}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error executing SQL query: {str(e)}")


def mask_blob_values(row):
    return tuple("<BLOB_DATA>" if isinstance(value, (bytes, bytearray, memoryview)) else value for value in row)


def get_sql_history(cursor, user_email: str, model_name: str, project_name: str):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level, _ = cursor.execute(get_access_level_query, (model_id, user_email)).fetchone()
    if access_level not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="User does not have permission to get SQL history")
    history_rows = cursor.execute(sql_client_queries.get_sql_history, (model_id, user_email)).fetchall()
    history = []
    for sql_query, is_errored, status, created_at in history_rows:
        history.append({"sql": sql_query, "is_errored": bool(is_errored), "status": status, "timestamp": created_at})
    return history


def add_sql_history(
    cursor, user_email: str, model_name: str, project_name: str, query: str, is_errored: bool, status: str
):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level, _ = cursor.execute(get_access_level_query, (model_id, user_email)).fetchone()
    if access_level not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="User does not have permission to add SQL history")
    cursor.execute(
        sql_client_queries.add_sql_history,
        (model_id, user_email, model_name, project_name, query, int(is_errored), status),
    )
