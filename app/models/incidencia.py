from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, String, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class SeveridadEnum(str, enum.Enum):
    baja = "baja"
    media = "media"
    alta = "alta"
    critica = "critica"


class EstadoEnum(str, enum.Enum):
    abierta = "abierta"
    en_revision = "en_revision"
    resuelta = "resuelta"
    descartada = "descartada"


class Incidencia(Base):
    __tablename__ = "incidencias"

    id = Column(Integer, primary_key=True, index=True)
    dispositivo_id = Column(Integer, ForeignKey("dispositivos.id"), nullable=False)
    telemetria_id = Column(Integer, ForeignKey("telemetrias.id"), nullable=True)

    tipo = Column(String(100), nullable=False)
    descripcion = Column(String(1000), nullable=True)
    severidad = Column(Enum(SeveridadEnum), default=SeveridadEnum.media, nullable=False)
    estado = Column(Enum(EstadoEnum), default=EstadoEnum.abierta, nullable=False)
    score_anomalia = Column(Float, nullable=True)  # IA confidence [0.0 – 1.0]

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    notas = Column(String(2000), nullable=True)

    # Relationships
    dispositivo = relationship("Dispositivo", back_populates="incidencias")

    def __repr__(self) -> str:
        return f"<Incidencia id={self.id} tipo={self.tipo} severidad={self.severidad}>"
