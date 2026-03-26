from fastapi import APIRouter, Depends

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
