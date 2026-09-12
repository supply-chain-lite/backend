"""API routes for user management operations."""

from fastapi import APIRouter, Depends

from app.connections.connection import master_connection
from app.routers.auth.methods import _get_user_from_token, check_module_access
from app.routers.models.methods import get_user_models_by_project
from app.routers.models.schemas import ModelListResponse

from . import methods as user_methods
from . import schemas as user_schemas

router = APIRouter()
this_api = "/api/user-management"


@router.post("/get-users", response_model=user_schemas.UserDetailResponse)
def get_users(user_data: tuple = Depends(_get_user_from_token)) -> user_schemas.UserDetailResponse:
    """Return the list of users"""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        user_details = user_methods.get_users(cursor)

    return user_schemas.UserDetailResponse(userDetails=user_details)


@router.post("/get-templates", response_model=user_schemas.TemplateResponse)
def get_templates(user_data: tuple = Depends(_get_user_from_token)) -> user_schemas.TemplateResponse:
    """Return the list of templates"""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        templates = user_methods.get_templates(cursor)

    return user_schemas.TemplateResponse(templates=templates)


@router.post("/get-user-models", response_model=ModelListResponse)
def get_user_models(
    request: user_schemas.GetUserModelsRequest, user_data: tuple = Depends(_get_user_from_token)
) -> ModelListResponse:
    """Return the list of user models"""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        project_models = get_user_models_by_project(cursor, request.UserEmail)

    return ModelListResponse(project_models=project_models)


@router.post("/get-modules", response_model=user_schemas.ModulesResponse)
def get_modules(user_data: tuple = Depends(_get_user_from_token)) -> user_schemas.ModulesResponse:
    """Return the list of modules"""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        modules, home_pages = user_methods.get_modules(cursor)

    return user_schemas.ModulesResponse(modules=modules, HomePages=home_pages)


@router.post("/get-roles", response_model=user_schemas.RoleResponse)
def get_roles(user_data: tuple = Depends(_get_user_from_token)) -> user_schemas.RoleResponse:
    """Return the list of roles"""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        roles = user_methods.get_roles(cursor)

    return user_schemas.RoleResponse(roles=roles)


@router.post("/add-user", response_model=user_schemas.MessageResponse)
def add_user(
    request: user_schemas.AddNewUserRequest, user_data: tuple = Depends(_get_user_from_token)
) -> user_schemas.MessageResponse:
    """Add a new user"""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        user_methods.add_new_user(cursor, request)

    return user_schemas.MessageResponse(message="User added successfully")


@router.post("/add-role", response_model=user_schemas.MessageResponse)
def add_role(
    request: user_schemas.AddNewRoleRequest, user_data: tuple = Depends(_get_user_from_token)
) -> user_schemas.MessageResponse:
    """Add a new role"""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        user_methods.add_new_role(cursor, request)

    return user_schemas.MessageResponse(message="Role added successfully")


@router.post("/update-user", response_model=user_schemas.MessageResponse)
def update_user(
    request: user_schemas.UpdateUserRequest, user_data: tuple = Depends(_get_user_from_token)
) -> user_schemas.MessageResponse:
    """Update an existing user"""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        user_methods.update_user(cursor, request)

    return user_schemas.MessageResponse(message="User updated successfully")


@router.post("/update-role", response_model=user_schemas.MessageResponse)
def update_role(
    request: user_schemas.UpdateRoleRequest, user_data: tuple = Depends(_get_user_from_token)
) -> user_schemas.MessageResponse:
    """Update an existing role"""
    useremail, _display_name, role_name = user_data

    with master_connection() as cursor:
        check_module_access(cursor, role_name, this_api)
        user_methods.update_role(cursor, request)

    return user_schemas.MessageResponse(message="Role updated successfully")
