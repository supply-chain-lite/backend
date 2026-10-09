import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.routers.auth.methods import forgot_password
from app.routers.models import queries as model_queries
from app.routers.models.methods import get_model_details
from app.routers.projects.methods import add_new_project
from app.routers.projects.queries import get_project_id

from . import queries as user_queries
from . import schemas as user_schema


def _parse_json(value: str | None, default):
    """Parse a JSON string, returning the default if empty or malformed."""
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def get_users(cursor, current_user_email) -> list[user_schema.UserDetail]:
    """
    Get the list of users from the database.

    Args:
        cursor: Database cursor.

    Returns:
        List of user details as UserDetail objects.
    """
    all_rows = cursor.execute(user_queries.list_users).fetchall()
    user_details = []
    default_end_date = (datetime.now(timezone.utc).date() + timedelta(days=365)).isoformat()
    for row in all_rows:
        user_email, display_name, is_active, access_templates, role_name, json_data, created_at = row
        access_templates = _parse_json(access_templates, [])
        other_data = _parse_json(json_data, {})
        max_concurrent_runs = other_data.get("max_concurrent_runs", 1)
        end_date = other_data.get("end_date", default_end_date)
        this_user_detail = {
            "UserEmail": user_email,
            "DisplayName": display_name,
            "IsActive": is_active,
            "Templates": access_templates,
            "RoleName": role_name,
            "EndDate": end_date,
            "MaxConcurrentRuns": max_concurrent_runs,
            "CreatedAt": created_at,
            "userModels": get_user_models(cursor, user_email, current_user_email),
        }
        user_details.append(user_schema.UserDetail(**this_user_detail))
    return user_details


def get_user_models(cursor, user_email: str, current_user_email: str) -> list[user_schema.UserModel]:
    """Return a user's non-owned models with their access levels."""
    rows = cursor.execute(user_queries.get_shared_models, (current_user_email, user_email)).fetchall()
    return [user_schema.UserModel(ModelId=model_id, AccessLevel=access_level) for model_id, access_level in rows]


def update_user_models(
    cursor,
    current_user_email: str,
    user_email: str,
    user_models: list[user_schema.UserModel],
) -> None:
    """Sync models owned by the acting user to the destination user's requested shares.

    An empty list requests clearing all non-owned models. Routes skip this
    method when userModels is omitted or null.
    """
    if current_user_email == user_email:
        raise HTTPException(status_code=400, detail="A user cannot share models with themselves")

    requested_models = {}
    for user_model in user_models:
        model_id = user_model.ModelId
        access_level = user_model.AccessLevel.lower()
        if access_level not in {"read", "write", "execute", "admin"}:
            raise HTTPException(status_code=400, detail=f"Invalid access level: {user_model.AccessLevel}")
        if model_id in requested_models:
            raise HTTPException(status_code=400, detail=f"Duplicate model ID: {model_id}")

        row = cursor.execute(user_queries.get_access_level, (model_id, current_user_email)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Model {model_id} was not found for the acting user")
        (current_user_access_level,) = row
        if current_user_access_level != "owner":
            raise HTTPException(status_code=403, detail=f"Only model owners can share model {model_id}")

        requested_models[model_id] = access_level

    for model_id, access_level in requested_models.items():
        dest_row = cursor.execute(user_queries.get_access_level, (model_id, user_email)).fetchone()
        if dest_row is None:
            add_user_model(cursor, current_user_email, user_email, model_id, access_level)
        else:
            (dest_access_level,) = dest_row
            if dest_access_level == "owner":
                raise HTTPException(status_code=400, detail=f"Cannot change ownership of model {model_id}")
            cursor.execute(model_queries.update_user_access_level, (access_level, model_id, user_email))

    existing_shared_models = cursor.execute(user_queries.get_shared_models, (current_user_email, user_email)).fetchall()
    for model_id, _ in existing_shared_models:
        if model_id not in requested_models:
            cursor.execute(user_queries.delete_shared_model, (model_id, user_email))


def add_user_model(
    cursor,
    current_user_email: str,
    dest_user_email: str,
    model_id: int,
    access_level: str,
) -> None:
    """Add a non-owned model for a user with the specified access level."""
    source_row = cursor.execute(
        model_queries.get_model_name_and_project_name, (model_id, current_user_email)
    ).fetchone()
    if source_row is None:
        raise HTTPException(status_code=404, detail=f"Model {model_id} was not found for the acting user")
    model_name, project_name = source_row

    project_row = cursor.execute(get_project_id, (dest_user_email, project_name)).fetchone()
    if project_row is None:
        add_new_project(cursor, dest_user_email, project_name, open_after_create=False)
        project_row = cursor.execute(get_project_id, (dest_user_email, project_name)).fetchone()
    if project_row is None:
        raise HTTPException(status_code=500, detail=f"Could not create project '{project_name}'")
    project_id = project_row[0]

    model_details = get_model_details(cursor, model_name, project_name, dest_user_email)
    if model_details:
        raise HTTPException(
            status_code=400,
            detail=f"User already has a model with the same project: {project_name} and model name: {model_name}",
        )
    cursor.execute(
        model_queries.insert_user_models,
        (model_id, dest_user_email, project_id, access_level, model_name),
    )


def get_templates(cursor) -> list[str]:
    """
    Get the list of distinct templates from the database.

    Args:
        cursor: Database cursor.
    Returns:
        List of distinct template names.
    """
    all_rows = cursor.execute(user_queries.list_templates).fetchall()
    return [row[0] for row in all_rows]


def get_modules(cursor) -> tuple[list[str], list[str]]:
    """
    Get the list of distinct modules from the database.

    Args:
        cursor: Database cursor.
    Returns:
        List of distinct module names.
        List of distinct home pages
    """
    modules = []
    home_pages = []
    for module, home_page in cursor.execute(user_queries.list_modules).fetchall():
        modules.append(module)
        home_pages.append(home_page)
    return list(set(modules)), list(set(home_pages))


def get_roles(cursor) -> list[user_schema.RoleDetail]:
    """
    Get the list of roles from the database.

    Args:
        cursor: Database cursor.
    Returns:
        List of role details as RoleDetail objects.
    """
    all_rows = cursor.execute(user_queries.list_roles).fetchall()
    role_details = []
    for row in all_rows:
        role_id, role_name, role_description, created_at, json_data = row
        other_data = _parse_json(json_data, {})
        modules = other_data.get("modules", [])
        home_page = other_data.get("homePage", "")
        can_add_new_model = other_data.get("canAddNewModel", False)
        if isinstance(can_add_new_model, bool):
            can_add_new_model = int(can_add_new_model)
        this_role_detail = {
            "RoleId": role_id,
            "RoleName": role_name,
            "RoleDescription": role_description,
            "Modules": modules,
            "HomePage": home_page,
            "CanAddNewModel": can_add_new_model,
            "CreatedAt": created_at,
        }
        role_details.append(user_schema.RoleDetail(**this_role_detail))
    return role_details


def _validate_role_name(role_name: str | None) -> None:
    """Reject the SUPER_ADMIN role from user assignment paths."""
    if role_name and role_name.upper() == "SUPER_ADMIN":
        raise HTTPException(status_code=400, detail="Cannot change the role to a SUPER_ADMIN user.")


def add_new_user(cursor, user_data: user_schema.AddNewUserRequest):
    """
    Add a new user to the database.

    Args:
        cursor: Database cursor.
        user_data: User data as an AddNewUserRequest object.
    """
    _validate_role_name(user_data.RoleName)
    access_templates = json.dumps(user_data.Templates)
    other_data = json.dumps({"end_date": user_data.EndDate, "max_concurrent_runs": user_data.MaxConcurrentRuns})
    row = cursor.execute(
        user_queries.add_new_user,
        (
            user_data.UserEmail,
            user_data.DisplayName,
            access_templates,
            other_data,
            user_data.RoleName,
            user_data.UserEmail,
        ),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail=f"User with email {user_data.UserEmail} already exists.")
    forgot_password(cursor, user_data.UserEmail)  # Send forgot password email to the new user
    return


def add_new_role(cursor, role_data: user_schema.AddNewRoleRequest):
    """
    Add a new role to the database.

    Args:
        cursor: Database cursor.
        role_data: Role data as an AddNewRoleRequest object.
    """
    all_modules, _ = get_modules(cursor)
    for module in role_data.Modules:
        if module not in all_modules:
            raise HTTPException(status_code=400, detail=f"Module '{module}' does not exist.")

    other_data = json.dumps(
        {
            "modules": role_data.Modules,
            "homePage": role_data.HomePage,
            "canAddNewModel": int(role_data.CanAddNewModel),
        }
    )
    row = cursor.execute(
        user_queries.add_new_role,
        (role_data.RoleName, role_data.RoleDescription, other_data, role_data.RoleName),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail=f"Role with name {role_data.RoleName} already exists.")
    return


def update_role(cursor, role_data: user_schema.UpdateRoleRequest):
    """
    Update an existing role in the database.

    Args:
        cursor: Database cursor.
        role_data: Role data as an UpdateRoleRequest object.
    """
    if role_data.Modules:
        all_modules, _ = get_modules(cursor)
        for module in role_data.Modules:
            if module not in all_modules:
                raise HTTPException(status_code=400, detail=f"Module '{module}' does not exist.")

    other_data = {}
    if role_data.Modules:
        other_data["modules"] = role_data.Modules
    if role_data.HomePage is not None:
        other_data["homePage"] = role_data.HomePage
    if role_data.CanAddNewModel is not None:
        other_data["canAddNewModel"] = int(role_data.CanAddNewModel)
    other_data = json.dumps(other_data) if other_data else None

    row = cursor.execute(
        user_queries.update_role,
        (role_data.RoleName, role_data.RoleDescription, other_data, other_data, role_data.RoleId),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail=f"Role with id {role_data.RoleId} does not exist.")
    return


def update_user(cursor, user_data: user_schema.UpdateUserRequest):
    """
    Update an existing user in the database.

    Args:
        cursor: Database cursor.
        user_data: User data as an UpdateUserRequest object.
    """
    access_templates = json.dumps(user_data.Templates) if user_data.Templates else None
    other_data = {}
    if user_data.EndDate:
        other_data["end_date"] = user_data.EndDate
    if user_data.MaxConcurrentRuns:
        other_data["max_concurrent_runs"] = user_data.MaxConcurrentRuns

    other_data = json.dumps(other_data)
    role_id = None
    if user_data.RoleName:
        _validate_role_name(user_data.RoleName)
        role_id_row = cursor.execute(user_queries.get_role_id, (user_data.RoleName,)).fetchone()
        if role_id_row is None:
            raise HTTPException(status_code=400, detail=f"Role with name {user_data.RoleName} does not exist.")
        role_id = role_id_row[0]
    row = cursor.execute(
        user_queries.update_user,
        (
            user_data.DisplayName,
            user_data.IsActive,
            access_templates,
            role_id if user_data.RoleName else None,
            other_data,
            user_data.UserEmail,
        ),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail=f"User with email {user_data.UserEmail} does not exist.")
    return
