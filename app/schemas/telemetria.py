from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional
from datetime import datetime
import math


class TelemetriaCreate(BaseModel):
    """
    Esquema de validación para los datos entrantes de telemetría IoT.
    Aplica reglas estrictas para asegurar que solo entren datos limpios a la base de datos.
    """
    
    # ID del dispositivo físico que transmite
    dispositivo_id: int = Field(..., gt=0, description="ID del dispositivo (debe existir activo en la BD)")
    
    # Voltaje medido por el transformador ZPT101B
    voltaje: float = Field(
        ...,
        gt=0,
        le=1000,
        description="Voltaje en Voltios (V). Debe ser un número positivo finito hasta 1000 V.",
        examples=[115.4],
    )
    
    # Corriente medida por la pinza no invasiva SCT-013
    corriente: float = Field(
        ...,
        gt=0,
        le=500,
        description="Corriente en Amperios (A). Debe ser un número positivo finito hasta 500 A.",
        examples=[12.3],
    )
    
    # Potencia activa calculada en Vatios (W)
    potencia: Optional[float] = Field(
        default=None,
        ge=0,
        description="Potencia activa en Vatios (W). Opcional, se autoderiva si no se envía.",
    )
    
    # Frecuencia de red en Hertz (Hz) 
    frecuencia: Optional[float] = Field(
        default=None,
        ge=0,
        le=1000,
        description="Frecuencia de la red eléctrica en Hertz (Hz).",
    )
    
    # Cadena opcional para almacenar el JSON crudo original enviado por el hardware (para trazabilidad y auditoría)
    raw_payload: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Cadena JSON original cruda enviada por el dispositivo para auditoría.",
    )

    # ─── Campos de apagón ─────────────────────────────────────
    apagon: Optional[bool] = Field(
        default=False,
        description="Indica si el dispositivo reporta una pérdida de suministro eléctrico.",
    )
    inicio_apagon: Optional[int] = Field(
        default=None,
        description="Timestamp Unix (epoch) del inicio del apagón.",
    )
    fin_apagon: Optional[int] = Field(
        default=None,
        description="Timestamp Unix (epoch) del fin del apagón.",
    )
    duracion_seg: Optional[int] = Field(
        default=None,
        ge=0,
        description="Duración del apagón en segundos.",
    )

    @field_validator("voltaje", "corriente")
    @classmethod
    def must_be_finite(cls, v: float, info) -> float:
        """
        Validador a nivel de campo: Garantiza que los valores eléctricos no sean nulos (NaN)
        ni infinitos, y redondea los registros automáticamente a 4 decimales.
        """
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"El campo {info.field_name} debe ser un número finito válido, se recibió: {v}")
        return round(v, 4)

    @model_validator(mode="after")
    def compute_potencia_if_missing(self) -> "TelemetriaCreate":
        """
        Validador a nivel de modelo: Derivación matemática automatizada.
        Si el nodo IoT no envía la potencia calculada, el backend la calcula multiplicando
        el Voltaje por la Corriente (P = V * I) antes de persistir en la base de datos.
        """
        if self.potencia is None:
            self.potencia = round(self.voltaje * self.corriente, 4)
        return self

    # Configuración de metadatos para la documentación interactiva de Swagger UI
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "dispositivo_id": 1,
                    "voltaje": 115.4,
                    "corriente": 12.3,
                    "frecuencia": 60.0,
                }
            ]
        }
    }


class TelemetriaResponse(BaseModel):
    """
    Esquema de salida (Respuesta): Estructura de datos que devuelve la API
    al cliente una vez que el registro eléctrico ha sido guardado exitosamente en SQLite.
    """
    id: int
    dispositivo_id: int
    voltaje: float
    corriente: float
    potencia: Optional[float]
    frecuencia: Optional[float]
    timestamp: datetime
    procesado_ia: bool
    anomalia_detectada: bool

    # Permite a Pydantic leer los datos directamente desde los modelos ORM de SQLAlchemy
    model_config = {"from_attributes": True}


class TelemetriaIAResult(BaseModel):
    """
    Esquema compuesto definitivo: Retorna al cliente la telemetría guardada
    junto con el desglose completo del veredicto del análisis de la Inteligencia Artificial.
    """
    telemetria: TelemetriaResponse
    ia_resultado: dict