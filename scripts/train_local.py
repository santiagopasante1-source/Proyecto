import json
import os
import sys
import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.preprocessing import MinMaxScaler
from sklearn.utils.class_weight import compute_class_weight
import joblib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)

CSV_PATH = os.path.join(BASE_DIR, "dataset_entrenamiento.csv")
H5_PATH = os.path.join(BASE_DIR, "models", "lstm_anomaly_detector.h5")
KERAS_PATH = os.path.join(BASE_DIR, "models", "lstm_anomaly_detector.keras")
SCALER_PATH = os.path.join(BASE_DIR, "models", "scaler.pkl")

SEQUENCE_LENGTH = 10
FEATURES = ["voltaje", "corriente", "frecuencia"]
EPOCHS = 30
BATCH_SIZE = 64
VALIDATION_SPLIT = 0.2
PATIENCE = 5

def preparar_secuencias(x, y, seq_length):
    X, Y = [], []
    for i in range(len(x) - seq_length):
        X.append(x[i : i + seq_length])
        Y.append(y[i + seq_length])
    return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32)

def entrenar():
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

    if not os.path.exists(CSV_PATH):
        print(f"ERROR: No se encontro {CSV_PATH}")
        sys.exit(1)

    print(f"Leyendo datos desde: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH)
    total_anom = int(df["anomalia"].sum())
    print(f"Filas: {len(df)}, Anomalias: {total_anom} ({df['anomalia'].mean()*100:.1f}%)")

    # Split temporal: primeras 80% train, últimas 20% val (sin shuffle)
    split_idx = int(len(df) * (1 - VALIDATION_SPLIT))
    df_train = df.iloc[:split_idx].copy()
    df_val = df.iloc[split_idx:].copy()
    print(f"\nSplit temporal: train={len(df_train)} filas, val={len(df_val)} filas")
    print(f"  Train anomalias: {int(df_train['anomalia'].sum())} ({df_train['anomalia'].mean()*100:.1f}%)")
    print(f"  Val anomalias:   {int(df_val['anomalia'].sum())} ({df_val['anomalia'].mean()*100:.1f}%)")

    # Escalado: fit SOLO en train, transform ambos
    scaler = MinMaxScaler()
    x_train_scaled = scaler.fit_transform(df_train[FEATURES].values.astype(np.float32))
    x_val_scaled = scaler.transform(df_val[FEATURES].values.astype(np.float32))

    os.makedirs(os.path.dirname(SCALER_PATH), exist_ok=True)
    joblib.dump(scaler, SCALER_PATH)
    print(f"Scaler guardado: {SCALER_PATH}")
    print(f"  Rangos: V=[{scaler.data_min_[0]:.1f}, {scaler.data_max_[0]:.1f}], "
          f"I=[{scaler.data_min_[1]:.1f}, {scaler.data_max_[1]:.1f}], "
          f"F=[{scaler.data_min_[2]:.1f}, {scaler.data_max_[2]:.1f}]")

    # Generar secuencias
    X_train, Y_train = preparar_secuencias(x_train_scaled, df_train["anomalia"].values.astype(np.float32), SEQUENCE_LENGTH)
    X_val, Y_val = preparar_secuencias(x_val_scaled, df_val["anomalia"].values.astype(np.float32), SEQUENCE_LENGTH)
    print(f"Secuencias: train={len(X_train)}, val={len(X_val)} (ventana={SEQUENCE_LENGTH})")

    # Pesos por clase para balancear la loss
    clases = np.array([0, 1])
    pesos = compute_class_weight("balanced", classes=clases, y=df_train["anomalia"].values)
    peso_dict = {0: float(pesos[0]), 1: float(pesos[1])}
    print(f"Pesos por clase: normal={peso_dict[0]:.2f}, anomalia={peso_dict[1]:.2f}")

    print("\nConstruyendo modelo Bi-LSTM (LSTM(64, Bi) -> LSTM(32) -> Dense(16) -> sigmoid)...")
    model = tf.keras.Sequential([
        tf.keras.layers.Bidirectional(
            tf.keras.layers.LSTM(64, return_sequences=True),
            input_shape=(SEQUENCE_LENGTH, len(FEATURES)),
        ),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.LSTM(32),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(16, activation="relu"),
        tf.keras.layers.Dense(1, activation="sigmoid"),
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="binary_crossentropy",
        metrics=["accuracy", tf.keras.metrics.AUC(name="auc")],
    )

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=PATIENCE, restore_best_weights=True, verbose=1
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=3, min_lr=1e-6, verbose=1
        ),
    ]

    print(f"Entrenando (max {EPOCHS} epochs)...")
    history = model.fit(
        X_train, Y_train,
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        validation_data=(X_val, Y_val),
        class_weight=peso_dict,
        callbacks=callbacks,
        verbose=1,
    )

    print("\n--- Evaluacion en validation set ---")
    loss, acc, auc = model.evaluate(X_val, Y_val, verbose=0)
    print(f"Loss: {loss:.4f}, Accuracy: {acc:.4f}, AUC: {auc:.4f}")

    Y_pred = model.predict(X_val, verbose=0).flatten()

    # Grid search de threshold optimizando F1
    thresholds = np.arange(0.05, 0.99, 0.01)
    best_f1 = 0
    best_threshold = 0.5
    best_metrics = {}

    for thresh in thresholds:
        preds = (Y_pred > thresh).astype(int)
        tp = ((preds == 1) & (Y_val == 1)).sum()
        fp = ((preds == 1) & (Y_val == 0)).sum()
        fn = ((preds == 0) & (Y_val == 1)).sum()
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = thresh
            best_metrics = {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}

    print(f"\nMejor threshold: {best_threshold:.2f} (F1={best_f1:.4f})")
    print(f"  Precision: {best_metrics['precision']:.4f}")
    print(f"  Recall:    {best_metrics['recall']:.4f}")
    print(f"  F1-score:  {best_metrics['f1']:.4f}")
    print(f"  TP: {best_metrics['tp']}, FP: {best_metrics['fp']}, FN: {best_metrics['fn']}")

    # Guardar modelo
    os.makedirs(os.path.dirname(H5_PATH), exist_ok=True)
    model.save(H5_PATH)
    print(f"\nModelo guardado: {H5_PATH}")

    model.save(KERAS_PATH)
    print(f"Modelo guardado: {KERAS_PATH}")

    meta = {
        "threshold": float(best_threshold),
        "f1": float(best_f1),
        "precision": float(best_metrics["precision"]),
        "recall": float(best_metrics["recall"]),
        "accuracy": float(acc),
        "auc": float(auc),
        "samples": len(df),
        "train_samples": len(df_train),
        "val_samples": len(df_val),
        "sequences": len(X_train) + len(X_val),
        "epochs_completed": len(history.history["loss"]),
        "class_weights": {"normal": peso_dict[0], "anomaly": peso_dict[1]},
        "scaler_path": "models/scaler.pkl",
        "feature_ranges": {
            "voltaje": {"min": float(scaler.data_min_[0]), "max": float(scaler.data_max_[0])},
            "corriente": {"min": float(scaler.data_min_[1]), "max": float(scaler.data_max_[1])},
            "frecuencia": {"min": float(scaler.data_min_[2]), "max": float(scaler.data_max_[2])},
        },
    }
    meta_path = os.path.join(os.path.dirname(H5_PATH), "training_metrics.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metricas guardadas: {meta_path}")
    print("\nEntrenamiento completado exitosamente.")

if __name__ == "__main__":
    entrenar()
