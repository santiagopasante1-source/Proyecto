import pandas as pd
import numpy as np

# Configurar generador aleatorio para reproducibilidad académica
rng = np.random.default_rng(42)

total_filas = 20000
tamano_bloque = 100  # Cada bloque representa una ventana temporal continua de 100 lecturas
num_bloques = total_filas // tamano_bloque  # 60 bloques en total

voltajes = []
corrientes = []
frecuencias = []
anomalias = []

print(f"Generando {total_filas} registros estructurados en {num_bloques} bloques temporales continuos...")

for b in range(num_bloques):
    # Alternamos de forma balanceada: bloques pares son estables, impares son fallas (50% / 50%)
    es_falla = (b % 2 != 0)
    
    if not es_falla:
        # ── BLOQUE NORMAL (Lecturas consecutivas estables) ──
        v = rng.normal(120.0, 1.2, tamano_bloque)
        c = rng.normal(10.0, 0.8, tamano_bloque)
        f = rng.normal(60.0, 0.04, tamano_bloque)
        a = np.zeros(tamano_bloque, dtype=int)
    else:
        # ── BLOQUE DE FALLA (El sistema entra en una anomalía sostenida) ──
        tipo_falla = rng.choice(['sobretension', 'bajo_voltaje', 'sobrecarga', 'ruido_frecuencia'])
        
        if tipo_falla == 'sobretension':
            v = rng.normal(195.0, 6.0, tamano_bloque)
            c = rng.normal(8.0, 1.0, tamano_bloque)
            f = rng.normal(60.0, 0.1, tamano_bloque)
        elif tipo_falla == 'bajo_voltaje':
            v = rng.normal(65.0, 5.0, tamano_bloque)
            c = rng.normal(3.5, 0.6, tamano_bloque)
            f = rng.normal(60.0, 0.1, tamano_bloque)
        elif tipo_falla == 'sobrecarga':
            v = rng.normal(116.0, 2.0, tamano_bloque)
            c = rng.normal(78.0, 5.0, tamano_bloque)
            f = rng.normal(60.0, 0.1, tamano_bloque)
        else:  # ruido_frecuencia
            v = rng.normal(120.0, 1.5, tamano_bloque)
            c = rng.normal(10.0, 0.8, tamano_bloque)
            f = rng.normal(68.5, 1.8, tamano_bloque)
            
        a = np.ones(tamano_bloque, dtype=int)
        
    voltajes.extend(v)
    corrientes.extend(c)
    frecuencias.extend(f)
    anomalias.extend(a)

# Construir el DataFrame conservando el orden de los bloques temporales
df_final = pd.DataFrame({
    'voltaje': np.round(voltajes, 2),
    'corriente': np.round(corrientes, 2),
    'frecuencia': np.round(frecuencias, 2),
    'anomalia': anomalias
})

# Guardar el archivo en la raíz del proyecto
df_final.to_csv('dataset_entrenamiento.csv', index=False)

print("\n========================================================")
print("¡NUEVO DATASET CRONOLÓGICO GENERADO CON ÉXITO!")
print("Archivo guardado como: dataset_entrenamiento.csv")
print(f"Total registros: {len(df_final)} (10000 Normales / 10000 Fallas en continuidad)")
print("========================================================")