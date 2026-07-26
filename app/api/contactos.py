from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.contacto_notificacion import ContactoNotificacion
from app.models.dispositivo import Dispositivo
from app.models.usuario import Usuario
from app.schemas.contacto import ContactoCreate, ContactoUpdate, ContactoResponse
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/v1/contactos", tags=["Contactos de Notificación"])

MAX_CONTACTOS = 3


@router.post("", response_model=ContactoResponse, status_code=status.HTTP_201_CREATED)
def crear_contacto(
    payload: ContactoCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dispositivo = db.query(Dispositivo).filter(Dispositivo.id == payload.dispositivo_id).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    if dispositivo.usuario_id != current_user.id:
        raise HTTPException(status_code=403, detail="No eres dueño de este dispositivo")

    existentes = (
        db.query(ContactoNotificacion)
        .filter(ContactoNotificacion.dispositivo_id == payload.dispositivo_id)
        .count()
    )
    if existentes >= MAX_CONTACTOS:
        raise HTTPException(
            status_code=400,
            detail=f"Este dispositivo ya tiene {MAX_CONTACTOS} contactos (máximo permitido)",
        )

    contacto = ContactoNotificacion(
        dispositivo_id=payload.dispositivo_id,
        nombre=payload.nombre,
        telegram_id=payload.telegram_id,
        email=payload.email,
        rol=payload.rol,
    )
    db.add(contacto)
    db.commit()
    db.refresh(contacto)
    return contacto


@router.get("/{dispositivo_id}", response_model=list[ContactoResponse])
def listar_contactos(
    dispositivo_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dispositivo = db.query(Dispositivo).filter(Dispositivo.id == dispositivo_id).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    if dispositivo.usuario_id != current_user.id:
        raise HTTPException(status_code=403, detail="No eres dueño de este dispositivo")

    contactos = (
        db.query(ContactoNotificacion)
        .filter(ContactoNotificacion.dispositivo_id == dispositivo_id)
        .order_by(ContactoNotificacion.id)
        .all()
    )
    return contactos


@router.patch("/{contacto_id}", response_model=ContactoResponse)
def actualizar_contacto(
    contacto_id: int,
    payload: ContactoUpdate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contacto = db.query(ContactoNotificacion).filter(ContactoNotificacion.id == contacto_id).first()
    if not contacto:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    dispositivo = db.query(Dispositivo).filter(Dispositivo.id == contacto.dispositivo_id).first()
    if not dispositivo or dispositivo.usuario_id != current_user.id:
        raise HTTPException(status_code=403, detail="No eres dueño de este contacto")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(contacto, field, value)

    if not contacto.telegram_id and not contacto.email:
        raise HTTPException(
            status_code=400,
            detail="Debe mantener al menos un Telegram ID o un Email",
        )

    db.commit()
    db.refresh(contacto)
    return contacto


@router.delete("/{contacto_id}")
def eliminar_contacto(
    contacto_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contacto = db.query(ContactoNotificacion).filter(ContactoNotificacion.id == contacto_id).first()
    if not contacto:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    dispositivo = db.query(Dispositivo).filter(Dispositivo.id == contacto.dispositivo_id).first()
    if not dispositivo or dispositivo.usuario_id != current_user.id:
        raise HTTPException(status_code=403, detail="No eres dueño de este contacto")

    db.delete(contacto)
    db.commit()
    return {"ok": True, "mensaje": "Contacto eliminado"}
