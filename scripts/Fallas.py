import pandas as pd
import numpy as np

rng = np.random.default_rng(42)

total_filas = 30000
seq_length = 10

voltajes = []
corrientes = []
frecuencias = []
anomalias = []

print(f"Generando {total_filas} registros con patrones realistas...")

generated = 0
state = "normal"
block_remaining = 0
transition_samples = 0
transition_start = {}
target_state = None

def make_normal_block(tamano):
    v = rng.normal(120, 2, tamano)
    c = rng.uniform(10, 80, tamano)
    f = rng.normal(60, 0.3, tamano)
    a = np.zeros(tamano, dtype=int)
    for i in range(1, tamano):
        v[i] = v[i-1] * 0.7 + v[i] * 0.3
        f[i] = f[i-1] * 0.7 + f[i] * 0.3
    return v, c, f, a

SOBREVOLTAJE_VALS = {"v_lo": 135, "v_hi": 150, "c_lo": 10, "c_hi": 80, "f_mu": 60, "f_sigma": 0.3}
BAJO_VOLTAJE_VALS = {"v_lo": 100, "v_hi": 113, "c_lo": 10, "c_hi": 80, "f_mu": 60, "f_sigma": 0.3}
FREC_BAJA_VALS = {"v_mu": 120, "v_sigma": 2, "c_lo": 10, "c_hi": 80, "f_lo": 57, "f_hi": 58.9}
FREC_ALTA_VALS = {"v_mu": 120, "v_sigma": 2, "c_lo": 10, "c_hi": 80, "f_lo": 61.1, "f_hi": 63}
DRIFT_V_BAJO_VALS = {"v_start": 117, "v_end": 114, "c_lo": 10, "c_hi": 80, "f_mu": 60, "f_sigma": 0.3}
DRIFT_FREC_VALS = {"v_mu": 120, "v_sigma": 1.5, "c_lo": 10, "c_hi": 80, "f_start": 60, "f_end": 58.8}
OSCILACION_VALS = {"v_base": 120, "v_amp_start": 0.5, "v_amp_end": 3, "c_lo": 10, "c_hi": 80, "f_mu": 60, "f_sigma": 0.3}
MIXTO_VALS = {"v_lo": 114.5, "v_hi": 116, "c_lo": 10, "c_hi": 80, "f_lo": 58.8, "f_hi": 59.3}

def linear_transition(vals_src, vals_dst, tamano):
    v = np.linspace(vals_src.get("v", 120), vals_dst.get("v", 120), tamano)
    c = np.linspace(vals_src.get("c", 40), vals_dst.get("c", 40), tamano)
    f = np.linspace(vals_src.get("f", 60), vals_dst.get("f", 60), tamano)
    a = np.linspace(vals_src.get("a", 0), vals_dst.get("a", 1), tamano)
    a = (a > 0.5).astype(int)
    noise_v = rng.normal(0, 0.5, tamano)
    noise_c = rng.normal(0, 1, tamano)
    noise_f = rng.normal(0, 0.1, tamano)
    return v + noise_v, c + noise_c, f + noise_f, a

anomaly_types = [
    "sobrevoltaje", "bajo_voltaje", "frecuencia_baja", "frecuencia_alta",
    "pre_drift_bajo", "pre_drift_frec", "pre_oscilacion", "pre_mixto"
]

while generated < total_filas:
    remaining = total_filas - generated

    if state == "normal":
        block_size = min(rng.integers(8, 30), remaining - 4 if remaining > 4 else remaining)
        if block_size < 1:
            break
        v, c, f, a = make_normal_block(block_size)
        voltajes.extend(v); corrientes.extend(c); frecuencias.extend(f); anomalias.extend(a)
        generated += block_size
        state = "anomaly"
    else:
        tipo = rng.choice(anomaly_types)
        fault_size = min(rng.integers(5, 20), remaining - 8 if remaining > 8 else remaining)
        if fault_size < 4:
            break

        transition_size = min(rng.integers(4, 8), fault_size // 2)
        steady_size = fault_size - transition_size * 2

        if steady_size < 1:
            transition_size = max(1, fault_size // 3)
            steady_size = fault_size - transition_size * 2
            if steady_size < 1:
                steady_size = 0
                transition_size = fault_size // 2

        src_info = {"v": 120, "c": 40, "f": 60, "a": 0}

        if tipo == "sobrevoltaje":
            dst_info = {"v": rng.uniform(135, 145), "c": rng.uniform(30, 70), "f": 60, "a": 1}
        elif tipo == "bajo_voltaje":
            dst_info = {"v": rng.uniform(100, 113), "c": rng.uniform(30, 70), "f": 60, "a": 1}
        elif tipo == "frecuencia_baja":
            dst_info = {"v": 120, "c": rng.uniform(30, 70), "f": rng.uniform(57, 58.8), "a": 1}
        elif tipo == "frecuencia_alta":
            dst_info = {"v": 120, "c": rng.uniform(30, 70), "f": rng.uniform(61.2, 63), "a": 1}
        elif tipo == "pre_drift_bajo":
            dst_info = {"v": rng.uniform(114, 116), "c": rng.uniform(30, 70), "f": 60, "a": 1}
        elif tipo == "pre_drift_frec":
            dst_info = {"v": 120, "c": rng.uniform(30, 70), "f": rng.uniform(58.8, 59.2), "a": 1}
        elif tipo == "pre_oscilacion":
            v_vals = 120 + np.cumsum(rng.normal(0, 0.08, fault_size))
            c = rng.uniform(30, 70, fault_size)
            f = rng.normal(60, 0.3, fault_size)
            a = np.ones(fault_size, dtype=int)
            voltajes.extend(v_vals); corrientes.extend(c); frecuencias.extend(f); anomalias.extend(a)
            generated += fault_size
            state = "normal"
            continue
        elif tipo == "pre_mixto":
            dst_info = {"v": rng.uniform(114.5, 116), "f": rng.uniform(58.8, 59.3), "c": rng.uniform(30, 70), "a": 1}

        v_trans, c_trans, f_trans, a_trans = linear_transition(src_info, dst_info, transition_size)
        voltajes.extend(v_trans); corrientes.extend(c_trans); frecuencias.extend(f_trans); anomalias.extend(a_trans)

        if steady_size > 0:
            if tipo == "sobrevoltaje":
                v = rng.uniform(SOBREVOLTAJE_VALS["v_lo"], SOBREVOLTAJE_VALS["v_hi"], steady_size)
                c = rng.uniform(SOBREVOLTAJE_VALS["c_lo"], SOBREVOLTAJE_VALS["c_hi"], steady_size)
                f = rng.normal(SOBREVOLTAJE_VALS["f_mu"], SOBREVOLTAJE_VALS["f_sigma"], steady_size)
            elif tipo == "bajo_voltaje":
                v = rng.uniform(BAJO_VOLTAJE_VALS["v_lo"], BAJO_VOLTAJE_VALS["v_hi"], steady_size)
                c = rng.uniform(BAJO_VOLTAJE_VALS["c_lo"], BAJO_VOLTAJE_VALS["c_hi"], steady_size)
                f = rng.normal(BAJO_VOLTAJE_VALS["f_mu"], BAJO_VOLTAJE_VALS["f_sigma"], steady_size)
            elif tipo == "frecuencia_baja":
                v = rng.normal(FREC_BAJA_VALS["v_mu"], FREC_BAJA_VALS["v_sigma"], steady_size)
                c = rng.uniform(FREC_BAJA_VALS["c_lo"], FREC_BAJA_VALS["c_hi"], steady_size)
                f = rng.uniform(FREC_BAJA_VALS["f_lo"], FREC_BAJA_VALS["f_hi"], steady_size)
            elif tipo == "frecuencia_alta":
                v = rng.normal(FREC_ALTA_VALS["v_mu"], FREC_ALTA_VALS["v_sigma"], steady_size)
                c = rng.uniform(FREC_ALTA_VALS["c_lo"], FREC_ALTA_VALS["c_hi"], steady_size)
                f = rng.uniform(FREC_ALTA_VALS["f_lo"], FREC_ALTA_VALS["f_hi"], steady_size)
            elif tipo == "pre_drift_bajo":
                ramp = np.linspace(dst_info["v"], DRIFT_V_BAJO_VALS["v_end"], steady_size)
                v = ramp + rng.normal(0, 0.5, steady_size)
                c = rng.uniform(DRIFT_V_BAJO_VALS["c_lo"], DRIFT_V_BAJO_VALS["c_hi"], steady_size)
                f = rng.normal(DRIFT_V_BAJO_VALS["f_mu"], DRIFT_V_BAJO_VALS["f_sigma"], steady_size)
            elif tipo == "pre_drift_frec":
                ramp = np.linspace(dst_info["f"], DRIFT_FREC_VALS["f_end"], steady_size)
                f = ramp + rng.normal(0, 0.05, steady_size)
                v = rng.normal(DRIFT_FREC_VALS["v_mu"], DRIFT_FREC_VALS["v_sigma"], steady_size)
                c = rng.uniform(DRIFT_FREC_VALS["c_lo"], DRIFT_FREC_VALS["c_hi"], steady_size)
            elif tipo == "pre_mixto":
                v = rng.uniform(MIXTO_VALS["v_lo"], MIXTO_VALS["v_hi"], steady_size)
                c = rng.uniform(MIXTO_VALS["c_lo"], MIXTO_VALS["c_hi"], steady_size)
                f = rng.uniform(MIXTO_VALS["f_lo"], MIXTO_VALS["f_hi"], steady_size)
            else:
                v = rng.normal(120, 2, steady_size)
                c = rng.uniform(10, 80, steady_size)
                f = rng.normal(60, 0.3, steady_size)
            a = np.ones(steady_size, dtype=int)

            voltajes.extend(v); corrientes.extend(c); frecuencias.extend(f); anomalias.extend(a)
            generated += steady_size

        dst_normal = {"v": 120, "c": 40, "f": 60, "a": 0}
        v_trans2, c_trans2, f_trans2, a_trans2 = linear_transition(dst_info, dst_normal, transition_size)
        voltajes.extend(v_trans2); corrientes.extend(c_trans2); frecuencias.extend(f_trans2); anomalias.extend(a_trans2)
        generated += transition_size * 2

        state = "normal"

voltajes_arr = np.array(voltajes[:total_filas])
corrientes_arr = np.array(corrientes[:total_filas])
frecuencias_arr = np.array(frecuencias[:total_filas])
anomalias_arr = np.array(anomalias[:total_filas], dtype=int)

noise_mask = rng.random(total_filas) < 0.01
voltajes_arr[noise_mask] += rng.normal(0, 5, noise_mask.sum())
corrientes_arr[noise_mask] += rng.normal(0, 8, noise_mask.sum())
frecuencias_arr[noise_mask] += rng.normal(0, 0.5, noise_mask.sum())

voltajes_arr = np.clip(voltajes_arr, 90, 155)
corrientes_arr = np.clip(corrientes_arr, 0, 85)
frecuencias_arr = np.clip(frecuencias_arr, 55, 65)

df_final = pd.DataFrame({
    'voltaje': np.round(voltajes_arr, 2),
    'corriente': np.round(corrientes_arr, 2),
    'frecuencia': np.round(frecuencias_arr, 2),
    'anomalia': anomalias_arr
})

normales = (df_final['anomalia'] == 0).sum()
fallas = (df_final['anomalia'] == 1).sum()
borderline = df_final[(df_final['anomalia'] == 1) & (df_final['voltaje'] > 113) & (df_final['voltaje'] < 135) & (df_final['frecuencia'] > 58.9) & (df_final['frecuencia'] < 61.1)].shape[0]

df_final.to_csv('dataset_entrenamiento.csv', index=False)

print(f"\nDataset generado: {len(df_final)} registros ({normales} normales / {fallas} anomalias)")
print(f"  - Anomalias detectables por reglas: {fallas - borderline}")
print(f"  - Anomalias borderline (solo LSTM): {borderline}")
print(f"Guardado como: dataset_entrenamiento.csv")
