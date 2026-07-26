import enum
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RolContactoEnum(str, enum.Enum):
    tecnico = "tecnico"
    emergencia = "emergencia"
    distribuidor = "distribuidor"
    conocidos = "conocidos"
    familiar = "familiar"
    proveedor = "proveedor"


ROL_LABELS = {
    RolContactoEnum.tecnico: "Técnico",
    RolContactoEnum.emergencia: "Emergencia",
    RolContactoEnum.distribuidor: "Distribuidor",
    RolContactoEnum.conocidos: "Conocidos",
    RolContactoEnum.familiar: "Familiar",
    RolContactoEnum.proveedor: "Proveedor",
}


class ContactoNotificacion(Base):
    __tablename__ = "contactos_notificacion"

    id = Column(Integer, primary_key=True, index=True)
    dispositivo_id = Column(
        Integer, ForeignKey("dispositivos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre = Column(String(150), nullable=False)
    telegram_id = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    rol = Column(Enum(RolContactoEnum), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "(telegram_id IS NOT NULL) OR (email IS NOT NULL)",
            name="ck_contacto_al_menos_un_canal",
        ),
    )

    dispositivo = relationship("Dispositivo", backref="contactos")

    def __repr__(self) -> str:
        return f"<ContactoNotificacion id={self.id} nombre={self.nombre} rol={self.rol}>"
