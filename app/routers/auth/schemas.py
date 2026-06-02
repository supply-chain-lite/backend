from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    username: str


class ActivateRequest(BaseModel):
    email: EmailStr
    activation_code: str


class GetCurrentUserRequest(BaseModel):
    page_url: str | None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    verification_code: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserDetailsResponse(BaseModel):
    role_name: str
    display_name: str
    email: EmailStr
    redirect_url: str | None = None


class RedirectUrlResponse(BaseModel):
    redirect_url: str


class MessageResponse(BaseModel):
    message: str
