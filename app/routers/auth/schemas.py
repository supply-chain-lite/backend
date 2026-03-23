from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    username: str
    base_url: str

class ActivateRequest(BaseModel):
    email: EmailStr
    activation_code: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    base_url: str

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    message: str
