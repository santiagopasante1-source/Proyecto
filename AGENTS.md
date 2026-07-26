# AGENTS.md — IoT Electrical Anomaly Detection

## Arquitectura

- **FastAPI** backend (`app/main.py:app`) en `:8000`
- **Streamlit** dashboard (`dashboard.py`) en `:8501`
- **Bi-LSTM** detector de anomalías profundo (`app/services/ia_deep_learning.py`)
- **PostgreSQL** (Neon) — URL requerida en `.env` como `DATABASE_URL`
- **Monitor de APAGÓN/DESCONEXIÓN** — `app/services/device_monitor.py` (thread background, 60s timeout, 10s check)
- **Telegram** — `app/services/telegram.py` (debounce 300s por tipo/dispositivo)
- **PDF Reports** — `app/services/pdf_reports.py` (reportes de incidencias y consumo)

### Arquitectura del modelo Bi-LSTM

```
Bidirectional(LSTM(64, return_sequences=True))
  → Dropout(0.2)
  → LSTM(32)
  → Dropout(0.2)
  → Dense(16, activation="relu")
  → Dense(1, activation="sigmoid")
```

| Parámetro | Valor |
|---|---|
| Optimizer | Adam(learning_rate=1e-3) |
| Loss | binary_crossentropy |
| Metrics | accuracy, AUC |
| Sequence length | 10 |
| Features | 3 (voltaje, corriente, frecuencia) |
| Threshold real | **0.46** (cargado desde `training_metrics.json`) |

## Cómo ejecutar

```powershell
# Todo a la vez
python launch.py

# O individualmente:
uvicorn app.main:app --port 8000                # Backend
streamlit run dashboard.py                       # Dashboard
python scripts/simulador_realista.py --interval 3 # Simulador
```

## Comandos

| Acción | Comando |
|---|---|
| Entrenar modelo LSTM | `python scripts/train_local.py` → escribe `models/lstm_anomaly_detector.{h5,keras}` + `models/training_metrics.json` |
| Generar dataset (30k filas) | `python scripts/Fallas.py` → escribe `dataset_entrenamiento.csv` |
| Crear usuario + asignar dispositivo | `python scripts/seed_usuario.py --username X --password Y --device-id N` |
| Registrar dispositivo ID 1 | `python crear_dispositivo.py` (generalmente redundante — la app lo auto-crea al iniciar) |
| Instalar dependencias | `pip install -r requirements.txt` |

### Parámetros de entrenamiento (`scripts/train_local.py`)

| Parámetro | Valor |
|---|---|
| Épocas máximas | 30 |
| Batch size | 64 |
| Partición | 70/15/15 (train/val/test) |
| EarlyStopping patience | 5 (restore_best_weights=True) |
| ReduceLROnPlateau | patience=3, factor=0.5, min_lr=1e-6 |
| Búsqueda de threshold | Grid search 0.30–0.99, step 0.01, optimizado por F1 |

### Métricas del modelo final (`models/training_metrics.json`)

| Métrica | Validation (15%) | Test (15%) |
|---|---|---|
| Threshold óptimo | **0.41** | **0.41** |
| F1-score | 0.8100 | 0.8166 |
| Precision | 0.7963 | 0.7858 |
| Recall | 0.8243 | 0.8500 |
| Accuracy | 0.9461 | 0.9419 |
| AUC | 0.9773 | 0.9774 |
| Muestras totales | — | 52,311 |
| Secuencias generadas | — | 52,301 |
| Épocas completadas | — | 30 |

## Auth (JWT)

- **Endpoints de auth** (`app/api/auth.py`):

| Método | Endpoint | Auth | Descripción |
|---|---|---|---|
| POST | `/api/v1/auth/login` | No | Iniciar sesión → JWT |
| POST | `/api/v1/auth/register` | No | Registrar nuevo usuario |
| GET | `/api/v1/auth/me` | JWT | Obtener perfil actual |
| PATCH | `/api/v1/auth/me` | JWT | Actualizar email/username |
| PUT | `/api/v1/auth/telegram` | JWT | Vincular ID de Telegram |
| POST | `/api/v1/auth/telegram/test` | JWT | Enviar mensaje de prueba |
| POST | `/api/v1/auth/telegram/diagnostico` | JWT | Diagnóstico completo de Telegram |
| POST | `/api/v1/auth/forgot-password` | No | Enviar código de 6 dígitos vía Telegram |
| POST | `/api/v1/auth/reset-password` | No | Restablecer contraseña con código |
| POST | `/api/v1/auth/asignar-dispositivo` | JWT | Asignar dispositivo al usuario |

- **Login requerido** para acceso al dashboard — se muestra página de login/register primero, token almacenado en `st.session_state`.
- **Usuario** model: `username` + `email` + `password_hash` (bcrypt). Sin contraseñas en texto plano.
- **`.env` debe incluir `SECRET_KEY`** para JWT en producción (el default es inseguro).

### Endpoints de sistema adicionales

| Método | Endpoint | Auth | Descripción |
|---|---|---|---|
| GET | `/health` | No | Health check del sistema (DB + IA status) |
| GET | `/ia/status` | No | Estado detallado del motor IA |
| POST | `/analizar` | No | Análisis en tiempo real sin persistencia |
| GET | `/api/v1/devices/status` | No | Estado de conexión + detección de APAGÓN |
| GET | `/api/v1/devices` | No | Listar dispositivos activos |
| GET | `/setup` (HTML) | No | Página web para configurar dispositivos y Telegram |

## Key gotchas

- **Threshold real = 0.41**: El default en `DeepAnomalyDetector.__init__` es 0.90, pero se sobreescribe al cargar `training_metrics.json`. Score > threshold = anomalía.
- **LSTM buffer**: necesita 10 muestras secuenciales antes de devolver predicciones; retorna `"Calibrando LSTM..."` hasta entonces.
- **Python version**: proyecto requiere Python ≤ 3.11 para TensorFlow 2.15. `.python-version` = 3.10, pero `runtime.txt` = 3.11 (para Railway). Railway **ignora** `.python-version` — crear `runtime.txt` con `python-3.11` o el build falla.
- **IA_MODE**: `.env` espera `IA_MODE=deep` (Bi-LSTM). No existen otros modos.
- **Formato del modelo**: `scripts/train_local.py` guarda `.keras` y `.h5`; `app/services/ia_deep_learning.py` carga desde `.h5` (`models/lstm_anomaly_detector.h5`).
- **Modelo obligatorio en producción**: `models/lstm_anomaly_detector.h5` debe existir. La app falla al iniciar si falta y `ENVIRONMENT != "development"`.
- **Auto-training es dev-only**: En desarrollo, si no existe el modelo, se entrena desde `dataset_entrenamiento.csv` o datos dummy. Producción nunca auto-entrena.
- **Bug conocido**: `ia_manager.py:51` llama a `self.detector.entrenar_con_dummy_data()` pero **no existe** ese método en `DeepAnomalyDetector`. Causaría `AttributeError` si se alcanza esa rama (dev sin modelo ni CSV).
- **DB tables auto-create** en cada inicio (`Base.metadata.create_all`). Columnas nuevas (`username`, `password_hash`, `reset_code_hash`, `reset_code_expires_at`) se auto-migran con ALTER TABLE IF NOT EXISTS. No se necesita Alembic.
- **LSTM es el detector puro**: El LSTM decide SI hay anomalía. Reglas solo etiquetan el tipo. Si LSTM no detecta, NO se crea incidencia (sin safety net). Única excepción: RESTABLECIMIENTO vía DeviceMonitor. `ANOMALIA_LSTM` se crea cuando LSTM detecta pero ninguna regla clasifica.
- **APAGÓN solo por DeviceMonitor**: En un apagón real el ESP32 pierde alimentación, no envía datos. APAGÓN se detecta vía `DeviceMonitor` (60s sin telemetría, configurable con `OFFLINE_TIMEOUT_SECONDS` en `.env`), no por reglas de voltaje bajo. RESTABLECIMIENTO se crea cuando vuelven los datos.
- **`.env` está en gitignore pero ya está commiteado** con credenciales reales de Neon PostgreSQL. No re-committear secretos.
- **`postgres://` → `postgresql://`**: `dashboard.py` auto-corrige el prefijo; `app/core/config.py` no.
- **CORS abierto** (`allow_origins=["*"]`) — intencional para comunicación Streamlit <-> FastAPI.
- **Telegram notifications**: opcional, configurado vía `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` en `.env` o Railway. Debounce de 300s por tipo/dispositivo vía `app/services/telegram.py`.
- **Users tienen `telegram_id` field** (nullable) — necesario para forgot-password y alertas por dispositivo.
- **Forgot-password**: código numérico de 6 dígitos con expiry 10 min, enviado al Telegram del usuario. Endpoints `POST /api/v1/auth/forgot-password`, `POST /api/v1/auth/reset-password`. Requiere `telegram_id` en el usuario.
- **SQLite local dev**: Si `DATABASE_URL` empieza con `sqlite`, el engine usa `check_same_thread=False` + WAL mode. DB file es `iot_thesis.db` (gitignored).
- **No tests**: No hay directorio de tests, ni config de test runner. Cero archivos de test en el repo.
- **ESP32 firmware**: Código Arduino en `esp32_iot/` (`.ino`, `config.h`, `sensors.h`). Config vía `config.h` (WiFi SSID/password, API URL, ADC pins, calibration). Envía POST a `POST /api/v1/telemetry` cada 3s.
- **`railway.json`**: Usa builder NIXPACKS, comando `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, restartPolicy ON_FAILURE (max 10 retries).
- **`.devcontainer/devcontainer.json`**: Para GitHub Codespaces. Ejecuta `streamlit run app/main.py` (esto está **incorrecto** — debería ser `dashboard.py`). Solo útil como punto de partida.
- **APAGON_MONITOR obsoleto**: `app/services/apagon_monitor.py` existe pero **no se importa en ningún lado**. Usa umbral de 12s (vs 60s de DeviceMonitor), no envía Telegram, no inserta V=0/I=0, no maneja DESCONEXION/RECONEXION. Reemplazado por `device_monitor.py`.
- **`stream.py` obsoleto**: Dashboard legacy con 3 bugs: busca tabla `telemetria` (debe ser `telemetrias`), solo pasa 2 de 3 features al modelo (falta `frecuencia`), usa `st.secrets["DATABASE_URL"]` directo. **No usar**.
- **PDF Reports**: `app/services/pdf_reports.py` requiere `fpdf2` + DejaVuSans.ttf para Unicode. `dashboard.py` lo importa y ofrece descargas PDF en páginas Consumo e Incidencias.
- **OFFLINE_TIMEOUT_SECONDS**: configurable en `.env`, default 60s. Define cuánto tiempo sin telemetría antes de crear un APAGÓN.

## Dataset

`dataset_entrenamiento.csv` generado por `scripts/Fallas.py` con **30,000 filas** (columnas: `voltaje, corriente, frecuencia, anomalia`). El entrenamiento produce **52,311 muestras** → **52,301 secuencias** (ventana deslizante de 10).

Generado con:
- Bloques irregulares: 8-30 normal, 5-20 anomalía — sin patrón fijo alternado
- Transiciones graduales: rampas lineales de 4-8 muestras entre estados
- Patrones pre-falla: drift, acumulación de oscilación, señales mixtas sutiles
- Anomalías borderline (V=114-116, F=58.8-59.3) que las reglas no capturan
- 1% spikes de ruido tipo ADC
- Tipos de falla: sobrevoltaje, bajo_voltaje, frecuencia_baja, frecuencia_alta, pre_drift_bajo, pre_drift_frec, pre_oscilacion, pre_mixto

## Railway Deployment (FastAPI + Deep Learning)

| Paso | Acción |
|---|---|
| 1 | Push repo a GitHub |
| 2 | [railway.app](https://railway.app) → New Project → Deploy from GitHub |
| 3 | Set **Variables**: `DATABASE_URL`, `SECRET_KEY`, `ENVIRONMENT=production`, `IA_MODE=deep` |
| 4 | Railway auto-builds (usa `railway.json` con builder NIXPACKS) y arranca `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| 5 | Copiar Railway URL → pegar en Streamlit Cloud **Secrets** como `API_BASE` |
| 6 | En Streamlit Cloud **Secrets** también agregar: `DATABASE_URL` (misma URL Neon) |

**Gotchas**: Railway usa 1GB RAM, suficiente para `tensorflow`. Build toma ~5-10 min la primera vez. El tier gratis NO duerme (a diferencia de Render). Railway **ignora** `.python-version` — crear `runtime.txt` con `python-3.11` o TensorFlow 2.15 falla (no hay wheels para Python 3.12).

## Style notes

- Modelos SQLAlchemy en `app/models/`, Schemas Pydantic en `app/schemas/`.
- DB session dependency: `from app.core.database import get_db`.
- IA manager es un singleton en `app.state`, accesible vía `request.app.state.detector` o el dependency `get_ia_manager`.
- `app/services/pdf_reports.py` usa `fpdf2` con DejaVuSans.ttf para Unicode. Genera `gen_pdf_incidencias(df)` y `gen_pdf_consumo(df, total, periodo)`.
- `app/services/telegram.py` con debounce de 300s por tipo/dispositivo.
- `app/services/device_monitor.py` corre en thread background, verifica cada 10s dispositivos con `ultimo_ping` > `OFFLINE_TIMEOUT_SECONDS`.
- Dockerfile no existe — Railway usa Nixpacks builder automático.
