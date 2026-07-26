from datetime import datetime
from pydantic import BaseModel, Field, model_validator

from app.models.contacto_notificacion import RolContactoEnum


ROL_OPCIONES = [r.value for r in RolContactoEnum]


class ContactoCreate(BaseModel):
    dispositivo_id: int = Field(..., gt=0)
    nombre: str = Field(..., min_length=1, max_length=150)
    telegram_id: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255)
    rol: RolContactoEnum

    @model_validator(mode="after")
    def al_menos_un_canal(self):
        if not self.telegram_id and not self.email:
            raise ValueError("Debe proporcionar al menos un Telegram ID o un Email")
        return self


class ContactoUpdate(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=150)
    telegram_id: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255)
    rol: RolContactoEnum | None = None
    is_active: bool | None = None


class ContactoResponse(BaseModel):
    id: int
    dispositivo_id: int
    nombre: str
    telegram_id: str | None = None
    email: str | None = None
    rol: RolContactoEnum
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
