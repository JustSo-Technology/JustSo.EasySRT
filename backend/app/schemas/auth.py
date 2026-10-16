from pydantic import BaseModel, Field

from app.models.auth import UserRole


class LoginRequest(BaseModel):
    username: str = Field(min_length=3)
    password: str = Field(min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8)
    new_password: str = Field(min_length=12)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3)
    password: str = Field(min_length=12)
    role: UserRole


class UserUpdateRequest(BaseModel):
    role: UserRole | None = None
    disabled: bool | None = None


class UserResponse(BaseModel):
    id: str
    username: str
    role: UserRole
    disabled: bool


class BootstrapStatus(BaseModel):
    requires_bootstrap: bool


class AuthStatus(BaseModel):
    authenticated: bool
    user: UserResponse | None = None
    csrf_token: str | None = None
