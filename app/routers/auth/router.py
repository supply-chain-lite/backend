from app.connection import master_connection
from fastapi import APIRouter, HTTPException, status
from app.config import SECRET_KEY as settings_secret_key
from . import methods as auth_methods

from .schemas import MessageResponse, RegisterRequest

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

