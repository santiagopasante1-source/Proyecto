#ifndef CONFIG_H
#define CONFIG_H

// ─── WiFi ─────────────────────────────────────────────────
const char* WIFI_SSID      = "TP-Link_24C4";
const char* WIFI_PASSWORD  = "tu_contraseña_wifi";

// ─── API ───────────────────────────────────────────────────
const char* API_BASE_URL   = "https://deep-learning-production.up.railway.app";
const int   DEVICE_ID      = 1;

// ─── Pines ADC ─────────────────────────────────────────────
const int   PIN_ZMPT101B   = 34;   // Voltaje (ZMPT101B)
const int   PIN_SCT013     = 35;   // Corriente (SCT-013)

// ─── Parámetros de muestreo ────────────────────────────────
const int   SAMPLES        = 1480;   // ~ un ciclo de 60 Hz a 1700 samples/s
const int   SAMPLE_DELAY   = 600;    // microsegundos entre muestras
const float VREF           = 3.3;    // Voltaje de referencia del ADC

// ─── Calibración (ajustar con multímetro) ──────────────────
const float VOLTAGE_CAL    = 430.0;  // factor ZMPT101B
const float CURRENT_CAL    = 30.0;   // Relación SCT-013-030: 30A / 1V

// ─── Intervalo de envío (ms) ───────────────────────────────
const int   SEND_INTERVAL  = 3000;

#endif
