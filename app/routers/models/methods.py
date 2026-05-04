import json
import os
import shutil
import sqlite3
import tempfile
import uuid

import apsw
from fastapi import File, HTTPException, UploadFile, responses

from app.commons.methods import get_table_groups as _get_table_groups
from app.config import BACKUP_FOLDER, DATA_FOLDER, MAX_BACKUPS, TEMP_FOLDER
from app.connection import remove_connection_object, sql_connection

from . import queries as model_queries


def add_new_model(
    cursor, model_name: str, project_name: str, user_name: str, template_name: str, with_sample_data: bool
):

    project_id = get_project_id(cursor, user_name, project_name)

    model_id, _ = get_model_id_and_path(cursor, model_name, project_name, user_name)
    if model_id:
        raise HTTPException(status_code=400, detail="Model already exists in project for user")

    template_sql_file = get_template_sql_file(cursor, user_name, template_name, with_sample_data)

    db_uid = str(uuid.uuid4())
    db_path = os.path.join(DATA_FOLDER, f"{db_uid}.sqlite3")
    if os.path.exists(db_path):
        raise HTTPException(status_code=400, detail="Model with same UID already exists")
    with sqlite3.connect(db_path) as model_db:
        with open(template_sql_file, "r") as f:
            model_db.executescript(f.read())

    role = "owner"
    model_id = cursor.execute(model_queries.insert_models, (db_uid, db_path, user_name, template_name)).fetchone()[0]
    cursor.execute(
        model_queries.insert_user_models,
        (model_id, user_name, project_id, role, model_name),
    )


def move_model_to_project(
    cursor,
    user_email: str,
    model_name: str,
    old_project_name: str,
    new_project_name: str,
) -> int:
    old_model_id, _ = get_model_id_and_path(cursor, model_name, old_project_name, user_email)
    if not old_model_id:
        raise HTTPException(status_code=404, detail="Model not found in the old project")

    new_model_id, _ = get_model_id_and_path(cursor, model_name, new_project_name, user_email)
    if new_model_id:
        raise HTTPException(status_code=400, detail="Model already exists in the new project")

    new_project_id = get_project_id(cursor, user_email, new_project_name)

    old_project_id = get_project_id(cursor, user_email, old_project_name)

    row = cursor.execute(
        model_queries.update_user_model_project,
        (new_project_id, old_model_id, user_email, old_project_id),
    ).fetchone()

    if not row:
        raise HTTPException(status_code=400, detail="Failed to move model to new project")

    return 1


def get_model_templates(cursor, user_email: str):
    rows = cursor.execute(model_queries.get_model_templates, (user_email,)).fetchall()
    return [row[0] for row in rows]


def get_user_models_by_project(cursor, user_email: str):
    rows = cursor.execute(model_queries.get_user_models_by_project, (user_email,)).fetchall()
    models_by_project = {}
    for project_name, model_name, access_level in rows:
        if project_name not in models_by_project:
            models_by_project[project_name] = {}
        if model_name is not None:
            models_by_project[project_name][model_name] = access_level
    return models_by_project


def save_as_model(
    cursor,
    user_email: str,
    model_name: str,
    project_name: str,
    new_model_name: str,
    new_project_name: str,
    new_user_email: str,
):

    old_model_id, old_model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not old_model_id:
        raise HTTPException(status_code=404, detail="Model not found in the old project")

    new_model_id, new_model_path = get_model_id_and_path(cursor, new_model_name, new_project_name, new_user_email)
    if new_model_id:
        raise HTTPException(status_code=400, detail="Model already exists in the new project")

    template_name = cursor.execute(model_queries.get_template_name, (old_model_id,)).fetchone()[0]

    db_uid = str(uuid.uuid4())
    new_model_path = os.path.join(DATA_FOLDER, f"{db_uid}.sqlite3")
    if os.path.exists(new_model_path):
        raise HTTPException(status_code=400, detail="Model with same UID already exists")

    new_project_id = get_project_id(cursor, new_user_email, new_project_name)

    role = "owner"
    model_id = cursor.execute(
        model_queries.insert_models,
        (db_uid, new_model_path, new_user_email, template_name),
    ).fetchone()[0]
    cursor.execute(
        model_queries.insert_user_models,
        (model_id, new_user_email, new_project_id, role, new_model_name),
    )

    if model_id:
        connection = apsw.Connection(old_model_path)
        try:
            connection.execute(f"VACUUM INTO '{new_model_path}'")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to copy model database: {str(e)}")
        finally:
            connection.close()
        return 1
    raise HTTPException(status_code=500, detail="Failed to create new model")


def rename_model(cursor, user_email: str, model_name: str, project_name: str, new_model_name: str):
    model_id, _ = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    existing_model_id, _ = get_model_id_and_path(cursor, new_model_name, project_name, user_email)
    if existing_model_id:
        raise HTTPException(status_code=400, detail="Model with the new name already exists")

    cursor.execute(model_queries.rename_model, (new_model_name, model_id, user_email))
    return 1


def delete_model(cursor, user_email: str, model_name: str, project_name: str):
    """
    Delete a model or, if the caller is not the owner, remove the caller's association with the model.

    Parameters:
        cursor: Database cursor used to execute queries.
        user_email (str): Email of the requesting user (used to determine access and associations).
        model_name (str): Name of the model to delete.
        project_name (str): Name of the project the model belongs to.

    Returns:
        int: `1` on successful deletion or successful removal of the user's association.

    Raises:
        fastapi.HTTPException: 404 if the specified model cannot be found.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(model_queries.get_access_level, (model_id, user_email)).fetchone()[0]
    if access_level != "owner":
        cursor.execute(model_queries.delete_user_model, (model_id, user_email))
        return 1

    cursor.executescript(model_queries.delete_model_for_all_users, (model_id, model_id))

    conn = sqlite3.connect(model_path)
    conn.close()

    if os.path.exists(model_path):
        os.remove(model_path)

    all_backups = cursor.execute(model_queries.get_model_backups, (model_id,)).fetchall()
    for backup in all_backups:
        backup_path = backup[0]
        if os.path.exists(backup_path):
            os.remove(backup_path)
    cursor.execute(model_queries.delete_model_backup, (model_id, "NA"))
    remove_connection_object(model_id)

    return 1


def create_model_backup(cursor, user_email: str, model_name: str, project_name: str, backup_comment: str):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(model_queries.get_access_level, (model_id, user_email)).fetchone()[0]

    if access_level != "owner":
        raise HTTPException(status_code=403, detail="Only owner can create backup")

    all_backups = cursor.execute(model_queries.get_model_backups, (model_id,)).fetchall()

    if len(all_backups) >= MAX_BACKUPS:
        oldest_backup_path = all_backups[0][0]
        if os.path.exists(oldest_backup_path):
            os.remove(oldest_backup_path)
        cursor.execute(model_queries.delete_model_backup, ("NA", oldest_backup_path))

    backup_uid = str(uuid.uuid4())
    backup_path = os.path.join(BACKUP_FOLDER, f"{backup_uid}.sqlite3")
    if os.path.exists(backup_path):
        raise HTTPException(status_code=500, detail="Backup with same UID already exists")

    connection = apsw.Connection(model_path)
    try:
        connection.execute(f"VACUUM INTO '{backup_path}'")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create backup: {str(e)}")
    finally:
        connection.close()

    cursor.execute(
        "INSERT INTO S_ModelBackups (ModelId, BackupPath, BackupText) VALUES (?, ?, ?)",
        (model_id, backup_path, backup_comment),
    )


def get_model_backups(cursor, user_email: str, model_name: str, project_name: str):
    model_id, _ = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(model_queries.get_access_level, (model_id, user_email)).fetchone()[0]

    if access_level != "owner":
        raise HTTPException(status_code=403, detail="Only owner can get backups")

    all_backups = cursor.execute(model_queries.get_model_backup_details, (model_id,)).fetchall()

    return all_backups


def restore_model_from_backup(cursor, user_email: str, model_name: str, project_name: str, backup_id: int):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(model_queries.get_access_level, (model_id, user_email)).fetchone()[0]

    if access_level != "owner":
        raise HTTPException(status_code=403, detail="Only owner can restore from backup")

    backup_row = cursor.execute(model_queries.get_model_backup_path, (backup_id, model_id)).fetchone()
    if not backup_row:
        raise HTTPException(status_code=404, detail="Backup not found")

    backup_path = backup_row[0]

    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="Backup file not found on disk")

    backup_connection = apsw.Connection(backup_path)
    this_connection = apsw.Connection(model_path)

    try:
        with this_connection.backup("main", backup_connection, "main") as backup:
            backup.step()  # copy entire database in one step
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore backup: {str(e)}")
    finally:
        this_connection.close()
        backup_connection.close()


def share_model(
    cursor,
    from_user_email: str,
    to_user_email: str,
    model_name: str,
    project_name: str,
    access_level: str,
):
    """
    Create and send a model share request by inserting a notification for the target user.

    Parameters:
        cursor: Database cursor used to perform queries and insert the notification.
        from_user_email (str): Email of the user sharing the model (must be the owner).
        to_user_email (str): Email of the recipient user to receive the share request.
        model_name (str): Name of the model to be shared.
        project_name (str): Name of the project containing the model.
        access_level (str): Access level being requested for the recipient (e.g., "viewer", "editor").

    Raises:
        HTTPException 400: If attempting to share to self, if the recipient already has access,
            or if an identical share request was already sent.
        HTTPException 403: If the sharer is not the owner of the model.
        HTTPException 404: If the target user or the specified model cannot be found.
        HTTPException 500: If creating the notification record fails.
    """
    if from_user_email == to_user_email:
        raise HTTPException(status_code=400, detail="Cannot share model with yourself")
    if not cursor.execute(model_queries.check_user_email, (to_user_email,)).fetchone():
        raise HTTPException(status_code=404, detail="Target user not found")
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, from_user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    from_user_access_level = cursor.execute(model_queries.get_access_level, (model_id, from_user_email)).fetchone()[0]

    if from_user_access_level != "owner":
        raise HTTPException(status_code=403, detail="Only owner can share the model")

    row = cursor.execute(model_queries.get_access_level, (model_id, to_user_email)).fetchone()
    if row:
        raise HTTPException(status_code=400, detail="Model already shared with the user")

    row = cursor.execute(
        model_queries.check_if_model_shared_with_user, (to_user_email, from_user_email, model_id)
    ).fetchone()
    if row:
        raise HTTPException(status_code=400, detail="Model share request already sent to the user")

    notification_data = {
        "model_id": model_id,
        "model_name": model_name,
        "project_name": project_name,
        "access_level": access_level,
    }
    title = "Model Share Request"
    message = f"{from_user_email} wants to share the model '{model_name}' in project "
    message = f"{message}'{project_name}' with you. Do you accept?"
    notification_type = "model_share_request"
    notifications = cursor.execute(
        model_queries.add_user_notifications,
        (
            from_user_email,
            to_user_email,
            title,
            message,
            notification_type,
            json.dumps(notification_data),
        ),
    ).fetchone()
    if not notifications:
        raise HTTPException(status_code=500, detail="Failed to create notification for model share")


def read_notification(cursor, notification_id: int, user_email: str):
    cursor.execute(model_queries.read_notification, (notification_id, user_email))


def accept_model_share(
    cursor,
    notification_id: int,
    accept: bool,
    new_model_name: str,
    new_project_name: str,
    create_copy: bool = False,
    user_email: str = "",
):
    """
    Handle a share notification by accepting or rejecting a model-share request.

    When accepted, either create a copy of the shared model for the recipient or associate the existing model with the recipient's project and access level; when rejected, mark the notification as rejected.

    Parameters:
        notification_id (int): ID of the notification to process.
        accept (bool): If False, mark the notification as rejected; if True, process acceptance.
        new_model_name (str): Destination model name to use when creating a copy or adding the shared model to the recipient's project.
        new_project_name (str): Destination project name for the new or associated model.
        create_copy (bool): If True, create a new copy of the shared model for the recipient; if False, grant access to the existing model.
        user_email (str): Email of the user accepting or rejecting the share.

    Raises:
        HTTPException(status_code=404): If the notification or the shared model cannot be found.
        HTTPException(status_code=400): If the model ID in the notification does not match the source model, if the recipient already has access to the model, or if the recipient already has a model with the same name in the target project.
        HTTPException(status_code=500): Propagated from underlying operations (e.g., model copy) when those fail.
    """
    notification_row = cursor.execute(model_queries.get_notification_params, (notification_id, user_email)).fetchone()
    if not notification_row:
        raise HTTPException(status_code=404, detail=f"Notification not found; {user_email}, {notification_id}")

    if not accept:
        cursor.execute(model_queries.accept_notification, (-1, notification_id, user_email))
        return

    from_user_email = notification_row[0]
    notification_params = json.loads(notification_row[1])
    model_id = notification_params.get("model_id")
    model_name = notification_params.get("model_name")
    project_name = notification_params.get("project_name")
    access_level = notification_params.get("access_level")

    old_model_id, _ = get_model_id_and_path(cursor, model_name, project_name, from_user_email)

    if not old_model_id:
        raise HTTPException(status_code=404, detail="Model not found for sharing")

    if old_model_id != model_id:
        raise HTTPException(status_code=400, detail="Model ID mismatch")

    row = cursor.execute(model_queries.get_access_level, (old_model_id, user_email)).fetchone()
    if row:
        raise HTTPException(status_code=400, detail="Model already shared with the user")

    if create_copy:
        save_as_model(
            cursor,
            from_user_email,
            model_name,
            project_name,
            new_model_name,
            new_project_name,
            user_email,
        )
    else:
        project_id = get_project_id(cursor, user_email, new_project_name)
        new_model_id, _ = get_model_id_and_path(cursor, new_model_name, new_project_name, user_email)
        if new_model_id:
            raise HTTPException(status_code=400, detail="User already has a model with the same name in the project")
        cursor.execute(
            model_queries.insert_user_models,
            (model_id, user_email, project_id, access_level, new_model_name),
        )
    cursor.execute(model_queries.accept_notification, (1, notification_id, user_email))


def get_user_notifications(cursor, user_email: str):
    rows = cursor.execute(model_queries.get_user_notifications, (user_email, user_email)).fetchall()
    notifications = []
    for (
        notification_id,
        from_user_email,
        title,
        message,
        notification_type,
        params,
        is_read,
        is_accepted,
    ) in rows:
        params_dict = json.loads(params) if params else {}
        project_name = params_dict.get("project_name")
        model_name = params_dict.get("model_name")

        notifications.append(
            {
                "notification_id": notification_id,
                "from_user_email": from_user_email,
                "title": title,
                "message": message,
                "notification_type": notification_type,
                "project_name": project_name,
                "model_name": model_name,
                "is_read": is_read,
                "is_accepted": is_accepted,
            }
        )
    return notifications


def download_model(cursor, user_email: str, model_name: str, project_name: str):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(model_queries.get_access_level, (model_id, user_email)).fetchone()[0]

    if access_level not in ["owner", "editor"]:
        raise HTTPException(status_code=403, detail="Only owner and editor can download the model")

    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail="Model file not found on disk")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db", dir=TEMP_FOLDER)
    tmp.close()  # Close the file so that it can be used by other processes

    connection = apsw.Connection(model_path)
    try:
        connection.execute(f"VACUUM INTO '{tmp.name}'")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create a copy of the model for download: {str(e)}")
    finally:
        connection.close()

    # 3. Return file
    return responses.FileResponse(
        path=tmp.name,
        filename=f"{model_name}.db",
        media_type="application/octet-stream",
    )


def upload_model(
    cursor,
    user_email: str,
    project_name: str,
    model_name: str,
    model_file: UploadFile = File(...),
):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(model_queries.get_access_level, (model_id, user_email)).fetchone()[0]

    if access_level not in ["owner", "editor"]:
        raise HTTPException(status_code=403, detail="Only owner and editor can upload the model")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db", dir=TEMP_FOLDER)
    tmp.close()

    with open(tmp.name, "wb") as buffer:
        shutil.copyfileobj(model_file.file, buffer)

    backup_connection = apsw.Connection(tmp.name)
    this_connection = apsw.Connection(model_path)

    try:
        with this_connection.backup("main", backup_connection, "main") as backup:
            backup.step()  # copy entire database in one step
    finally:
        this_connection.close()
        backup_connection.close()


def update_model_access_level(cursor, user_email: str, model_name: str, project_name: str, access_list: list):
    model_id, _ = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    from_user_access_level = cursor.execute(model_queries.get_access_level, (model_id, user_email)).fetchone()[0]

    if from_user_access_level != "owner":
        raise HTTPException(status_code=403, detail="Only owner can update access level")

    for access_user, access_level in access_list:
        if access_user == user_email:
            continue
        if access_level == "delete":
            count = cursor.execute(model_queries.delete_user_model, (model_id, access_user)).fetchall()
            if len(count) == 0:
                count = cursor.execute(
                    model_queries.update_access_request_notification, (-1, "Revoked", access_user, model_id)
                ).fetchall()
                if len(count) == 0:
                    raise HTTPException(status_code=400, detail="Failed to revoke access and update notification")
        else:
            if access_level not in ["read", "write", "execute", "admin"]:
                raise HTTPException(status_code=400, detail="Invalid access level")
            count = cursor.execute(
                model_queries.update_user_access_level,
                (access_level, model_id, access_user),
            ).fetchall()
            if len(count) == 0:
                count = cursor.execute(
                    model_queries.update_access_request_notification, (0, access_level, access_user, model_id)
                ).fetchall()
                if len(count) == 0:
                    raise HTTPException(status_code=400, detail="Failed to update access request notification")


# added
def get_all_user_emails(cursor, user_email: str):
    rows = cursor.execute(model_queries.fetch_all_user_emails, (user_email,)).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No users Found")

    return [row[0] for row in rows]


# Common functions, not exposed as an endpoint


def get_project_id(cursor, user_name: str, project_name: str):
    row = cursor.execute(model_queries.get_project_id, (user_name, project_name)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project does not exist for user")
    return row[0]


def get_model_id_and_path(cursor, model_name: str, project_name: str, user_name: str):
    if model_name.strip() == "" or project_name.strip() == "":
        raise HTTPException(status_code=400, detail="Model name and project name cannot be empty")

    row = cursor.execute(model_queries.get_model_id_and_path, (project_name, model_name, user_name)).fetchone()
    if row:
        return row[0], row[1]
    return None, None


def get_template_sql_file(cursor, user_email: str, template_name: str, with_data: bool = False):
    """
    Return the filesystem path to the SQL template file for a given template name.

    Parameters:
        user_email (str): Email of the user requesting the template (used to check template access).
        template_name (str): Name of the template to locate.
        with_data (bool): If True, select the template that includes sample data SQL; otherwise select the schema-only SQL.

    Returns:
        sql_file (str): Absolute filesystem path to the requested SQL file.

    Raises:
        HTTPException: 403 if the user does not have access to the template.
        HTTPException: 404 if the template record or the SQL file cannot be found on disk.
    """
    all_templates = get_model_templates(cursor, user_email)
    if template_name not in all_templates:
        raise HTTPException(status_code=403, detail="User dont have access to the template")

    column_name = "TemplateWithDataSQL" if with_data else "TemplateSQL"
    this_query = model_queries.get_template_sql_file.format(column_name=column_name)
    row = cursor.execute(this_query, (template_name,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Template not found")

    file_name = row[0]
    this_parent_dir = os.path.dirname(os.path.abspath(__file__))
    this_parent_dir = os.path.dirname(this_parent_dir)
    this_parent_dir = os.path.dirname(this_parent_dir)
    schema_dir = os.path.join(this_parent_dir, "schemas")

    sql_file = os.path.join(schema_dir, file_name)
    if not os.path.isfile(sql_file):
        raise HTTPException(status_code=404, detail="SQL file for template not found")

    return sql_file


def get_table_groups(cursor, user_email: str, model_name: str, project_name: str):
    """
    Retrieve table groups and their metadata for the specified model.

    Returns:
        table_groups: A data structure describing groups of tables and their associated metadata for the model.

    Raises:
        HTTPException: Raised with status_code=404 when the specified model cannot be found.
    """
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    with sql_connection(model_id, model_path) as model_cursor:
        table_groups = _get_table_groups(model_cursor)

    return table_groups


def _clean_up_temp_file(file_path: str):
    """
    Remove a temporary file at the given path if it exists.

    Parameters:
        file_path (str): Path to the temporary file to remove. If the file does not exist, the function does nothing.
    """
    if os.path.exists(file_path):
        os.remove(file_path)


def vacuum_model(cursor, user_email: str, model_name: str, project_name: str):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(model_queries.get_access_level, (model_id, user_email)).fetchone()[0]

    if access_level != "owner":
        raise HTTPException(status_code=403, detail="Only owner can vacuum the model")

    connection = apsw.Connection(model_path)
    connection.execute("VACUUM")
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()


def get_model_info(cursor, user_email: str, model_name: str, project_name: str):
    model_id, _ = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    access_level = cursor.execute(model_queries.get_access_level, (model_id, user_email)).fetchone()[0]

    owner_email, template_name = cursor.execute(model_queries.get_model_info, (model_id,)).fetchone()

    owner_model_name, owner_project_name = cursor.execute(
        model_queries.get_model_name_and_project_name, (model_id, owner_email)
    ).fetchone()

    access_user_list = []
    if owner_email == user_email:
        for user_id, user_access_level in cursor.execute(
            model_queries.get_users_for_model, (model_id, owner_email)
        ).fetchall():
            access_user_list.append({"user_email": user_id, "access_level": user_access_level, "accepted": "Yes"})

        for user_id, user_access_level in cursor.execute(
            model_queries.get_access_requests_for_model, (owner_email, model_id)
        ).fetchall():
            access_user_list.append({"user_email": user_id, "access_level": user_access_level, "accepted": "No"})

    return {
        "model_name": model_name,
        "project_name": project_name,
        "access_level": access_level,
        "owner_email": owner_email,
        "template_name": template_name,
        "access_user_list": access_user_list,
        "owner_model_name": owner_model_name,
        "owner_project_name": owner_project_name,
    }


def get_files_list(cursor, user_email: str, model_name: str, project_name: str):
    model_id, model_path = get_model_id_and_path(cursor, model_name, project_name, user_email)
    if not model_id:
        raise HTTPException(status_code=404, detail="Model not found")

    with sql_connection(model_id, model_path) as model_cursor:
        try:
            rows = model_cursor.execute(model_queries.get_data_files).fetchall()
        except Exception:
            return []
    files = []
    for file_id, file_name, file_type, file_extension, uploaded_file_name, last_updated, file_exists in rows:
        files.append(
            {
                "file_id": file_id,
                "file_name": file_name,
                "file_type": file_type,
                "file_extension": file_extension,
                "uploaded_file_name": uploaded_file_name,
                "last_updated": last_updated,
                "file_exists": file_exists,
            }
        )
    return files
