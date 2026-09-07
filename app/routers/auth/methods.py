import hashlib
import json
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from time import sleep
from urllib.parse import urlencode

import jwt
from fastapi import HTTPException, Request, Response

from app.config import (
    ACCESS_TOKEN_EXPIRE_DAYS,
    BASE_URL,
    LOCK_TIME_MINUTES,
    MAX_ATTEMPTS,
    PASSWORD_PEPPER,
    SECRET_KEY,
    SMTP_PORT,
    SMTP_PWD,
    SMTP_URL,
    SMTP_USER,
)
from app.connection import master_connection
from app.logging_config import get_logger

from . import queries as queries

logger = get_logger(__name__)

ACTIVATION_CODE_PREFIX = "AC-"
RESET_CODE_PREFIX = "RE-"


def _hash_password(password: str, salt: bytes) -> str:
    # Include a dedicated pepper in the KDF input to harden derived hashes.
    # Uses PASSWORD_PEPPER (not SECRET_KEY) so JWT key rotation never
    # invalidates existing password hashes.
    pepper = PASSWORD_PEPPER.encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt + pepper,
        120_000,
    ).hex()


def _send_email(to_email: str, subject: str, body: str):
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = "SCL Team <{}>".format(SMTP_USER)
        msg["To"] = to_email
        with smtplib.SMTP(SMTP_URL, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PWD)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
    except Exception:
        logger.exception("Failed to send email to %s: %s", to_email)


def _get_model_templates(cursor):
    templates = cursor.execute(queries.get_template_names).fetchall()
    return [t[0] for t in templates]


def _is_user_expired(end_date_str: str | None) -> bool:
    if not end_date_str:
        return True
    try:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except ValueError:
        return True
    return datetime.now(timezone.utc).date() > end_date


def register_user(cursor, useremail: str, username: str, password: str):
    salt = os.urandom(16)
    password_hash = _hash_password(password, salt)

    existing = cursor.execute(
        queries.check_user_email,
        (useremail,),
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    total_users = cursor.execute("SELECT COUNT(*) FROM S_Users").fetchone()[0]
    is_first_user = total_users == 0
    role_name = "SUPER_ADMIN" if is_first_user else "User"
    role_row = cursor.execute("SELECT RoleId FROM S_UserRoles WHERE RoleName = ?", (role_name,)).fetchone()
    if not role_row:
        raise HTTPException(status_code=500, detail=f"Role {role_name} not found")
    role_id = role_row[0]

    model_templates = _get_model_templates(cursor)
    default_end_date = (
        "2099-01-01" if is_first_user else (datetime.now(timezone.utc).date() + timedelta(days=365)).isoformat()
    )
    user_json_data = json.dumps({"end_date": default_end_date})

    activation_code = None if is_first_user else f"{ACTIVATION_CODE_PREFIX}{os.urandom(3).hex()}"
    is_active = 1 if is_first_user else 0

    cursor.execute(
        queries.create_user,
        (
            useremail,
            role_id,
            username,
            password_hash,
            salt,
            activation_code,
            is_active,
            json.dumps(model_templates),
            user_json_data,
        ),
    )
    cursor.execute(queries.add_default_project, (useremail, useremail))
    cursor.intermediate_commit()

    if is_first_user:
        return

    # Even if the email fails to send, the user is created, so we don't want to rollback the transaction.
    # The user can request a new activation code if needed.
    params = urlencode({"useremail": useremail, "activationcode": activation_code})
    activation_link = f"{BASE_URL}/activate-account.html?{params}"

    subject = "Welcome to Supply Chain Lite"
    body = f"Hello {username},\n\nThank you for registering with Supply Chain Lite! "
    body = f"{body}Please activate your account using the following code: {activation_code}\n"
    body = f"{body}You can also activate your account by clicking the following link: {activation_link}\n\n"
    body = f"{body}Best regards,\nSCL Team\n"

    _send_email(useremail, subject, body)


def activate_user(cursor, useremail: str, activation_code: str):
    if not activation_code.startswith(ACTIVATION_CODE_PREFIX):
        raise HTTPException(status_code=400, detail="Invalid activation code")
    row = cursor.execute(queries.get_status_activation_code, (useremail,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    status, activation_code_db = row
    if status == 1:
        raise HTTPException(status_code=400, detail="User already active")
    if activation_code_db != activation_code:
        raise HTTPException(status_code=400, detail="Invalid activation code")

    cursor.execute(queries.update_user_activation, (useremail,))
    cursor.intermediate_commit()


def forgot_password(cursor, useremail: str):
    row = cursor.execute(queries.get_status_activation_code, (useremail,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    status, _activation_code_db = row
    if status == 0:
        raise HTTPException(status_code=400, detail="User account is not active")

    verification_code = f"{RESET_CODE_PREFIX}{os.urandom(8).hex()}"
    cursor.execute(queries.update_password_reset_code, (verification_code, useremail))
    cursor.intermediate_commit()

    subject = "Supply Chain Lite Password Reset"
    params = urlencode({"useremail": useremail, "verificationcode": verification_code})
    reset_link = f"{BASE_URL}/reset-password.html?{params}"
    body = "Hello,\n\nWe received a request to reset your password for your Supply Chain Lite account. "
    body = f"{body}Please click the following link to reset your password: {reset_link}\n\n"
    body = f"{body}If you did not request a password reset, please ignore this email.\n\nBest regards,\nSCL Team\n"

    _send_email(useremail, subject, body)


def reset_password(cursor, useremail: str, verification_code: str, password: str):
    if not verification_code.startswith(RESET_CODE_PREFIX):
        logger.warning("Password reset attempt failed due to invalid verification code prefix for user: %s", useremail)
        raise HTTPException(status_code=400, detail="Password reset request unsuccessful")
    row = cursor.execute(queries.get_status_activation_code, (useremail,)).fetchone()
    if not row:
        logger.warning("Password reset attempt failed for non-existent user: %s", useremail)
        raise HTTPException(status_code=400, detail="Password reset request unsuccessful")
    status, verification_code_db = row
    if status == 0:
        logger.warning("Password reset attempt failed for inactive user: %s", useremail)
        raise HTTPException(status_code=400, detail="Password reset request unsuccessful")
    if verification_code_db != verification_code:
        logger.warning("Password reset attempt failed due to invalid verification code for user: %s", useremail)
        raise HTTPException(status_code=400, detail="Password reset request unsuccessful")

    salt = os.urandom(16)
    password_hash = _hash_password(password, salt)

    cursor.execute(
        queries.update_password_reset_code,
        (
            None,
            useremail,
        ),
    )
    cursor.execute(
        queries.update_user_password,
        (password_hash, salt, useremail),
    )
    cursor.intermediate_commit()


def _generate_token(token_version: int, useremail: str) -> str:
    expiration = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {"token_version": token_version, "useremail": useremail, "exp": expiration.timestamp()}
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    return token


def login_user(cursor, useremail: str, password: str):
    row = cursor.execute(queries.get_user_password, (useremail,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Invalid credentials")
    password_hash_db, salt_db, is_active, failed_attempts, token_version, is_locked, role_name, end_date = row
    if is_active == 0:
        raise HTTPException(status_code=400, detail="User account is not active")
    if is_locked:
        raise HTTPException(status_code=400, detail="User account is locked")
    if _is_user_expired(end_date):
        raise HTTPException(status_code=400, detail="User account has expired")

    if token_version is None:
        token_version = 0

    password_hash = _hash_password(password, salt_db)
    lock_minutes = "+0 minutes"
    if password_hash != password_hash_db:
        failed_attempts += 1
        if failed_attempts >= MAX_ATTEMPTS:
            lock_minutes = f"+{LOCK_TIME_MINUTES} minutes"
        cursor.execute(queries.lock_user_account, (lock_minutes, token_version, failed_attempts, useremail))
        cursor.intermediate_commit()
        raise HTTPException(status_code=400, detail="Invalid credentials")
    cursor.execute(queries.lock_user_account, (lock_minutes, token_version + 1, 0, useremail))
    access_token = _generate_token(token_version + 1, useremail)
    return access_token, role_name


def _get_user_from_token(request: Request, response: Response):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = _verify_token(token)
    useremail = payload.get("useremail")
    if not useremail:
        raise HTTPException(status_code=401, detail="Invalid token: missing user email")
    token_version = payload.get("token_version")
    if token_version is None or int(token_version) < 1:
        raise HTTPException(status_code=401, detail="Token has been revoked")
    with master_connection() as cursor:
        row = cursor.execute(queries.get_user_details, (useremail,)).fetchone()
        if not row:
            _delete_cookie_and_raise(response, 404, "User not found")
        role_name, display_name, token_version_db, is_active, is_locked, end_date = row
        if token_version_db != token_version:
            _delete_cookie_and_raise(response, 401, "Token has been revoked")
        if is_active == 0:
            _delete_cookie_and_raise(response, 400, "User account is not active")
        if is_locked:
            _delete_cookie_and_raise(response, 400, "User account is locked")
        if _is_user_expired(end_date):
            _delete_cookie_and_raise(response, 400, "User account has expired")
    return useremail, display_name, role_name


def _delete_cookie_and_raise(response: Response, status_code: int, detail: str):
    response.delete_cookie(key="access_token", path="/")
    set_cookie_header = response.headers.get("set-cookie")
    headers = {"set-cookie": set_cookie_header} if set_cookie_header else None
    raise HTTPException(status_code=status_code, detail=detail, headers=headers)


def _verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def change_password(cursor, useremail: str, current_password: str, new_password: str):
    row = cursor.execute(queries.get_user_password, (useremail,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    password_hash_db, salt_db, is_active, _, _, is_locked, _, end_date = row
    if is_active == 0:
        raise HTTPException(status_code=400, detail="User account is not active")
    if is_locked:
        raise HTTPException(status_code=400, detail="User account is locked")
    if _is_user_expired(end_date):
        raise HTTPException(status_code=400, detail="User account has expired")

    current_password_hash = _hash_password(current_password, salt_db)
    if current_password_hash != password_hash_db:
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    new_salt = os.urandom(16)
    new_password_hash = _hash_password(new_password, new_salt)
    sleep(2)  # Add delay to test account lock functionality
    cursor.execute(
        queries.update_user_password,
        (new_password_hash, new_salt, useremail),
    )
    cursor.intermediate_commit()


def get_home_page_url(cursor, role_name: str) -> str:
    row = cursor.execute(queries.get_home_page_url, (role_name,)).fetchone()
    if row and row[0]:
        return row[0]
    return "home-page.html"


def check_if_user_can_access_page(cursor, role_name: str, page_url: str) -> bool:
    if role_name == "SUPER_ADMIN":
        return True  # Super admin has access to all pages
    row = cursor.execute(queries.check_if_user_can_access_url, (role_name, page_url)).fetchone()
    return row[0] > 0


def check_module_access(cursor, role_name: str, module_path: str):
    """Verify the user's role has access to the given API module path. Raises 403 if not."""
    if role_name == "SUPER_ADMIN":
        return  # Super admin has access to all modules
    row = cursor.execute(queries.check_module_access, (role_name, module_path)).fetchone()
    if not row or row[0] == 0:
        raise HTTPException(status_code=403, detail="You do not have permission to access this module")


def get_modules(cursor, role_name: str) -> list[str]:
    """Return a list of module names accessible to the given role."""
    module_query = queries.get_modules
    params = (role_name,)
    if role_name.upper() == "SUPER_ADMIN":
        module_query = queries.get_all_modules
        params = ()
    rows = cursor.execute(module_query, params).fetchall()
    return [row[0] for row in rows]


def check_can_add_new_model(cursor, role_name: str):
    """Verify the user's role is permitted to add new models. Raises 403 if not."""
    if role_name == "SUPER_ADMIN":
        return  # Super admin can always add new models
    row = cursor.execute(queries.check_can_add_new_model, (role_name,)).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Role not found")
    can_add = row[0]
    if can_add is None:
        return  # Permission not configured; default to allowed for backward compatibility
    if can_add == 0:
        raise HTTPException(status_code=403, detail="You do not have permission to add new models")
