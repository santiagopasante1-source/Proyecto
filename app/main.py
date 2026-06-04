"""
main.py — Entry point de la aplicación (Producción Optimizada)
──────────────────────────────────────────────────────────────
Cambios realizados:
  - Implementación de esquemas Pydantic para el endpoint /analizar.
  - Inyección de dependencias formal para acceder al motor de IA.
  - Protección de Base.metadata.create_all para que solo corra en desarrollo.
  - Tipado estricto y manejo limpio de excepciones.
"""
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.database import Base, SessionLocal, check_db_connection, engine
from app.api.endpoints import router
from app.services.ia_manager import IAManager

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
    if settings.ENVIRONMENT == "development":
        print("🗄️  [Dev] Inicializando tablas locales de la base de datos...")
        Base.metadata.create_all(bind=engine)
        
        # Dispositivo de prueba para desarrollo local (ESP32 simula ID 1)
        from app.models.dispositivo import Dispositivo
        db = SessionLocal()
        try:
            if not db.query(Dispositivo).filter(Dispositivo.id == 1).first():
                db.add(Dispositivo(id=1, nombre="Sensor_Principal", is_active=True))
                db.commit()
                print("✅ Dispositivo de prueba (ID 1) verificado/creado.")
        except Exception as e:
            print(f"❌ Error al crear dispositivo de prueba: {e}")
        finally:
            db.close()
    else:
        print("🗄️  [Prod] Saltando create_all. Se asume que las migraciones corren vía Alembic.")

    # 2. Inicializar motor de IA (Carga del modelo Bidirectional-LSTM)
    print(f"🤖 Cargando motor de IA en modo: {settings.IA_MODE}...")
    app.state.detector = IAManager(mode=settings.IA_MODE)
    print(f"✅ Motor de IA listo: {app.state.detector.status}")

    yield

    # 3. Limpieza al apagar el servidor
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

app.include_router(router)


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