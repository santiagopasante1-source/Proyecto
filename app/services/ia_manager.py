"""
app/services/ia_manager.py
──────────────────────────
Manager unificado del motor de IA.
Actúa como fachada (Facade pattern) sobre los detectores disponibles:
  - "classic" → IsolationForest (scikit-learn) — rápido, sin GPU
  - "deep"    → LSTM bidireccional (TensorFlow) — mayor precisión con datos históricos

El endpoint y el lifespan solo conocen IAManager.process_data().
Para cambiar de motor: modifica IA_MODE en .env y reinicia.
"""
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
            # Solo entrena desde cero si el modelo no fue cargado desde disco
            if not self.detector._is_ready:
                csv = settings.TRAINING_CSV_PATH
                if os.path.exists(csv):
                    self.detector.entrenar_con_csv(csv)
                else:
                    logger.warning("CSV no encontrado. Entrenando con datos dummy.")
                    self.detector.entrenar_con_dummy_data()

        except Exception as exc:
            logger.error("Error inicializando modo deep: %s. Degradando a classic.", exc)
            self.mode = "classic"
            self._init_classic()

    # ── Interfaz pública ─────────────────────────────────────────────────────

    def process_data(self, datos: dict[str, Any]) -> dict[str, Any]:
        """
        Punto de entrada unificado para análisis de telemetría.
        Llama a predecir() o process_data() según el detector activo.
        Nunca lanza excepciones — siempre devuelve un resultado seguro.
        """
        if self.detector is None:
            return self._fallback("Detector no inicializado.")
        try:
            # Ambos detectores exponen predecir(); ia_service también process_data()
            if hasattr(self.detector, "predecir"):
                return self.detector.predecir(datos)
            return self.detector.process_data(datos)
        except Exception as exc:
            logger.error("Error en inferencia IA: %s", exc)
            return self._fallback(str(exc))

    # Alias para retrocompatibilidad con main.py → manager.procesar(datos)
    def procesar(self, datos: dict[str, Any]) -> dict[str, Any]:
        return self.process_data(datos)

    @property
    def status(self) -> dict[str, Any]:
        """Información de estado para el endpoint /health y el dashboard."""
        return {
            "mode": self.mode,
            "detector_class": type(self.detector).__name__ if self.detector else "None",
            "ready": self.detector is not None,
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
