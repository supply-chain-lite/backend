import hashlib
import json
import os
import smtplib
from email.mime.text import MIMEText
from urllib.parse import urlencode

from fastapi import HTTPException

from app.config import BASE_URL, SECRET_KEY, SMTP_PORT, SMTP_PWD, SMTP_URL, SMTP_USER

from . import queries as queries


def _hash_password(password: str, salt: bytes) -> str:
    # Include app secret in the KDF input to harden derived hashes.
    secret = SECRET_KEY.encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt + secret,
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
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to send email: " + str(e))


def _get_model_templates(cursor):
    templates = cursor.execute(queries.get_template_names).fetchall()
    return [t[0] for t in templates]


def register_user(cursor, useremail: str, username: str, password: str):
    salt = os.urandom(16)
    password_hash = _hash_password(password, salt)

    existing = cursor.execute(
        queries.check_user_email,
        (useremail,),
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    model_templates = _get_model_templates(cursor)

    activation_code = os.urandom(3).hex()

    cursor.execute(
        queries.create_user,
        (
            useremail,
            2,
            username,
            password_hash,
            salt,
            activation_code,
            0,
            json.dumps(model_templates),
        ),
    )

    cursor.intermediate_commit()
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

    verification_code = os.urandom(8).hex()
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
    row = cursor.execute(queries.get_status_activation_code, (useremail,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    status, verification_code_db = row
    if status == 0:
        raise HTTPException(status_code=400, detail="User account is not active")
    if verification_code_db != verification_code:
        raise HTTPException(status_code=400, detail="Invalid verification code")

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
