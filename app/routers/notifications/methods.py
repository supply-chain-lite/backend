import json

from fastapi import HTTPException

from app.routers.models.methods import get_model_details, get_project_id, save_as_model
from app.routers.models.queries import get_access_level, insert_user_models

from . import queries as notification_queries


def get_user_notifications(cursor, user_email: str, get_all: bool = False):
    if get_all:
        rows = cursor.execute(notification_queries.get_all_user_notifications, (user_email,)).fetchall()
    else:
        rows = cursor.execute(notification_queries.get_user_notifications, (user_email,)).fetchall()
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
        created_at,
    ) in rows:
        params_dict = json.loads(params) if params else {}
        project_name = params_dict.get("project_name")
        model_name = params_dict.get("model_name")
        notification_level = params_dict.get("LEVEL", "INFO")

        notifications.append(
            {
                "notification_id": notification_id,
                "from_user_email": from_user_email,
                "task_id": params_dict.get("task_id"),
                "title": title,
                "message": message,
                "notification_type": notification_type,
                "project_name": project_name,
                "model_name": model_name,
                "is_read": is_read,
                "is_accepted": is_accepted,
                "notification_level": notification_level,
                "created_at": created_at,
            }
        )
    return notifications


def mark_notification_read(cursor, notification_ids: list[int], user_email: str):
    for notification_id in notification_ids:
        row = cursor.execute(notification_queries.mark_notification_read, (notification_id, user_email)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Notification not found: {notification_id}")


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
    notification_row = cursor.execute(
        notification_queries.get_notification_params, (notification_id, user_email)
    ).fetchone()
    if not notification_row:
        raise HTTPException(status_code=404, detail=f"Notification not found; {user_email}, {notification_id}")

    if not accept:
        accept_params = json.dumps({"Status": "Rejected"})
        cursor.execute(notification_queries.accept_notification, (-1, accept_params, notification_id, user_email))
        return

    from_user_email = notification_row[0]
    notification_params = json.loads(notification_row[1]) if notification_row[1] else {}
    model_id = notification_params.get("model_id")
    model_name = notification_params.get("model_name")
    project_name = notification_params.get("project_name")
    access_level = notification_params.get("access_level")

    old_model = get_model_details(cursor, model_name, project_name, from_user_email)

    if not old_model:
        raise HTTPException(status_code=404, detail="Model not found for sharing")

    is_running = old_model.is_running
    if is_running:
        raise HTTPException(status_code=400, detail="Cannot accept a shared model while a task using it is running")

    old_model_id = old_model.model_id
    if old_model_id != model_id:
        raise HTTPException(status_code=400, detail="Model ID mismatch")

    row = cursor.execute(get_access_level, (old_model_id, user_email)).fetchone()
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
        new_model = get_model_details(cursor, new_model_name, new_project_name, user_email)

        if new_model:
            raise HTTPException(status_code=400, detail="User already has a model with the same name in the project")
        cursor.execute(
            insert_user_models,
            (model_id, user_email, project_id, access_level, new_model_name),
        )
    accept_params = {
        "model_name": new_model_name,
        "project_name": new_project_name,
        "create_copy": create_copy,
        "Status": "Accepted",
    }
    cursor.execute(
        notification_queries.accept_notification, (1, json.dumps(accept_params), notification_id, user_email)
    )
