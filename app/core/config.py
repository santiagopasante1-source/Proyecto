"""
app/core/config.py
──────────────────
Configuración centralizada de la aplicación para PostgreSQL (Producción/Neon).
Lee variables de entorno desde el archivo .env usando pydantic-settings.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Identidad de la app 
    APP_NAME: str = "IoT Anomaly Detection API"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"  # development | staging | production

    # ── Base de datos (PostgreSQL / Neon)
    # Ejemplo: postgresql+psycopg2://user:pass@host:5432/iot_db
    DATABASE_URL: str

    # ── Seguridad / JWT 
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ── Motor de IA 
    # "classic" → IsolationForest (scikit-learn)
    # "deep"    → LSTM (TensorFlow/Keras)
    IA_MODE: str = "deep"
    TRAINING_CSV_PATH: str = "dataset_entrenamiento.csv"
    LSTM_SEQUENCE_LENGTH: int = 10

    # ── Telegram (Notificaciones)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # ── Configuración Pydantic-Settings 
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # Cambiado a False para evitar fallos si el .env tiene minúsculas
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_sqlite(self) -> bool:
        """Propiedad dinámica que evalúa si el motor actual es SQLite."""
        return str(self.DATABASE_URL).startswith("sqlite")


@lru_cache()
def get_settings() -> Settings:
    """Singleton cacheado — la configuración se lee una sola vez al arrancar."""
    return Settings()


settings = get_settings()