from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.connection import master_connection

from . import methods as auth_methods
from . import schemas as auth_schemas

router = APIRouter()


@router.post("/register", response_model=auth_schemas.MessageResponse, status_code=status.HTTP_201_CREATED)
def register(request: auth_schemas.RegisterRequest) -> auth_schemas.MessageResponse:
    email = request.email.strip().lower()
    username = request.username.strip()
    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if not request.password:
        raise HTTPException(status_code=400, detail="password is required")

    with master_connection() as cursor:
        auth_methods.register_user(cursor, email, username, request.password)
        return auth_schemas.MessageResponse(message="User registered successfully")


@router.post("/activate", response_model=auth_schemas.MessageResponse)
def activate(request: auth_schemas.ActivateRequest) -> auth_schemas.MessageResponse:
    email = request.email.strip().lower()
    activation_code = request.activation_code.strip()

    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if not activation_code:
        raise HTTPException(status_code=400, detail="activation code is required")

    with master_connection() as cursor:
        auth_methods.activate_user(cursor, email, activation_code)
        return auth_schemas.MessageResponse(message="User activated successfully")


@router.post("/forgot-password", response_model=auth_schemas.MessageResponse)
def forgot_password(request: auth_schemas.ForgotPasswordRequest) -> auth_schemas.MessageResponse:
    email = request.email.strip().lower()

    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    with master_connection() as cursor:
        try:
            auth_methods.forgot_password(cursor, email)
        except HTTPException as ex:
            if ex.status_code not in (400, 404):
                raise
            pass
        return auth_schemas.MessageResponse(message="If the account exists, password reset instructions have been sent")


@router.post("/reset-password", response_model=auth_schemas.MessageResponse)
def reset_password(request: auth_schemas.ResetPasswordRequest) -> auth_schemas.MessageResponse:
    email = request.email.strip().lower()
    verification_code = request.verification_code.strip()
    password = request.password

    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if not verification_code:
        raise HTTPException(status_code=400, detail="verification code is required")
    if not password:
        raise HTTPException(status_code=400, detail="password is required")

    with master_connection() as cursor:
        auth_methods.reset_password(cursor, email, verification_code, password)
        return auth_schemas.MessageResponse(message="Password reset successfully")


@router.post("/login", response_model=auth_schemas.MessageResponse)
def login(request: auth_schemas.LoginRequest, response: Response) -> auth_schemas.MessageResponse:
    email = request.email.strip().lower()
    password = request.password
    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if not password:
        raise HTTPException(status_code=400, detail="password is required")
    with master_connection() as cursor:
        access_token = auth_methods.login_user(cursor, email, password)
    response.set_cookie(key="access_token", value=access_token, httponly=True, secure=True, samesite="Lax")
    return auth_schemas.MessageResponse(message="Login successful")


@router.post("/logout", response_model=auth_schemas.MessageResponse)
def logout(response: Response) -> auth_schemas.MessageResponse:
    response.delete_cookie(key="access_token", httponly=True, secure=True, samesite="lax", path="/")
    return auth_schemas.MessageResponse(message="Logout successful")


@router.post("/me", response_model=auth_schemas.UserDetailsResponse)
def get_current_user(user_data: tuple = Depends(auth_methods._get_user_from_token)) -> auth_schemas.UserDetailsResponse:
    useremail, display_name, role_name = user_data
    return auth_schemas.UserDetailsResponse(role_name=role_name, display_name=display_name, email=useremail)


@router.post("/change-password", response_model=auth_schemas.MessageResponse)
def change_password(
    request: auth_schemas.ChangePasswordRequest, user_data: tuple = Depends(auth_methods._get_user_from_token)
) -> auth_schemas.MessageResponse:
    useremail, _display_name, _role_name = user_data
    current_password = request.current_password
    new_password = request.new_password

    if not current_password:
        raise HTTPException(status_code=400, detail="current password is required")
    if not new_password:
        raise HTTPException(status_code=400, detail="new password is required")

    with master_connection() as cursor:
        auth_methods.change_password(cursor, useremail, current_password, new_password)
        return auth_schemas.MessageResponse(message="Password changed successfully")
