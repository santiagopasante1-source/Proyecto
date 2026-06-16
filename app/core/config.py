import os
import streamlit as st
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- PUENTE DE SEGURIDAD (INYECCIÓN DE SECRETOS) ---
# Esto toma los valores de Streamlit Secrets y los pone en el Sistema Operativo
# para que Pydantic pueda verlos como variables de entorno normales.
try:
    if hasattr(st, "secrets"):
        for key, value in st.secrets.items():
            # Si el secreto es una sección (ej: [database]), aplanamos los valores
            if isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    os.environ[sub_key.upper()] = str(sub_val)
            else:
                os.environ[key.upper()] = str(value)
except Exception:
    # Si no estamos en Streamlit (local), simplemente ignoramos este paso
    pass

class Settings(BaseSettings):
    # ── Identidad de la app 
    APP_NAME: str = "IoT Anomaly Detection API"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # ── Base de datos (PostgreSQL / Neon)
    DATABASE_URL: str

    # ── Seguridad / JWT 
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ── Zona horaria (PostgreSQL)
    TIMEZONE: str = "America/Caracas"

    # ── Motor de IA 
    IA_MODE: str = "deep"
    TRAINING_CSV_PATH: str = "dataset_entrenamiento.csv"
    LSTM_SEQUENCE_LENGTH: int = 10

    # ── Telegram (Notificaciones)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # ── Detección de cortes eléctricos
    OFFLINE_TIMEOUT_SECONDS: int = 30

    # ── Configuración Pydantic-Settings 
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_sqlite(self) -> bool:
        return str(self.DATABASE_URL).startswith("sqlite")


@lru_cache()
def get_settings() -> Settings:
    """Singleton cacheado — la configuración se lee una sola vez al arrancar."""
    return Settings()


# Instanciamos settings aquí. Gracias al puente de arriba, 
# Pydantic ya encontrará DATABASE_URL en el entorno.
settings = get_settings()