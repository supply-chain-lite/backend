"""API routes for managing notifications."""

from fastapi import APIRouter, Depends

from app.connections.connection import master_connection
from app.routers.auth.methods import _get_user_from_token, check_can_add_new_model, check_module_access

from . import methods as notification_methods
from . import schemas as notification_schemas

router = APIRouter()
this_api = "/api/notifications"


@router.post("/get", response_model=notification_schemas.getNotificationsResponse)
def get_user_notifications(
    request: notification_schemas.getNotificationsRequest, user_data: tuple = Depends(_get_user_from_token)
) -> notification_schemas.getNotificationsResponse:
    """Return incoming model-sharing notifications for the authenticated user."""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        notifications = notification_methods.get_user_notifications(cursor, useremail, request.get_all)

    return notification_schemas.getNotificationsResponse(notifications=notifications)


@router.post("/mark-read", response_model=notification_schemas.MessageResponse)
def mark_notification_read(
    request: notification_schemas.markNotificationsReadRequest, user_data: tuple = Depends(_get_user_from_token)
) -> notification_schemas.MessageResponse:
    """Mark a notification as read for the authenticated user."""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        notification_methods.mark_notification_read(cursor, request.notification_ids, useremail)

    return notification_schemas.MessageResponse(message="Notification marked as read successfully")


@router.post("/accept", response_model=notification_schemas.MessageResponse)
def accept_model_share(
    request: notification_schemas.acceptModelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> notification_schemas.MessageResponse:
    """
    Accept or reject a model-sharing request and optionally create a personal copy.

    Parameters:
        request (acceptModelRequest): Contains `notification_id`, `accept` (boolean), `model_name`, `project_name`, and `create_new_copy` (boolean).

    Returns:
        MessageResponse: Confirmation message that the share request response was recorded.
    """
    useremail, _display_name, role_name = user_data
    notification_id = request.notification_id
    accept = request.accept
    model_name = request.model_name
    project_name = request.project_name
    create_new_copy = request.create_new_copy

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        if accept and create_new_copy:
            check_can_add_new_model(cursor, role_name)
        notification_methods.accept_model_share(
            cursor, notification_id, accept, model_name, project_name, create_new_copy, useremail
        )

    return notification_schemas.MessageResponse(message="Model share request response recorded successfully")
