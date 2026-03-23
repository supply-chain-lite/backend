from fastapi import APIRouter, HTTPException, status

from app.connection import master_connection

from . import methods as auth_methods
from .schemas import ActivateRequest, MessageResponse, RegisterRequest

router = APIRouter()


@router.post(
    "/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED
)
def register(request: RegisterRequest) -> MessageResponse:
    email = request.email.strip().lower()
    username = request.username.strip()
    base_url = request.base_url.strip()

    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if not request.password:
        raise HTTPException(status_code=400, detail="password is required")
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")

    with master_connection() as cursor:
        auth_methods.register_user(cursor, email, username, request.password, base_url)
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
