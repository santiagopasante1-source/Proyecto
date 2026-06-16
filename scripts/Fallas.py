import pandas as pd
import numpy as np

rng = np.random.default_rng(42)

total_filas = 20000

voltajes = []
corrientes = []
frecuencias = []
anomalias = []

print(f"Generando {total_filas} registros con rangos reales ESP32...")

generated = 0
block_idx = 0
while generated < total_filas:
    es_anomalia = (block_idx % 2 != 0)

    if es_anomalia:
        tamano = min(rng.integers(8, 13), total_filas - generated)
        tipo = rng.choice(['sobrevoltaje', 'bajo_voltaje', 'frecuencia_baja', 'frecuencia_alta', 'apagon'])

        if tipo == 'sobrevoltaje':
            v = rng.uniform(135, 150, tamano)
            c = rng.uniform(10, 80, tamano)
            f = rng.normal(60, 0.3, tamano)
        elif tipo == 'bajo_voltaje':
            v = rng.uniform(100, 113, tamano)
            c = rng.uniform(10, 80, tamano)
            f = rng.normal(60, 0.3, tamano)
        elif tipo == 'frecuencia_baja':
            v = rng.normal(120, 2, tamano)
            c = rng.uniform(10, 80, tamano)
            f = rng.uniform(57, 58.9, tamano)
        elif tipo == 'frecuencia_alta':
            v = rng.normal(120, 2, tamano)
            c = rng.uniform(10, 80, tamano)
            f = rng.uniform(61.1, 63, tamano)
        else:  # apagon
            v = rng.normal(0, 1, tamano)
            c = rng.normal(0, 1, tamano)
            f = rng.normal(0, 1, tamano)

        a = np.ones(tamano, dtype=int)
    else:
        tamano = min(rng.integers(10, 16), total_filas - generated)
        v = rng.normal(120, 2, tamano)
        c = rng.uniform(10, 80, tamano)
        f = rng.normal(60, 0.3, tamano)
        a = np.zeros(tamano, dtype=int)

    voltajes.extend(v)
    corrientes.extend(c)
    frecuencias.extend(f)
    anomalias.extend(a)

    generated += tamano
    block_idx += 1

df_final = pd.DataFrame({
    'voltaje': np.round(voltajes, 2),
    'corriente': np.round(corrientes, 2),
    'frecuencia': np.round(frecuencias, 2),
    'anomalia': anomalias
})

df_final.to_csv('dataset_entrenamiento.csv', index=False)

normales = (df_final['anomalia'] == 0).sum()
fallas = (df_final['anomalia'] == 1).sum()
print(f"\nDataset generado: {len(df_final)} registros ({normales} normales / {fallas} anomalias)")
print("Guardado como: dataset_entrenamiento.csv")
