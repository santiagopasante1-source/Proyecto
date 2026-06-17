from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=80)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    nombre: str | None = None


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    nombre: str | None = None
    is_active: bool
    created_at: datetime
    telegram_id: str | None = None

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class DeviceAssign(BaseModel):
    dispositivo_id: int = Field(..., gt=0)
    force: bool = Field(default=False, description="Forzar asignación incluso si pertenece a otro usuario")


class TelegramLink(BaseModel):
    telegram_id: int = Field(..., description="ID numérico de Telegram del usuario")


class ForgotPasswordRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)


class ResetPasswordRequest(BaseModel):
    username: str
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=6, max_length=128)


class UpdateUserRequest(BaseModel):
    email: EmailStr | None = None
    username: str | None = Field(None, min_length=3, max_length=80)
