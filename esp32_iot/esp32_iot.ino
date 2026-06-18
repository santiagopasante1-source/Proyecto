/*
 * ESP32 IoT — Monitor Eléctrico con Anomalía Detection
 * ======================================================
 * ZMPT101B  → Voltaje (RMS + Frecuencia)
 * SCT-013   → Corriente (RMS)
 * POST JSON → API Railway cada 3 segundos
 *
 * Conexiones:
 *   ZMPT101B VCC  → ESP32 5V (VIN)
 *   ZMPT101B GND  → ESP32 GND
 *   ZMPT101B OUT  → ESP32 GPIO 34  (con divisor resistivo si es necesario)
 *   SCT-013   SIG → ESP32 GPIO 35  (+ circuito de bias a 1.65V)
 *   SCT-013   GND → ESP32 GND
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

#include "config.h"
#include "sensors.h"

// ─── Variables de estado ─────────────────────────────────
static unsigned long last_send = 0;
static int           send_failures = 0;
static const int     MAX_FAILURES = 5;

// ─── Prototipos ──────────────────────────────────────────
void connectWiFi();
void sendTelemetry();

// ─── Setup ───────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(500);

    pinMode(PIN_ZMPT101B, INPUT);
    pinMode(PIN_SCT013,   INPUT);

    connectWiFi();
}

// ─── Loop principal ──────────────────────────────────────
void loop() {
    unsigned long now = millis();

    // Reintentar WiFi si se cayó
    if (WiFi.status() != WL_CONNECTED) {
        connectWiFi();
    }

    // Lectura de sensores + envío cada SEND_INTERVAL ms
    if (now - last_send >= SEND_INTERVAL) {
        readSensors();

        Serial.printf("V=%.1fV  I=%.2fA  F=%.1fHz  P=%.0fW\n",
                      voltaje_rms, corriente_rms, frecuencia_hz, potencia_w);

        sendTelemetry();
        last_send = now;
    }
}

// ─── Conexión WiFi ───────────────────────────────────────
void connectWiFi() {
    Serial.printf("Conectando a %s", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 40) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n✅ WiFi conectado. IP: %s\n", WiFi.localIP().toString().c_str());
        send_failures = 0;
    } else {
        Serial.println("\n❌ Error conectando WiFi");
    }
}

// ─── Envío de telemetría a la API ────────────────────────
void sendTelemetry() {
    if (WiFi.status() != WL_CONNECTED) return;

    HTTPClient http;
    String url = String(API_BASE_URL) + "/api/v1/telemetry";
    http.begin(url);
    http.addHeader("Content-Type", "application/json");

    // Construir JSON
    StaticJsonDocument<256> doc;
    doc["dispositivo_id"] = DEVICE_ID;
    doc["voltaje"]         = round(voltaje_rms * 10.0) / 10.0;
    doc["corriente"]       = round(corriente_rms * 100.0) / 100.0;
    doc["frecuencia"]      = round(frecuencia_hz * 10.0) / 10.0;

    String payload;
    serializeJson(doc, payload);

    int http_code = http.POST(payload);

    if (http_code == 201) {
        Serial.printf("📡 Enviado OK (HTTP %d)\n", http_code);
        send_failures = 0;
    } else {
        Serial.printf("⚠️  Error HTTP %d\n", http_code);
        String resp = http.getString();
        if (resp.length() > 0) {
            Serial.println(resp.substring(0, 120));
        }
        send_failures++;
    }

    http.end();

    // Si falla muchas veces seguidas, reinicia el ESP32
    if (send_failures >= MAX_FAILURES) {
        Serial.println("🔁 Demasiados errores. Reiniciando...");
        delay(2000);
        ESP.restart();
    }
}
