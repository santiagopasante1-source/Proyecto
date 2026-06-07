from __future__ import annotations

import logging
import os
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class IAManager:
    """
    Fachada sobre los detectores de anomalías.
    Expone process_data() y predecir() con una interfaz idéntica
    independientemente del detector activo.
    """

    def __init__(self, mode: str | None = None) -> None:
        self.mode = mode or settings.IA_MODE
        self.detector = None
        self._initialize()

    def _initialize(self) -> None:
        logger.info("IAManager: inicializando en modo '%s'.", self.mode)

        if self.mode == "deep":
            self._init_deep()
        else:
            self._init_classic()

    def _init_classic(self) -> None:
        from app.services.ia_service import AnomalyDetector
        self.detector = AnomalyDetector()
        trained = self.detector.entrenar(settings.TRAINING_CSV_PATH)
        if not trained:
            logger.warning("Classic IA: entrenamiento con datos sintéticos de respaldo.")

    def _init_deep(self) -> None:
        try:
            from app.services.ia_deep_learning import DeepAnomalyDetector, TF_AVAILABLE
            if not TF_AVAILABLE:
                logger.warning("TensorFlow no disponible. Degradando a modo 'classic'.")
                self.mode = "classic"
                self._init_classic()
                return

            self.detector = DeepAnomalyDetector(
                sequence_length=settings.LSTM_SEQUENCE_LENGTH,
            )
            
            # ── CANDADO DE SEGURIDAD PARA PRODUCCIÓN ─────────────────────────
            if not self.detector._is_ready:
                # Si no está en modo desarrollo (es decir, está en Render/Producción)
                if settings.ENVIRONMENT != "development":
                    raise RuntimeError(
                        "❌ ERROR CRÍTICO: El modelo Bidirectional-LSTM real no se pudo cargar en producción. "
                        "Se aborta el inicio para evitar el entrenamiento automático en la nube."
                    )
                
                # Solo entrena desde cero si está en desarrollo local
                csv = settings.TRAINING_CSV_PATH
                if os.path.exists(csv):
                    self.detector.entrenar_con_csv(csv)
                else:
                    logger.warning("CSV no encontrado. Entrenando con datos dummy.")
                    self.detector.entrenar_con_dummy_data()

        except Exception as exc:
            # Si es nuestro error crítico de producción, lo relanzamos para frenar a Render
            if "ERROR CRÍTICO" in str(exc):
                raise exc
                
            logger.error("Error inicializando modo deep: %s. Degradando a classic.", exc)
            self.mode = "classic"
            self._init_classic()

    # ── Interfaz pública ─────────────────────────────────────────────────────

    def process_data(self, datos: dict[str, Any]) -> dict[str, Any]:
        """
        Punto de entrada unificado para análisis de telemetría.
        """
        if self.detector is None:
            return self._fallback("Detector no inicializado.")
        try:
            if hasattr(self.detector, "predecir"):
                return self.detector.predecir(datos)
            return self.detector.process_data(datos)
        except Exception as exc:
            logger.error("Error en inferencia IA: %s", exc)
            return self._fallback(str(exc))

    def procesar(self, datos: dict[str, Any]) -> dict[str, Any]:
        return self.process_data(datos)

    @property
    def status(self) -> dict[str, Any]:
        """Información de estado para el endpoint /health y el dashboard."""
        return {
            "mode": self.mode,
            "detector_class": type(self.detector).__name__ if self.detector else "None",
            "ready": self.detector is not None and getattr(self.detector, "_is_ready", False),
        }

    @staticmethod
    def _fallback(razon: str) -> dict[str, Any]:
        return {
            "anomalia": False,
            "score": 0.0,
            "tipo": None,
            "confianza": 0.0,
            "mensaje": f"IA no disponible: {razon}",
        }