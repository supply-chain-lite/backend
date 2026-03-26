from fastapi import HTTPException

from . import queries as project_queries


def get_current_project(cursor, user_email: str):
    row = cursor.execute(project_queries.get_current_project, (user_email,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active project found for the user")
    return row[0]


def add_new_project(cursor, user_email: str, project_name: str, open_after_create: bool):
    if project_name is None or project_name.strip() == "":
        raise HTTPException(status_code=400, detail="Project name cannot be empty")
    project_id = _get_project_id(cursor, user_email, project_name)
    if project_id:
        raise HTTPException(status_code=400, detail="Project name already exists")
    row = cursor.execute(project_queries.insert_new_project, (user_email, project_name)).fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create project")
    if open_after_create:
        cursor.execute(project_queries.set_project_status, (user_email, user_email, project_name))
    return


def open_project(cursor, user_email: str, project_name: str):
    project_id = _get_project_id(cursor, user_email, project_name)
    if not project_id:
        raise HTTPException(status_code=404, detail="Project not found")
    cursor.execute(project_queries.set_project_status, (user_email, user_email, project_name))
    return project_name


def delete_project(cursor, user_email: str, project_name: str):
    if project_name == "Default":
        raise HTTPException(status_code=400, detail="Default project cannot be deleted")
    project_id = _get_project_id(cursor, user_email, project_name)
    if not project_id:
        raise HTTPException(status_code=404, detail="Project not found")

    all_models = cursor.execute(project_queries.get_project_models, (user_email, project_name)).fetchall()
    for (model_name,) in all_models:
        pass
        # delete_model(cursor, user_email, project_name, model_name)

    cursor.execute(project_queries.delete_project, (user_email, project_name))
    row = cursor.execute(project_queries.get_current_project, (user_email,)).fetchone()
    if not row:
        open_project(cursor, user_email, "Default")
    return


def rename_project(cursor, user_email: str, old_project_name: str, new_project_name: str):
    if new_project_name is None or new_project_name.strip() == "":
        raise HTTPException(status_code=400, detail="New project name cannot be empty")
    project_id = _get_project_id(cursor, user_email, old_project_name)
    if not project_id:
        raise HTTPException(status_code=404, detail="Project not found")

    new_project_id = _get_project_id(cursor, user_email, new_project_name)
    if new_project_id:
        raise HTTPException(status_code=400, detail="New project name must be different.")

    cursor.execute(project_queries.rename_project, (new_project_name, user_email, old_project_name))
    project_id_ = _get_project_id(cursor, user_email, new_project_name)
    if not project_id_:
        raise HTTPException(status_code=500, detail="Project name not updated.")
    return


def list_projects(cursor, user_email: str):
    rows = cursor.execute(project_queries.list_user_projects, (user_email,)).fetchall()
    return [row[0] for row in rows]


def _get_project_id(cursor, user_email: str, project_name: str):
    row = cursor.execute(project_queries.get_project_id, (user_email, project_name)).fetchone()
    return row[0] if row else None
