from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse

from app.connection import master_connection
from app.routers.auth.methods import _get_user_from_token

from . import methods as model_methods
from . import schemas as model_schemas

router = APIRouter()


@router.post("/list", response_model=model_schemas.ModelListResponse)
def get_user_models_by_project(user_data: tuple = Depends(_get_user_from_token)) -> model_schemas.ModelListResponse:
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        project_models = model_methods.get_user_models_by_project(cursor, useremail)
    return model_schemas.ModelListResponse(project_models=project_models)


@router.post("/templates", response_model=model_schemas.ModelTemplatesResponse)
def get_model_templates(user_data: tuple = Depends(_get_user_from_token)) -> model_schemas.ModelTemplatesResponse:
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        model_templates = model_methods.get_model_templates(cursor, useremail)
    return model_schemas.ModelTemplatesResponse(model_templates=model_templates)


@router.post("/create", response_model=model_schemas.MessageResponse)
def add_new_model(
    request: model_schemas.createModelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> model_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    model_template = request.model_template
    model_name = request.model_name
    project_name = request.project_name
    with_sample_data = request.with_sample_data
    with master_connection() as cursor:
        model_methods.add_new_model(cursor, model_name, project_name, useremail, model_template, with_sample_data)
    return model_schemas.MessageResponse(message="Model created successfully")


@router.post("/save-as", response_model=model_schemas.MessageResponse)
def save_as_model(
    request: model_schemas.saveAsModelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> model_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name
    new_model_name = request.new_model_name
    new_project_name = request.project_name
    new_user_email = useremail

    with master_connection() as cursor:
        model_methods.save_as_model(
            cursor, useremail, model_name, project_name, new_model_name, new_project_name, new_user_email
        )
    return model_schemas.MessageResponse(message="Model saved successfully as new model")


@router.post("/rename", response_model=model_schemas.MessageResponse)
def rename_model(
    request: model_schemas.renameModelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> model_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name
    new_model_name = request.new_model_name

    with master_connection() as cursor:
        model_methods.rename_model(cursor, useremail, model_name, project_name, new_model_name)
    return model_schemas.MessageResponse(message="Model renamed successfully")


@router.post("/delete", response_model=model_schemas.MessageResponse)
def delete_model(
    request: model_schemas.modelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> model_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name

    with master_connection() as cursor:
        model_methods.delete_model(cursor, useremail, model_name, project_name)
    return model_schemas.MessageResponse(message="Model deleted successfully")


@router.post("/move", response_model=model_schemas.MessageResponse)
def move_model(
    request: model_schemas.moveModelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> model_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name
    new_project_name = request.new_project_name

    with master_connection() as cursor:
        model_methods.move_model_to_project(cursor, useremail, model_name, project_name, new_project_name)
    return model_schemas.MessageResponse(message="Model moved successfully to the new project")


@router.post("/download", response_class=FileResponse)
def download_model(request: model_schemas.modelRequest, user_data: tuple = Depends(_get_user_from_token)):
    useremail, _, _ = user_data
    model_name = request.model_name
    project_name = request.project_name
    with master_connection() as cursor:
        return model_methods.download_model(cursor, useremail, model_name, project_name)

@router.post("/upload", response_model=model_schemas.MessageResponse)
def upload_model(
    request: model_schemas.modelRequest,
    user_data: tuple = Depends(_get_user_from_token),
    upload_file: UploadFile = File(...),
) -> model_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name
    with master_connection() as cursor:
        model_methods.upload_model(cursor, model_name, project_name, useremail, upload_file)
    return model_schemas.MessageResponse(message="Model uploaded successfully")


@router.post("/backup", response_model=model_schemas.MessageResponse)
def backup_model(
    request: model_schemas.backupModelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> model_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name
    backup_comment = request.backup_comment

    with master_connection() as cursor:
        model_methods.create_model_backup(cursor, useremail, model_name, project_name, backup_comment)
    return model_schemas.MessageResponse(message="Model backup created successfully")


@router.post("/get-backups", response_model=model_schemas.getBackupsResponse)
def get_model_backups(
    request: model_schemas.modelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> model_schemas.getBackupsResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name

    with master_connection() as cursor:
        backups = model_methods.get_model_backups(cursor, useremail, model_name, project_name)

    return model_schemas.getBackupsResponse(model_backups=backups)


@router.post("/restore", response_model=model_schemas.MessageResponse)
def restore_model(
    request: model_schemas.restoreModelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> model_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name
    backup_id = request.backup_id

    with master_connection() as cursor:
        model_methods.restore_model_from_backup(cursor, useremail, model_name, project_name, backup_id)

    return model_schemas.MessageResponse(message="Model restored successfully from backup")


@router.post("/share", response_model=model_schemas.MessageResponse)
def share_model(
    request: model_schemas.shareModelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> model_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    model_name = request.model_name
    project_name = request.project_name
    target_user_email = request.target_user_email
    access_level = request.access_level.value

    with master_connection() as cursor:
        model_methods.share_model(cursor, useremail, target_user_email, model_name, project_name, access_level)
    return model_schemas.MessageResponse(message="Model shared successfully with the target user")


@router.post("/get-notifications", response_model=model_schemas.getNotificationsResponse)
def get_user_notifications(user_data: tuple = Depends(_get_user_from_token)) -> model_schemas.getNotificationsResponse:
    useremail, _display_name, _role_name = user_data

    with master_connection() as cursor:
        notifications = model_methods.get_user_notifications(cursor, useremail)

    return model_schemas.getNotificationsResponse(notifications=notifications)


@router.post("/accept", response_model=model_schemas.MessageResponse)
def accept_model_share(
    request: model_schemas.acceptModelRequest, user_data: tuple = Depends(_get_user_from_token)
) -> model_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    notification_id = request.notification_id
    accept = request.accept
    model_name = request.model_name
    project_name = request.project_name
    create_new_copy = request.create_new_copy

    with master_connection() as cursor:
        model_methods.accept_model_share(
            cursor, notification_id, accept, model_name, project_name, create_new_copy, useremail
        )

    return model_schemas.MessageResponse(message="Model share request response recorded successfully")
