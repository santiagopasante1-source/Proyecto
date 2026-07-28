import os
import sys
import numpy as np
import pandas as pd
import tensorflow as tf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)

CSV_PATH = os.path.join(BASE_DIR, "dataset_entrenamiento.csv")
H5_PATH = os.path.join(BASE_DIR, "models", "lstm_anomaly_detector.h5")
KERAS_PATH = os.path.join(BASE_DIR, "models", "lstm_anomaly_detector.keras")

SEQUENCE_LENGTH = 10
FEATURES = ["voltaje", "corriente", "frecuencia"]
EPOCHS = 30
BATCH_SIZE = 64
TRAIN_SPLIT = 0.7
VAL_SPLIT = 0.15
PATIENCE = 5

def preparar_secuencias(x, y, seq_length):
    X, Y = [], []
    for i in range(len(x) - seq_length):
        X.append(x[i : i + seq_length])
        Y.append(y[i + seq_length])
    return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32)

def entrenar():
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: No se encontro {CSV_PATH}")
        sys.exit(1)

    print(f"Leyendo datos desde: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH)
    print(f"Filas: {len(df)}, Anomalias: {df['anomalia'].sum()} ({df['anomalia'].mean()*100:.1f}%)")

    x_raw = df[FEATURES].values.astype(np.float32)
    y_raw = df["anomalia"].values.astype(np.float32)

    X, Y = preparar_secuencias(x_raw, y_raw, SEQUENCE_LENGTH)
    print(f"Secuencias generadas: {len(X)} (ventana={SEQUENCE_LENGTH})")

    # Shuffle antes de partir para mezclar normales/anomalias
    indices = np.random.permutation(len(X))
    X, Y = X[indices], Y[indices]

    n_total = len(X)
    n_train = int(TRAIN_SPLIT * n_total)
    n_val = int(VAL_SPLIT * n_total)

    X_train = X[:n_train]
    X_val = X[n_train:n_train + n_val]
    X_test = X[n_train + n_val:]
    Y_train = Y[:n_train]
    Y_val = Y[n_train:n_train + n_val]
    Y_test = Y[n_train + n_val:]

    print(f"Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")
    print(f"  Train anomalias: {Y_train.sum():.0f}, Val anomalias: {Y_val.sum():.0f}, Test anomalias: {Y_test.sum():.0f}")

    print("Construyendo modelo Bi-LSTM (LSTM(64) -> LSTM(32) -> Dense(16))...")
    model = tf.keras.Sequential([
        tf.keras.layers.Bidirectional(
            tf.keras.layers.LSTM(64, return_sequences=True),
            input_shape=(SEQUENCE_LENGTH, len(FEATURES)),
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

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=PATIENCE, restore_best_weights=True, verbose=1
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=3, min_lr=1e-6, verbose=1
        ),
    ]

    print(f"Entrenando (max {EPOCHS} epochs, early stopping patience={PATIENCE})...")
    history = model.fit(
        X_train, Y_train,
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        validation_data=(X_val, Y_val),
        callbacks=callbacks,
        verbose=1,
    )

    print("\n--- Evaluacion en validation set ---")
    loss, acc, auc = model.evaluate(X_val, Y_val, verbose=0)
    print(f"Loss: {loss:.4f}")
    print(f"Accuracy: {acc:.4f}")
    print(f"AUC: {auc:.4f}")

    Y_pred = model.predict(X_val, verbose=0).flatten()

    thresholds = np.arange(0.3, 0.99, 0.01)
    best_f1 = 0
    best_threshold = 0.9
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

    print("\n--- Evaluacion en test set (15% no visto durante entrenamiento) ---")
    test_loss, test_acc, test_auc = model.evaluate(X_test, Y_test, verbose=0)
    print(f"Test Loss: {test_loss:.4f}")
    print(f"Test Accuracy: {test_acc:.4f}")
    print(f"Test AUC: {test_auc:.4f}")

    Y_pred_test = model.predict(X_test, verbose=0).flatten()
    preds_test = (Y_pred_test > best_threshold).astype(int)
    tp_test = ((preds_test == 1) & (Y_test == 1)).sum()
    fp_test = ((preds_test == 1) & (Y_test == 0)).sum()
    fn_test = ((preds_test == 0) & (Y_test == 1)).sum()
    precision_test = tp_test / (tp_test + fp_test) if (tp_test + fp_test) > 0 else 0
    recall_test = tp_test / (tp_test + fn_test) if (tp_test + fn_test) > 0 else 0
    f1_test = 2 * precision_test * recall_test / (precision_test + recall_test) if (precision_test + recall_test) > 0 else 0
    print(f"Test Precision: {precision_test:.4f}")
    print(f"Test Recall:    {recall_test:.4f}")
    print(f"Test F1-score:  {f1_test:.4f}")

    modelo_con_threshold = tf.keras.Sequential([
        model,
        tf.keras.layers.Lambda(lambda x: tf.cast(x > best_threshold, tf.float32))
    ])
    modelo_con_threshold.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="binary_crossentropy",
    )

    os.makedirs(os.path.dirname(H5_PATH), exist_ok=True)
    model.save(H5_PATH)
    print(f"\nModelo guardado: {H5_PATH}")

    model.save(KERAS_PATH)
    print(f"Modelo guardado: {KERAS_PATH}")

    import json
    meta = {
        "threshold": float(best_threshold),
        "f1_val": float(best_f1),
        "precision_val": float(best_metrics["precision"]),
        "recall_val": float(best_metrics["recall"]),
        "accuracy_val": float(acc),
        "auc_val": float(auc),
        "f1_test": float(f1_test),
        "precision_test": float(precision_test),
        "recall_test": float(recall_test),
        "accuracy_test": float(test_acc),
        "auc_test": float(test_auc),
        "samples": len(df),
        "sequences": len(X),
        "epochs_completed": len(history.history["loss"]),
    }
    meta_path = os.path.join(os.path.dirname(H5_PATH), "training_metrics.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metricas guardadas: {meta_path}")
    print("\nEntrenamiento completado exitosamente.")

if __name__ == "__main__":
    entrenar()
