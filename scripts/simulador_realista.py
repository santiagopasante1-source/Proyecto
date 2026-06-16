"""
scripts/simulador_realista.py
──────────────────────────────
Simulador de datos eléctricos realistas para pruebas del sistema.
Envía registros al endpoint POST /api/v1/telemetry a intervalos configurables.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time
from datetime import datetime

import requests

# ── Parámetros eléctricos de referencia (ANSI C84.1 / 120 V / 60 Hz) ─────────

VOLTAJE_NOMINAL = 120.0
CORRIENTE_NOMINAL = 10.0
FRECUENCIA_NOMINAL = 60.0

# Tipos de anomalía con probabilidades
ANOMALY_TYPES = {
    "normal":          0.80,   # Operación normal
    "apagon":          0.02,   # Corte total — V~[0-3V], I~[0-0.3A]
    "microcorte":      0.03,   # Voltaje cae < 80 V por < 1 ciclo
    "sobrevoltaje":    0.04,   # V > 253 V (norma IEC)
    "bajo_voltaje":    0.04,   # V < 108 V (fuera de rango ANSI)
    "sobrecorriente":  0.03,   # I > 80 A — posible corto
    "frecuencia_baja": 0.02,   # f < 59 Hz — sobrecarga del generador
    "frecuencia_alta": 0.02,   # f > 61 Hz — carga mínima
}

# Colores ANSI para consola
RESET  = "\033[0m"
RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
GRAY   = "\033[90m"
BOLD   = "\033[1m"


def generate_sample(t: float, anomaly_type: str) -> dict:
    """Genera una muestra eléctrica realista con ruido y derivación temporal."""
    noise_v = random.gauss(0, 1.5)   # Ruido blanco en voltaje
    noise_i = random.gauss(0, 0.3)   # Ruido blanco en corriente
    drift_f = math.sin(t / 30) * 0.1  # Deriva cíclica de frecuencia

    v = VOLTAJE_NOMINAL + noise_v
    i = CORRIENTE_NOMINAL + noise_i
    f = FRECUENCIA_NOMINAL + drift_f

    if anomaly_type == "apagon":
        v = random.uniform(0, 3)
        i = random.uniform(0, 0.3)
        f = random.uniform(0, 2)
    elif anomaly_type == "microcorte":
        v = random.uniform(50, 85)
    elif anomaly_type == "sobrevoltaje":
        v = random.uniform(255, 290)
    elif anomaly_type == "bajo_voltaje":
        v = random.uniform(90, 107)
    elif anomaly_type == "sobrecorriente":
        i = random.uniform(80, 150)
        v = v * random.uniform(0.92, 0.98)  # caída de voltaje por carga
    elif anomaly_type == "frecuencia_baja":
        f = random.uniform(57.5, 59.0)
    elif anomaly_type == "frecuencia_alta":
        f = random.uniform(61.1, 62.5)

    return {
        "voltaje":   round(max(0.0, v), 4),
        "corriente": round(max(0.0, i), 4),
        "frecuencia": round(f, 4),
    }


def pick_anomaly_type() -> str:
    """Selecciona el tipo de evento según la distribución de probabilidades."""
    r = random.random()
    cumulative = 0.0
    for tipo, prob in ANOMALY_TYPES.items():
        cumulative += prob
        if r <= cumulative:
            return tipo
    return "normal"


def send_sample(host: str, device_id: int, sample: dict) -> dict | None:
    payload = {
        "dispositivo_id": device_id,
        **sample,
    }
    try:
        r = requests.post(f"{host}/api/v1/telemetry", json=payload, timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        print(f"{RED}✗ Sin conexión al backend en {host}{RESET}")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"{YELLOW}⚠ HTTP {e.response.status_code}: {e.response.text[:120]}{RESET}")
        return None
    except Exception as e:
        print(f"{RED}✗ Error inesperado: {e}{RESET}")
        return None


def print_result(sample: dict, anomaly_type: str, resultado: dict | None) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    v, i, f = sample["voltaje"], sample["corriente"], sample.get("frecuencia", 0)
    reading = f"V={v:6.1f}  A={i:5.2f}  Hz={f:5.2f}"

    if resultado is None:
        print(f"{GRAY}[{ts}] {reading}  →  sin respuesta{RESET}")
        return

    ia = resultado.get("ia_resultado", {})
    is_anomaly = ia.get("anomalia", False)
    score = ia.get("score", 0.0)
    tipo_ia = ia.get("tipo") or "—"

    if is_anomaly:
        color = RED if score > 0.85 else YELLOW
        flag = "⚠  ANOMALÍA"
    else:
        color = GREEN
        flag = "✓  Normal  "

    label = f"[{anomaly_type.upper():16s}]" if anomaly_type != "normal" else f"[{'normal':16s}]"
    print(f"{GRAY}[{ts}]{RESET} {reading}  {color}{flag}  score={score:.3f}  {tipo_ia}{RESET}  {GRAY}{label}{RESET}")


def run(host: str, device_id: int, interval: float, max_samples: int) -> None:
    print(f"\n{BOLD}{CYAN}━━━  Simulador IoT Realista (Sustentado)  ━━━{RESET}")
    print(f"  Backend : {host}")
    print(f"  Dispositivo ID: {device_id}")
    print(f"  Intervalo: {interval}s")
    print(f"  Muestras: {'∞' if max_samples == 0 else max_samples}")
    print(f"{CYAN}{'─' * 70}{RESET}\n")

    sent = 0
    t = 0.0
    
    # Variables de control para la persistencia del estado temporal
    estado_actual = "normal"
    muestras_restantes_estado = 0

    try:
        while max_samples == 0 or sent < max_samples:
            # Si el estado terminó su duración, elegimos el siguiente bloque de datos
            if muestras_restantes_estado <= 0:
                estado_actual = pick_anomaly_type()
                if estado_actual == "normal":
                    # Los bloques normales duran un tiempo corto antes de volver a evaluar
                    muestras_restantes_estado = random.randint(3, 7)
                else:
                    # Las anomalías se mantienen de 8 a 15 pasos continuos para llenar la ventana LSTM (10)
                    muestras_restantes_estado = random.randint(8, 15)

            # Reducir el contador del bloque actual
            muestras_restantes_estado -= 1

            sample = generate_sample(t, estado_actual)
            resultado = send_sample(host, device_id, sample)
            print_result(sample, estado_actual, resultado)
            
            sent += 1
            t += interval
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print(f"\n{CYAN}Simulador detenido. {sent} muestras enviadas.{RESET}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador de telemetría IoT")
    parser.add_argument("--host",     default="http://localhost:8000", help="URL del backend FastAPI")
    parser.add_argument("--device",   type=int, default=1,             help="ID del dispositivo")
    parser.add_argument("--interval", type=float, default=3,           help="Segundos entre envíos")
    parser.add_argument("--max",      type=int, default=0,             help="Máximo de muestras (0 = infinito)")
    args = parser.parse_args()
    run(args.host, args.device, args.interval, args.max)


if __name__ == "__main__":
    main()