from fastapi import APIRouter, Depends

from app.connection import master_connection
from app.routers.auth.methods import _get_user_from_token

from . import methods as project_methods
from . import schemas as project_schemas

router = APIRouter()


@router.post("/current", response_model=project_schemas.CurrentProjectResponse)
def get_current_project(user_data: tuple = Depends(_get_user_from_token)) -> project_schemas.CurrentProjectResponse:
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        project_name = project_methods.get_current_project(cursor, useremail)
        return project_schemas.CurrentProjectResponse(project_name=project_name)


@router.post("/create", response_model=project_schemas.MessageResponse)
def create_project(
    request: project_schemas.ProjectCreateRequest, user_data: tuple = Depends(_get_user_from_token)
) -> project_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    project_name = request.name
    open_after_create = request.create_and_open
    if open_after_create is None:
        open_after_create = True
    with master_connection() as cursor:
        project_methods.add_new_project(cursor, useremail, project_name, open_after_create=request.create_and_open)
        return project_schemas.MessageResponse(message="Project created successfully")


@router.post("/open", response_model=project_schemas.MessageResponse)
def open_project(
    request: project_schemas.OpenProjectRequest, user_data: tuple = Depends(_get_user_from_token)
) -> project_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    project_name = request.project_name
    with master_connection() as cursor:
        project_methods.open_project(cursor, useremail, project_name)
        return project_schemas.MessageResponse(message="Project opened successfully")


@router.post("/delete", response_model=project_schemas.MessageResponse)
def delete_project(
    request: project_schemas.OpenProjectRequest, user_data: tuple = Depends(_get_user_from_token)
) -> project_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    project_name = request.project_name
    with master_connection() as cursor:
        project_methods.delete_project(cursor, useremail, project_name)
        return project_schemas.MessageResponse(message="Project deleted successfully")


@router.post("/rename", response_model=project_schemas.MessageResponse)
def rename_project(
    request: project_schemas.RenameProjectRequest, user_data: tuple = Depends(_get_user_from_token)
) -> project_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    old_project_name = request.old_project_name
    new_project_name = request.new_project_name
    with master_connection() as cursor:
        project_methods.rename_project(cursor, useremail, old_project_name, new_project_name)
        return project_schemas.MessageResponse(message="Project renamed successfully")


@router.post("/list", response_model=list[project_schemas.CurrentProjectResponse])
def list_projects(user_data: tuple = Depends(_get_user_from_token)) -> list[project_schemas.CurrentProjectResponse]:
    useremail, _display_name, _role_name = user_data
    with master_connection() as cursor:
        project_names = project_methods.list_projects(cursor, useremail)
        return [project_schemas.CurrentProjectResponse(project_name=name) for name in project_names]
