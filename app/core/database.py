"""
app/core/database.py
────────────────────
Módulo de conexión a base de datos.
- SQLite   (desarrollo): sin pool
- PostgreSQL (producción): pool de conexiones optimizado para la nube.

SQLAlchemy
"""
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.core.config import settings

# ── Construcción del engine según entorno

def _build_engine():
    if settings.is_sqlite:
        # SQLite: desarrollo local
        return create_engine(
            settings.DATABASE_URL,
            connect_args={"check_same_thread": False},
            echo=settings.DEBUG,
        )
    else:
        # PostgreSQL: pool de conexiones para producción en la nube
        return create_engine(
            settings.DATABASE_URL,
            echo=settings.DEBUG,
            # Pool sizing — ajusta según el plan de tu proveedor cloud:
            pool_size=10,           # Conexiones permanentes en el pool
            max_overflow=20,        # Conexiones extra bajo carga puntual
            pool_pre_ping=True,     # Verifica la conexión antes de usarla (evita "stale connections")
            pool_recycle=1800,      # Recicla conexiones cada 30 min (evita timeouts del servidor)
        )


engine = _build_engine()

# ── Habilitar WAL en SQLite (mejora la concurrencia de lecturas) 
if settings.is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_wal(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

# ── Session factory 
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# ── Base declarativa para todos los modelos ORM 
Base = declarative_base()


# ── Dependency de FastAPI
def get_db() -> Generator[Session, None, None]:
    """
    Inyecta una sesión de base de datos por request.
    Garantiza el cierre de la sesión incluso si ocurre una excepción.
    Uso en endpoints:
        def my_endpoint(db: Session = Depends(get_db)): ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> bool:
    """Verifica la conectividad con la base de datos. Útil para el endpoint /health."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
