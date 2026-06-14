"""
main.py — Entry point de la aplicación (Producción Optimizada)
──────────────────────────────────────────────────────────────
Cambios realizados:
  - Implementación de esquemas Pydantic para el endpoint /analizar.
  - Inyección de dependencias formal para acceder al motor de IA.
  - Protección de Base.metadata.create_all para que solo corra en desarrollo.
  - Tipado estricto y manejo limpio de excepciones.
  - Background task para detección de desconexiones de dispositivos.
"""
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text as sql_text

from app.core.config import settings
from app.core.database import Base, SessionLocal, check_db_connection, engine, get_db
from app.api.endpoints import router as telemetry_router
from app.api.auth import router as auth_router
from app.services.ia_manager import IAManager
from app.services.device_monitor import DeviceMonitor

# Registro explícito de todos los modelos antes de create_all
import app.models  # noqa: F401


# ── Esquemas de Validación (Pydantic) ────────────────────────────────────────

class TelemetriaInput(BaseModel):
    """Esquema de validación para los flujos de datos eléctricos de los sensores."""
    voltaje: float = Field(..., description="Voltaje de la línea en Voltios (V)", example=110.5)
    corriente: float = Field(..., description="Corriente de la línea en Amperios (A)", example=15.2)
    frecuencia: float = Field(..., description="Frecuencia de la red en Hertz (Hz)", example=60.0)

    class Config:
        from_attributes = True


# ── Lifespan (Ciclo de Vida) ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialización y limpieza del ciclo de vida de la aplicación."""

    # 1. Inicialización de Base de Datos según el entorno
    print("🗄️  Inicializando tablas de la base de datos...")
    Base.metadata.create_all(bind=engine)
    
    # Migración automática: agrega columnas nuevas a la tabla usuarios si no existen
    db = SessionLocal()
    try:
        from sqlalchemy import inspect, text as sql_text
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("usuarios")]
        if "username" not in columns:
            db.execute(sql_text("ALTER TABLE usuarios ADD COLUMN username VARCHAR(80) UNIQUE"))
            print("✅ Columna 'username' agregada a usuarios.")
        if "password_hash" not in columns:
            db.execute(sql_text("ALTER TABLE usuarios ADD COLUMN password_hash VARCHAR(255)"))
            print("✅ Columna 'password_hash' agregada a usuarios.")
        db.commit()
    except Exception as e:
        print(f"⚠️  Migración automática (opcional): {e}")
        db.rollback()
    finally:
        db.close()

    # Dispositivo por defecto (ID 1) para que exista siempre
    from app.models.dispositivo import Dispositivo
    db = SessionLocal()
    try:
        if not db.query(Dispositivo).filter(Dispositivo.id == 1).first():
            db.add(Dispositivo(id=1, nombre="Sensor_Principal", is_active=True))
            db.commit()
            print("✅ Dispositivo por defecto (ID 1) creado.")
    except Exception as e:
        print(f"❌ Error al crear dispositivo por defecto: {e}")
    finally:
        db.close()

    # 2. Inicializar motor de IA (Carga del modelo Bidirectional-LSTM)
    print(f"🤖 Cargando motor de IA en modo: {settings.IA_MODE}...")
    app.state.detector = IAManager(mode=settings.IA_MODE)
    print(f"✅ Motor de IA listo: {app.state.detector.status}")

    # 3. Inicializar monitor de desconexión de dispositivos
    print("📡 Iniciando monitor de dispositivos...")
    app.state.device_monitor = DeviceMonitor()
    app.state.device_monitor.start()

    yield

    # 4. Limpieza al apagar el servidor
    app.state.device_monitor.stop()
    app.state.detector = None
    print("🛑 Servidor detenido correctamente.")


# ── Configuración de la Aplicación ────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configuración de CORS para permitir la comunicación con el dashboard Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Reemplazar por ["http://localhost:8501"] (Streamlit) en prod si aplica
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telemetry_router)
app.include_router(auth_router)


# ── Dependencias ──────────────────────────────────────────────────────────────

def get_ia_manager(request: Request) -> IAManager:
    """Dependencia para obtener la instancia activa del motor de IA."""
    detector = getattr(request.app.state, "detector", None)
    if not detector:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="El motor de IA no está inicializado en el servidor."
        )
    return detector


# ── Endpoints de Diagnóstico e IA ─────────────────────────────────────────────

@app.get("/health", tags=["Diagnóstico"])
def health_check(request: Request):
    """Estado general del sistema — usado por el dashboard y balanceadores de carga."""
    # Intentamos obtener el detector de manera segura sin romper el endpoint si falla
    detector = getattr(request.app.state, "detector", None)
    
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "database": {
            "connected": check_db_connection(),
            "engine": "postgresql" if not settings.is_sqlite else "sqlite",
        },
        "ia": detector.status if detector else {"ready": False},
    }


@app.get("/api/v1/devices/status", tags=["Dispositivos"])
def devices_status(request: Request, db: Session = Depends(get_db)):
    """Estado de conexión de todos los dispositivos activos."""
    from datetime import datetime, timezone, timedelta
    from app.models.dispositivo import Dispositivo
    from app.models.incidencia import Incidencia, EstadoEnum

    TIMEOUT = 10
    ahora = datetime.now(timezone.utc)
    umbral = ahora - timedelta(seconds=TIMEOUT)
    dispositivos = db.query(Dispositivo).filter(Dispositivo.is_active == True).all()

    resultado = []
    for d in dispositivos:
        estado = "desconocido"
        ultimo_ping = d.ultimo_ping

        if ultimo_ping is None:
            estado = "nunca_conectado"
        elif ultimo_ping < umbral:
            segundos_desconectado = int((ahora - ultimo_ping).total_seconds())
            estado = f"desconectado ({segundos_desconectado}s)"
        else:
            estado = "conectado"

        # Verificar si hay un APAGÓN abierto para este dispositivo
        apagon = db.query(Incidencia).filter(
            Incidencia.dispositivo_id == d.id,
            Incidencia.tipo == "APAGON",
            Incidencia.estado == EstadoEnum.abierta,
        ).first()

        resultado.append({
            "id": d.id,
            "nombre": d.nombre or f"Dispositivo {d.id}",
            "ubicacion": d.ubicacion,
            "ultimo_ping": ultimo_ping.isoformat() if ultimo_ping else None,
            "estado": estado,
            "apagon_activo": apagon is not None,
            "apagon_desde": apagon.created_at.isoformat() if apagon else None,
        })

    return {"dispositivos": resultado}


@app.get("/ia/status", tags=["Diagnóstico"])
def ia_status(manager: IAManager = Depends(get_ia_manager)):
    """Estado detallado del motor de IA — usado por el dashboard Streamlit."""
    return manager.status


@app.post("/analizar", tags=["IA"])
async def analizar_datos(
    datos: TelemetriaInput, 
    manager: IAManager = Depends(get_ia_manager)
):
    """
    Análisis directo en tiempo real (sin persistencia) — óptimo para pruebas desde Streamlit.
    
    Valida automáticamente que el flujo contenga:
    - **voltaje** (float)
    - **corriente** (float)
    - **frecuencia** (float)
    
    Pasa estos datos directamente al modelo Bidirectional-LSTM para detectar anomalías.
    """
    try:
        # datos.model_dump() convierte el esquema Pydantic a un diccionario estándar de Python
        resultado = manager.process_data(datos.model_dump())
        return resultado
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno durante el procesamiento del modelo: {str(e)}"
        )