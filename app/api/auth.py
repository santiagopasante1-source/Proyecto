from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer

from app.core.database import get_db
from app.core.security import (
    verify_password, create_access_token, decode_access_token,
    hash_password, generate_reset_code, hash_reset_code,
)
from app.models.usuario import Usuario
from app.schemas.usuario import (
    UserLogin, UserResponse, Token, TelegramLink,
    ForgotPasswordRequest, ResetPasswordRequest,
    UpdateUserRequest,
)
from app.services.telegram import telegram_service

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token malformado")
    user = db.query(Usuario).filter(Usuario.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado o inactivo")
    return user


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario desactivado")

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(access_token=access_token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
def me(current_user: Usuario = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UpdateUserRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.email is not None and payload.email != current_user.email:
        existing = db.query(Usuario).filter(Usuario.email == payload.email).first()
        if existing:
            raise HTTPException(status_code=409, detail="Ese email ya está registrado por otro usuario")
        current_user.email = payload.email

    if payload.username is not None and payload.username != current_user.username:
        existing = db.query(Usuario).filter(Usuario.username == payload.username).first()
        if existing:
            raise HTTPException(status_code=409, detail="Ese nombre de usuario ya está registrado")
        current_user.username = payload.username

    db.commit()
    db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    user = db.query(Usuario).filter(Usuario.username == payload.username).first()
    if not user or not user.telegram_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado o sin Telegram vinculado",
        )

    code = generate_reset_code()
    user.reset_code_hash = hash_reset_code(code)
    user.reset_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.commit()

    mensaje = (
        f"🔐 *Codigo de recuperacion*\n\n"
        f"Tu codigo para restablecer la contrasena es:\n\n"
        f"`{code}`\n\n"
        f"Vence en 10 minutos. Si no solicitaste esto, ignora este mensaje."
    )
    telegram_service.send_notification(mensaje, 0, "RECUPERACION", user.telegram_id)

    return {"ok": True, "mensaje": "Si el usuario existe, revisa tu Telegram"}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.username == payload.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not user.reset_code_hash or not user.reset_code_expires_at:
        raise HTTPException(status_code=400, detail="No hay codigo de recuperacion pendiente")

    if datetime.now(timezone.utc) > user.reset_code_expires_at:
        user.reset_code_hash = None
        user.reset_code_expires_at = None
        db.commit()
        raise HTTPException(status_code=400, detail="El codigo ha expirado, solicita uno nuevo")

    if not verify_password(payload.code, user.reset_code_hash):
        raise HTTPException(status_code=400, detail="Codigo incorrecto")

    user.password_hash = hash_password(payload.new_password)
    user.reset_code_hash = None
    user.reset_code_expires_at = None
    db.commit()

    mensaje = (
        f"✅ *Contrasena restablecida*\n\n"
        f"Tu contrasena ha sido cambiada exitosamente."
    )
    telegram_service.send_notification(mensaje, 0, "RECUPERACION", user.telegram_id)

    return {"ok": True, "mensaje": "Contrasena restablecida exitosamente"}


@router.put("/telegram")
def link_telegram(
    payload: TelegramLink,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.telegram_id = str(payload.telegram_id)
    db.commit()
    return {"ok": True, "telegram_id": payload.telegram_id}


@router.post("/telegram/test")
def test_telegram(
    current_user: Usuario = Depends(get_current_user),
):
    if not current_user.telegram_id:
        raise HTTPException(status_code=400, detail="No tienes un ID de Telegram vinculado")

    mensaje = (
        f"🔔 *Prueba de Telegram*\n\n"
        f"✅ Si recibes esto, las notificaciones de anomalias funcionan correctamente.\n\n"
        f"👤 *Usuario:* {current_user.username}\n"
        f"📧 *Email:* {current_user.email}"
    )
    telegram_service.send_notification(mensaje, 0, "PRUEBA", current_user.telegram_id)
    return {"ok": True, "mensaje": "Mensaje de prueba enviado a Telegram"}



