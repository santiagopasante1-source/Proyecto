# app/models/__init__.py
"""
Archivo de inicialización del módulo de modelos.
Al importar este archivo, todos los modelos se registran automáticamente
en la metadata de SQLAlchemy, permitiendo que Base.metadata.create_all()
cree todas las tablas correctamente en la base de datos.
"""

from .usuario import Usuario
from .dispositivo import Dispositivo
from .telemetria import Telemetria
from .incidencia import Incidencia

# Declaramos qué clases exporta este módulo para mantener limpio el namespace
__all__ = ["Usuario", "Dispositivo", "Telemetria", "Incidencia"]