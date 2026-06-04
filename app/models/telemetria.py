from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, String, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Telemetria(Base):
    """
    Modelo ORM de la tabla 'telemetrias'.
    Representa el almacenamiento persistente de las mediciones eléctricas
    capturadas por los sensores (ZPT101B para voltaje, SCT-013 para corriente).
    """
    __tablename__ = "telemetrias"

    # Identificador único del registro en la base de datos
    id = Column(Integer, primary_key=True, index=True)
    
    # Clave foránea que relaciona esta telemetría con su dispositivo de origen
    dispositivo_id = Column(Integer, ForeignKey("dispositivos.id"), nullable=False)

    # --- Mediciones Eléctricas Reales ---
    # Voltaje en Voltios (V) - Capturado por el ZPT101B
    voltaje = Column(Float, nullable=False)
    
    # Corriente en Amperios (A) - Capturada por la pinza SCT-013
    corriente = Column(Float, nullable=False)
    
    # Potencia activa en Vatios (W) - Derivada matemáticamente
    potencia = Column(Float, nullable=True)
    
    # Frecuencia de red en Hertz (Hz) - Derivada del muestreo de onda de voltaje
    frecuencia = Column(Float, nullable=True)

    # --- Metadatos y Auditoría ---
    # Marca de tiempo automática al momento de la inserción
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Flags de procesamiento de Inteligencia Artificial
    procesado_ia = Column(Boolean, default=False)
    anomalia_detectada = Column(Boolean, default=False)
    
    # JSON original recibido del hardware (utilizado para trazabilidad)
    raw_payload = Column(String(2000), nullable=True)

    # Relación bidireccional con el modelo de Dispositivo
    dispositivo = relationship("Dispositivo", back_populates="telemetrias")

    def __repr__(self) -> str:
        """Representación legible para depuración (logs)"""
        return f"<Telemetria id={self.id} V={self.voltaje}V A={self.corriente}A>"