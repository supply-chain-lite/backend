from fastapi import APIRouter, HTTPException, Request, status

from app.connection import master_connection

from . import methods as auth_methods
from .schemas import ActivateRequest, ForgotPasswordRequest, MessageResponse, RegisterRequest, ResetPasswordRequest

router = APIRouter()


@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest) -> MessageResponse:
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
        return MessageResponse(message="User registered successfully")


@router.post("/activate", response_model=MessageResponse)
def activate(request: ActivateRequest) -> MessageResponse:
    email = request.email.strip().lower()
    activation_code = request.activation_code.strip()

    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if not activation_code:
        raise HTTPException(status_code=400, detail="activation code is required")

    with master_connection() as cursor:
        auth_methods.activate_user(cursor, email, activation_code)
        return MessageResponse(message="User activated successfully")


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(request: ForgotPasswordRequest) -> MessageResponse:
    email = request.email.strip().lower()

    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    with master_connection() as cursor:
        auth_methods.forgot_password(cursor, email)
        return MessageResponse(message="Password reset instructions sent")


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(request: ResetPasswordRequest) -> MessageResponse:
    email = request.email.strip().lower()
    verification_code = request.verification_code.strip()
    password = request.password.strip()

    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if not verification_code:
        raise HTTPException(status_code=400, detail="verification code is required")
    if not password:
        raise HTTPException(status_code=400, detail="password is required")

    with master_connection() as cursor:
        auth_methods.reset_password(cursor, email, verification_code, password)
        return MessageResponse(message="Password reset successfully")


@router.post("/login")
def login(request: Request):
    print("Login endpoint hit")
    print(request.url)
    return {"message": "Login endpoint - to be implemented"}
