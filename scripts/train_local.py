"""
scripts/train_local.py
──────────────────────
Script optimizado para correr dentro de una subcarpeta de scripts.
Detecta la raíz del proyecto de forma dinámica para no romper las rutas.
"""
import os
import numpy as np
import pandas as pd
import tensorflow as tf

# ── DETECCIÓN DINÁMICA DE LA RAÍZ DEL PROYECTO ──────────────────────────────
# __file__ es la posición de este script. Su padre es 'scripts/'. 
# El padre de su padre es la raíz del proyecto.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)

# Configuramos las rutas apuntando siempre a la raíz del proyecto
CSV_PATH = os.path.join(BASE_DIR, "dataset_entrenamiento.csv")
MODEL_SAVE_PATH = os.path.join(BASE_DIR, "models", "lstm_anomaly_detector.keras")

SEQUENCE_LENGTH = 10
FEATURES = ["voltaje", "corriente", "frecuencia"]

def preparar_secuencias(x_data, y_data, seq_length):
    X, Y = [], []
    for i in range(len(x_data) - seq_length):
        X.append(x_data[i : i + seq_length])
        Y.append(y_data[i + seq_length])
    return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32)

def generar_keras_desde_csv():
    # 1. Validar y leer el archivo CSV en la raíz
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(
            f"❌ No se encontró el archivo '{CSV_PATH}'.\n"
            f"Asegúrate de que tu dataset esté en la raíz del proyecto."
        )
    
    print(f"Leyendo datos desde: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH)
    
    columnas_necesarias = set(FEATURES + ["anomalia"])
    if not columnas_necesarias.issubset(df.columns):
        raise ValueError(f"❌ El CSV debe contener las columnas: {columnas_necesarias}")

    # 2. Preparar muestras
    x_raw = df[FEATURES].values.astype(np.float32)
    y_raw = df["anomalia"].values.astype(np.float32)
    
    X, Y = preparar_secuencias(x_raw, y_raw, SEQUENCE_LENGTH)
    print(f"Dataset convertido en {len(X)} secuencias de tiempo.")

    # 3. Arquitectura compacta y ligera
    print("Disenando red neuronal Bidirectional-LSTM compacta...")
    model = tf.keras.Sequential([
        tf.keras.layers.Bidirectional(
            tf.keras.layers.LSTM(32, return_sequences=True), 
            input_shape=(SEQUENCE_LENGTH, len(FEATURES)),
        ),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.LSTM(16),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(8, activation="relu"),
        tf.keras.layers.Dense(1, activation="sigmoid"),
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="binary_crossentropy",
        metrics=["accuracy"]
    )

    # 4. Entrenamiento
    print("Entrenando modelo...")
    model.fit(
        X, Y,
        epochs=8,
        batch_size=64,
        validation_split=0.1,
        verbose=1
    )

    # 5. Exportar a la carpeta /models en la raíz
    os.makedirs(os.path.dirname(MODEL_SAVE_PATH), exist_ok=True)
    model.save(MODEL_SAVE_PATH)
    print(f"\n✅ ¡Éxito total! Archivo .keras generado en: '{MODEL_SAVE_PATH}'")

if __name__ == "__main__":
    generar_keras_desde_csv()