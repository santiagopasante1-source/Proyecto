#ifndef SENSORS_H
#define SENSORS_H

#include <Arduino.h>
#include "config.h"

// ─── Variables de estado ─────────────────────────────────
static float   voltaje_rms    = 0.0;
static float   corriente_rms  = 0.0;
static float   frecuencia_hz  = 60.0;   // default
static float   potencia_w     = 0.0;

// ─── Lectura RAW con promedio móvil para estabilidad ────
int readADC(int pin) {
    int val = 0;
    for (int i = 0; i < 8; i++) {
        val += analogRead(pin);
    }
    return val / 8;
}

// ─── Muestreo de voltaje + frecuencia ───────────────────
void sampleVoltage() {
    float vmax = 0, vmin = VREF;
    int   zero_crossings = 0;
    float last_sample = 0;
    unsigned long last_cross_time = 0;
    unsigned long period_sum = 0;

    for (int i = 0; i < SAMPLES; i++) {
        float raw = readADC(PIN_ZMPT101B) * VREF / 4095.0;
        if (raw > vmax) vmax = raw;
        if (raw < vmin) vmin = raw;

        // Detección de cruce por cero (centro = VREF/2)
        float center = VREF / 2.0;
        if (last_sample < center && raw >= center) {
            unsigned long now = micros();
            if (last_cross_time > 0) {
                period_sum += (now - last_cross_time);
                zero_crossings++;
            }
            last_cross_time = now;
        }
        last_sample = raw;
        delayMicroseconds(SAMPLE_DELAY);
    }

    // Voltaje RMS
    float vpp = vmax - vmin;
    voltaje_rms = (vpp / 2.828) * VOLTAGE_CAL;

    // Frecuencia
    if (zero_crossings > 0) {
        unsigned long avg_period = period_sum / zero_crossings;
        frecuencia_hz = 1000000.0 / avg_period;
        if (frecuencia_hz < 40 || frecuencia_hz > 70) {
            frecuencia_hz = 60.0;  // fuera de rango razonable
        }
    }
}

// ─── Muestreo de corriente ──────────────────────────────
void sampleCurrent() {
    float vmax = 0, vmin = VREF;

    for (int i = 0; i < SAMPLES; i++) {
        float raw = readADC(PIN_SCT013) * VREF / 4095.0;
        if (raw > vmax) vmax = raw;
        if (raw < vmin) vmin = raw;
        delayMicroseconds(SAMPLE_DELAY);
    }

    float vpp = vmax - vmin;
    float vrms = vpp / 2.828;
    corriente_rms = vrms * CURRENT_CAL;
    if (corriente_rms < 0.1) corriente_rms = 0.0;  // umbral

    potencia_w = voltaje_rms * corriente_rms;
}

// ─── Lectura completa de sensores ───────────────────────
void readSensors() {
    sampleVoltage();
    sampleCurrent();
}

#endif
