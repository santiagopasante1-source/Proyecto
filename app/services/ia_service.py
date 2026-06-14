"""
app/services/ia_service.py
──────────────────────────
Motor clásico de detección de anomalías basado en IsolationForest (scikit-learn).
Implementa reglas de protección eléctrica en capas:
  Capa 1 → Protecciones críticas (cortes, sobrevoltaje grave)
  Capa 2 → Calidad de energía (voltaje fuera de norma, frecuencia inestable)
  Capa 3 → Inferencia del modelo de Machine Learning (IsolationForest)
"""
from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """
    Detector clásico de anomalías eléctricas.

    Jerarquía de detección (primera capa que dispara gana):
        1. Protecciones críticas  → alertas inmediatas por reglas deterministas.
        2. Calidad de energía     → verificación de rangos normativos.
        3. IA (IsolationForest)   → detección de patrones inusuales no cubiertos por reglas.
    """

    def __init__(self, threshold: float = 0.85) -> None:
        self.threshold = threshold
        self.model: IsolationForest | None = None
        logger.info("AnomalyDetector (classic) instanciado. Esperando entrenamiento...")

    # ── Entrenamiento ────────────────────────────────────────────────────────

    def entrenar(self, csv_path: str | None = None) -> bool:
        """
        Entrena el IsolationForest.
        Si existe el CSV de entrenamiento, lo usa; si no, genera datos sintéticos.
        Devuelve True si el entrenamiento fue exitoso.
        """
        path = csv_path or "dataset_entrenamiento.csv"
        try:
            if os.path.exists(path):
                df = pd.read_csv(path)
                required = {"voltaje", "corriente", "frecuencia"}
                if not required.issubset(df.columns):
                    raise ValueError(f"El CSV debe tener columnas: {required}")
                X = df[["voltaje", "corriente", "frecuencia"]].values
                logger.info("Entrenando IsolationForest con %d muestras reales...", len(X))
            else:
                logger.warning("CSV no encontrado. Usando datos sintéticos de referencia.")
                rng = np.random.default_rng(42)
                X = np.column_stack([
                    rng.normal(120, 5, 1000),   # voltaje ~120 V (norma ANSI)
                    rng.normal(10, 2, 1000),    # corriente ~10 A
                    rng.normal(60, 0.5, 1000),  # frecuencia ~60 Hz
                ])

            self.model = IsolationForest(
                n_estimators=200,
                contamination=0.05,   # 5 % de datos esperados como anomalía
                random_state=42,
                n_jobs=-1,
            )
            self.model.fit(X)
            logger.info("IsolationForest entrenado exitosamente.")
            return True

        except Exception as exc:
            logger.error("Error entrenando IsolationForest: %s", exc)
            return False

    # ── Interfaz pública ─────────────────────────────────────────────────────

    def predecir(self, data: dict[str, Any]) -> dict[str, Any]:
        """Alias de process_data para compatibilidad con IAManager."""
        return self.process_data(data)

    def process_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Analiza un registro de telemetría y devuelve un reporte de anomalía.

        Parámetros
        ----------
        data : dict con claves voltaje, corriente, potencia (opt), frecuencia (opt)

        Retorna
        -------
        dict con claves: anomalia (bool), score (float), tipo (str|None),
                         confianza (float), mensaje (str)
        """
        # Capa 1: Reglas críticas (siempre se evalúan)
        resultado = self._detectar_protecciones_criticas(data)
        if resultado:
            return resultado

        # Capa 2: Calidad de energía
        resultado = self._detectar_calidad_energia(data)
        if resultado:
            return resultado

        # Capa 3: Inferencia del modelo ML
        return self._ia_inference(data)

    # ── Capas de detección ───────────────────────────────────────────────────

    def _detectar_protecciones_criticas(self, data: dict[str, Any]) -> dict[str, Any] | None:
        v = data.get("voltaje", 0)
        i = data.get("corriente", 0)

        if v == 0:
            return self._alerta("FALLO_TOTAL", 1.0, "Corte total de energía detectado.")
        if v > 253:
            return self._alerta("SOBREVOLTAJE_CRITICO", 0.95,
                                f"Voltaje {v:.1f}V supera límite crítico IEC 60038 (253 V).")
        if i > 200:
            return self._alerta("SOBRECORRIENTE_CRITICA", 0.95,
                                f"Corriente {i:.1f}A en zona de riesgo severo (>200 A).")
        return None

    def _detectar_calidad_energia(self, data: dict[str, Any]) -> dict[str, Any] | None:
        v = data.get("voltaje", 0)
        f = data.get("frecuencia", 0)

        if f > 0:  # Solo evaluar frecuencia si fue enviada
            if not (59.5 <= f <= 60.5):
                return self._alerta("CALIDAD_FRECUENCIA", 0.80,
                                    f"Frecuencia inestable: {f:.2f} Hz (rango ANSI: 59.5–60.5 Hz).")

        if v > 0 and not (108 <= v <= 132):  # ±10 % de 120 V (ANSI C84.1)
            return self._alerta("CALIDAD_VOLTAJE", 0.78,
                                f"Voltaje {v:.1f}V fuera de rango ANSI (108–132 V).")
        return None

    def _ia_inference(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.model is None:
            return {
                "anomalia": False, "score": 0.0,
                "tipo": None, "confianza": 0.0,
                "mensaje": "Modelo IA no disponible — operación normal asumida.",
            }

        features = np.array([[
            data.get("voltaje", 0),
            data.get("corriente", 0),
            data.get("frecuencia", 60),
        ]])
        prediccion = self.model.predict(features)[0]      # 1 = normal, -1 = anomalía
        score_raw = self.model.decision_function(features)[0]
        # Normalizamos el score al rango [0, 1]: más cercano a 1 = más anómalo
        score = float(max(0.0, min(1.0, 0.5 - score_raw)))

        if prediccion == -1:
            return self._alerta("ANOMALIA_IA", round(score, 4),
                                "Patrón eléctrico inusual detectado por IsolationForest.")
        return {
            "anomalia": False, "score": round(score, 4),
            "tipo": None, "confianza": round(1.0 - score, 4),
            "mensaje": "Operación eléctrica normal.",
        }

    @staticmethod
    def _alerta(tipo: str, score: float, mensaje: str) -> dict[str, Any]:
        return {
            "anomalia": True,
            "score": score,
            "tipo": tipo,
            "confianza": round(score, 4),
            "mensaje": mensaje,
        }
