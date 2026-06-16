"""
app/services/ia_deep_learning.py
─────────────────────────────────
Motor de Deep Learning para detección de anomalías eléctricas.
Arquitectura: LSTM bidireccional con ventana deslizante de secuencias.

Flujo de inferencia:
  1. Cada llamada a predecir() agrega una muestra al buffer circular.
  2. Cuando el buffer alcanza sequence_length, realiza la inferencia.
  3. Mientras calibra, devuelve un estado de espera (no bloquea la API).

Entrenamiento:
  - Con CSV real: detector.entrenar_con_csv("dataset_entrenamiento.csv")
  - Guarda/carga el modelo en disco para no reentrenar en cada arranque.
"""
from __future__ import annotations

import logging
import os
from collections import deque
from typing import Any

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

# Importación condicional
try:
    import tensorflow as tf
    TF_AVAILABLE = True
    logger.info("TensorFlow %s disponible.", tf.__version__)
except ImportError:
    TF_AVAILABLE = False
    logger.warning("TensorFlow no instalado. DeepAnomalyDetector no estará disponible.")

MODEL_SAVE_PATH = "models/lstm_anomaly_detector.h5"
CSV_ENTRENAMIENTO_DEFAULT = "dataset_entrenamiento.csv"


class DeepAnomalyDetector:
    """
    Detector de anomalías basado en LSTM bidireccional.

    Parámetros
    ----------
    sequence_length : int
        Número de muestras consecutivas que conforman una ventana de entrada.
    features : int
        Número de variables de entrada (voltaje, corriente, frecuencia = 3).
    threshold : float
        Score de salida (sigmoid) a partir del cual se clasifica como anomalía.
    """

    FEATURES = ["voltaje", "corriente", "frecuencia"]

    def __init__(
        self,
        sequence_length: int = 10,
        threshold: float = 0.90,
    ) -> None:
        self.sequence_length = sequence_length
        self.features = len(self.FEATURES)
        self.threshold = threshold
        self.model = None
        self._buffer: deque[list[float]] = deque(maxlen=sequence_length)
        self._is_ready = False

        if TF_AVAILABLE:
            if os.path.exists(MODEL_SAVE_PATH):
                self._load_model()
            else:
                # CANDADO: Si no existe el modelo físico en producción, detenemos el sistema
                if settings.ENVIRONMENT != "development":
                    raise RuntimeError(
                        f"❌ ERROR CRÍTICO: El archivo del modelo no existe en la ruta '{MODEL_SAVE_PATH}'. "
                        f"Asegúrate de haber subido tu nuevo archivo Keras a GitHub."
                    )
                
                # Comportamiento local si estás desarrollando
                self.model = self._build_model()
                if os.path.exists(CSV_ENTRENAMIENTO_DEFAULT):
                    logger.info("Archivo '%s' detectado. Iniciando entrenamiento inicial automático...", CSV_ENTRENAMIENTO_DEFAULT)
                    self.entrenar_con_csv(CSV_ENTRENAMIENTO_DEFAULT)
                else:
                    logger.info("Modelo LSTM construido. Pendiente de entrenamiento (No se encontró '%s').", CSV_ENTRENAMIENTO_DEFAULT)
        else:
            logger.error("TensorFlow no disponible — DeepAnomalyDetector en modo stub.")

    # ── Arquitectura del modelo 
    def _build_model(self):
        """LSTM bidireccional con regularización Dropout."""
        if not TF_AVAILABLE:
            return None

        model = tf.keras.Sequential([
            tf.keras.layers.Bidirectional(
                tf.keras.layers.LSTM(64, return_sequences=True),
                input_shape=(self.sequence_length, self.features),
            ),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.LSTM(32),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(16, activation="relu"),
            tf.keras.layers.Dense(1, activation="sigmoid"),
        ])
        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
            loss="binary_crossentropy",
            metrics=["accuracy", tf.keras.metrics.AUC(name="auc")],
        )
        return model

    # ── Persistencia 
    def _save_model(self) -> None:
        if self.model is None:
            return
        os.makedirs(os.path.dirname(MODEL_SAVE_PATH), exist_ok=True)
        self.model.save(MODEL_SAVE_PATH)
        logger.info("Modelo LSTM guardado en %s", MODEL_SAVE_PATH)

    def _load_model(self) -> None:
        try:
            # 1. Cargamos de forma segura omitiendo la compilación inicial conflictiva
            self.model = tf.keras.models.load_model(MODEL_SAVE_PATH, compile=False)
            
            # 2. Compilamos manualmente con la configuración exacta original
            self.model.compile(
                optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
                loss="binary_crossentropy",
                metrics=["accuracy", tf.keras.metrics.AUC(name="auc")],
            )
            self._is_ready = True
            logger.info("✅ Modelo LSTM cargado y compilado con éxito desde %s", MODEL_SAVE_PATH)
            
        except Exception as exc:
            logger.error("Error cargando el archivo del modelo guardado: %s", exc)
            
            # Si la lectura falla en producción, rompemos el flujo inmediatamente
            if settings.ENVIRONMENT != "development":
                raise RuntimeError(
                    f"❌ ERROR CRÍTICO: No se pudo cargar el modelo Bidirectional-LSTM en producción: {exc}. "
                    f"Verifica la integridad del archivo y las dependencias."
                ) from exc
            
            # Fallback exclusivo para entorno de desarrollo local
            logger.info("Modo Desarrollo: reconstruyendo y reentrenando modelo local...")
            self.model = self._build_model()
            if os.path.exists(CSV_ENTRENAMIENTO_DEFAULT):
                logger.info("Intentando regenerar modelo usando '%s'...", CSV_ENTRENAMIENTO_DEFAULT)
                self.entrenar_con_csv(CSV_ENTRENAMIENTO_DEFAULT)

    # ── Entrenamiento 

    def entrenar_con_csv(self, ruta_archivo: str) -> bool:
        """Entrena con datos reales etiquetados (columnas: voltaje, corriente, frecuencia, anomalia)."""
        if not TF_AVAILABLE or self.model is None:
            logger.error("TensorFlow no disponible. No se puede entrenar.")
            return False
        if not os.path.exists(ruta_archivo):
            logger.error("CSV no encontrado: %s", ruta_archivo)
            return False

        try:
            import pandas as pd
            df = pd.read_csv(ruta_archivo)
            required = {"voltaje", "corriente", "frecuencia", "anomalia"}
            if not required.issubset(df.columns):
                logger.error("El CSV debe contener columnas: %s", required)
                return False

            x_raw = df[self.FEATURES].values.astype(np.float32)
            y_raw = df["anomalia"].values.astype(np.float32)

            X, Y = self._create_sequences(x_raw, y_raw)
            if len(X) == 0:
                logger.error("El CSV tiene menos filas que sequence_length=%d.", self.sequence_length)
                return False

            logger.info("Iniciando entrenamiento LSTM con %d secuencias reales...", len(X))
            self.model.fit(
                X, Y,
                epochs=20,
                batch_size=32,
                validation_split=0.2,
                callbacks=[
                    tf.keras.callbacks.EarlyStopping(patience=3, restore_best_weights=True),
                ],
                verbose=1,
            )
            self._is_ready = True
            self._save_model()
            logger.info("Entrenamiento con CSV completado de forma exitosa.")
            return True
        except Exception as err:
            logger.error("Fallo crítico durante el procesamiento o entrenamiento del CSV: %s", err)
            return False

    # ── Inferencia 

    def predecir(self, datos_entrada: dict[str, Any]) -> dict[str, Any]:
        """
        Procesa una muestra, la agrega al buffer y realiza inferencia cuando la ventana está lista.
        """
        nuevo_dato = [datos_entrada.get(f, 0.0) for f in self.FEATURES]
        self._buffer.append(nuevo_dato)

        if len(self._buffer) < self.sequence_length:
            return {
                "anomalia": False,
                "score": 0.0,
                "tipo": None,
                "confianza": 0.0,
                "mensaje": f"Calibrando LSTM... ({len(self._buffer)}/{self.sequence_length} muestras)",
            }

        if not self._is_ready or self.model is None:
            return {
                "anomalia": False,
                "score": 0.0,
                "tipo": None,
                "confianza": 0.0,
                "mensaje": "Modelo LSTM pendiente de entrenamiento.",
            }

        try:
            input_data = np.array(list(self._buffer), dtype=np.float32).reshape(
                1, self.sequence_length, self.features
            )
            score = float(self.model.predict(input_data, verbose=0)[0][0])
            logger.info(f"DEBUG: Input Vector: {input_data.flatten().tolist()} | Score Calculado: {score}")
            es_anomalia = score > self.threshold

            return {
                "anomalia": es_anomalia,
                "score": round(score, 4),
                "tipo": "ANOMALIA_LSTM" if es_anomalia else None,
                "confianza": round(score if es_anomalia else 1.0 - score, 4),
                "mensaje": (
                    f"Anomalía detectada por LSTM (score={score:.3f})"
                    if es_anomalia
                    else "Patrón eléctrico normal (LSTM)."
                ),
            }
        except Exception as exc:
            logger.error("Error durante inferencia LSTM: %s", exc)
            return {
                "anomalia": False, "score": 0.0,
                "tipo": None, "confianza": 0.0,
                "mensaje": f"Error de inferencia: {exc}",
            }

    def _create_sequences(
        self, x: np.ndarray, y: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Genera ventanas deslizantes (X, Y) para entrenamiento LSTM."""
        X, Y = [], []
        for i in range(len(x) - self.sequence_length):
            X.append(x[i : i + self.sequence_length])
            Y.append(y[i + self.sequence_length])
        return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32)