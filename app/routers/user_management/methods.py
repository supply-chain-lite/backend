import json
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from app.routers.auth.methods import forgot_password

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


def get_users(cursor) -> list[user_schema.UserDetail]:
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
        }
        user_details.append(user_schema.UserDetail(**this_user_detail))
    return user_details


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


def add_new_user(cursor, user_data: user_schema.AddNewUserRequest):
    """
    Add a new user to the database.

    Args:
        cursor: Database cursor.
        user_data: User data as an AddNewUserRequest object.
    """
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
