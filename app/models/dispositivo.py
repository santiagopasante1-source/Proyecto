from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Dispositivo(Base):
    """
    Modelo ORM de la tabla 'dispositivos'.
    Representa el nodo IoT físico que envía las mediciones eléctricas.
    """
    __tablename__ = "dispositivos"

    id = Column(Integer, primary_key=True, index=True)
    
    # Marcamos usuario_id
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    
    # Nombre y MAC address
    nombre = Column(String(150), nullable=True)
    mac_address = Column(String(17), unique=True, index=True, nullable=True)
    
    descripcion = Column(String(500), nullable=True)
    ubicacion = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    ultimo_ping = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    usuario = relationship("Usuario", back_populates="dispositivos")
    telemetrias = relationship(
        "Telemetria", back_populates="dispositivo", cascade="all, delete-orphan"
    )
    incidencias = relationship(
        "Incidencia", back_populates="dispositivo", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Dispositivo id={self.id} nombre={self.nombre}>"