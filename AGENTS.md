# AGENTS.md — IoT Electrical Anomaly Detection

## Architecture

- **FastAPI** backend (`app/main.py:app`) on `:8000`
- **Streamlit** dashboard (`dashboard.py`) on `:8501`
- **Bi-LSTM** deep anomaly detector (`app/services/ia_deep_learning.py`)
- **PostgreSQL** (Neon) — URL required in `.env` as `DATABASE_URL`

## How to run

```powershell
# Everything at once
python launch.py

# Or individually:
uvicorn app.main:app --port 8000                # Backend
streamlit run dashboard.py                       # Dashboard
python scripts/simulador_realista.py --interval 3 # Simulator
```

## Commands

| Action | Command |
|---|---|---|
| Train LSTM model | `python scripts/train_local.py` → writes `models/lstm_anomaly_detector.{h5,keras}` + `models/training_metrics.json` |
| Generate dataset (30k rows) | `python scripts/Fallas.py` → writes `dataset_entrenamiento.csv` |
| Create user + assign device | `python scripts/seed_usuario.py --username X --password Y --device-id N` |
| Register device ID 1 | `python crear_dispositivo.py` (usually redundant — app auto-creates it on startup) |
| Install deps | `pip install -r requirements.txt` |

## Auth (JWT)

- **Endpoints**: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/asignar-dispositivo`.
- **Login required** for dashboard access — login/register page shown first, token stored in `st.session_state`.
- **Usuario** model: `username` + `email` + `password_hash` (bcrypt). No plain text passwords.
- **DB schema change**: If `usuarios` table already exists without `username`/`password_hash`, drop or ALTER it before running.
- **`.env` must include `SECRET_KEY`** for production JWT signing (default is insecure).

## Key gotchas

- **LSTM buffer must fill first**: needs 10 sequential samples before returning predictions; returns `"Calibrando LSTM..."` until then.
- **Python version**: project requires Python ≤ 3.11 for TensorFlow 2.15. `.python-version` = 3.10, but `runtime.txt` = 3.11 (for Railway). Railway **ignores** `.python-version` — create `runtime.txt` with `python-3.11` or the build fails.
- **IA_MODE**: `.env` expects `IA_MODE=deep` (Bi-LSTM). No other modes exist.
- **Model format**: `scripts/train_local.py` saves both `.keras` and `.h5`; `app/services/ia_deep_learning.py` loads from `.h5` (`models/lstm_anomaly_detector.h5`).
- **Model file is mandatory in production**: `models/lstm_anomaly_detector.h5` must exist. The app crashes on startup if missing and `ENVIRONMENT != "development"`.
- **Auto-training is dev-only**: In development, if no model file exists, the app trains from `dataset_entrenamiento.csv` or dummy data. Production never auto-trains.
- **DB tables auto-create** on every startup (`Base.metadata.create_all`). New columns (`username`, `password_hash`, `reset_code_hash`, `reset_code_expires_at`) auto-migrate with ALTER TABLE IF NOT EXISTS. No Alembic needed.
- **LSTM es el detector puro**: El LSTM decide SI hay anomalía. Reglas solo etiquetan el tipo. Si LSTM no detecta, NO se crea incidencia (sin safety net). Única excepción: RESTABLECIMIENTO vía DeviceMonitor. `ANOMALIA_LSTM` se crea cuando LSTM detecta pero ninguna regla clasifica.
- **APAGÓN solo por DeviceMonitor**: En un apagón real el ESP32 pierde alimentación, no envía datos. APAGÓN se detecta vía `DeviceMonitor` (60s sin telemetría), no por reglas de voltaje bajo. RESTABLECIMIENTO se crea cuando vuelven los datos.
- **`.env` is gitignored but is already committed** with a real Neon PostgreSQL credential. Do not re-commit secrets.
- **`postgres://` → `postgresql://`**: `dashboard.py` auto-fixes the prefix; `app/core/config.py` does not.
- **CORS wide open** (`allow_origins=["*"]`) — intentional for Streamlit<->FastAPI communication.
- **Telegram notifications**: optional, configured via `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` in `.env` or Railway. Debounce de 300s por tipo/dispositivo vía `app/services/telegram.py`.
- **Users have `telegram_id` field** (nullable) — needed for forgot-password and per-device Telegram alerts.
- **Forgot-password**: código numérico de 6 dígitos con expiry 10 min, enviado al Telegram del usuario. Endpoints `POST /forgot-password`, `POST /reset-password`. Requiere `telegram_id` en el usuario.
- **SQLite local dev**: If `DATABASE_URL` starts with `sqlite`, the engine uses `check_same_thread=False` + WAL mode. DB file is `iot_thesis.db` (gitignored).
- **No tests**: No test directory, no test runner config. Zero test files in the repo.
- **ESP32 firmware**: Arduino code in `esp32_iot/` (`.ino`, `config.h`, `sensors.h`). Config via `config.h` (WiFi SSID/password, API URL, ADC pins, calibration). Sends POST to `POST /api/v1/telemetry` every 3s.

## Dataset

`dataset_entrenamiento.csv` (30,000 rows) has columns: `voltaje, corriente, frecuencia, anomalia`. Generated with:
- Irregular block sizes (8-30 normal, 5-20 anomaly) — no fixed alternating pattern
- Gradual transitions (linear ramps of 4-8 samples between states)
- Pre-fault patterns: drift, oscillation buildup, mixed subtle signals
- Borderline anomalies (V=114-116, F=58.8-59.3) that rules don't catch
- 1% ADC-like noise spikes
- Fault types: sobrevoltaje, bajo_voltaje, frecuencia_baja, frecuencia_alta, pre_drift_bajo, pre_drift_frec, pre_oscilacion, pre_mixto

## Railway Deployment (FastAPI + Deep Learning)

| Step | Action |
|---|---|
| 1 | Push repo to GitHub |
| 2 | [railway.app](https://railway.app) → New Project → Deploy from GitHub |
| 3 | Set **Variables**: `DATABASE_URL`, `SECRET_KEY`, `ENVIRONMENT=production`, `IA_MODE=deep` |
| 4 | Railway auto-builds and starts `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| 5 | Copy Railway URL → paste in Streamlit Cloud **Secrets** as `API_BASE` |
| 6 | In Streamlit Cloud **Secrets** also add: `DATABASE_URL` (same Neon URL) |

**Gotchas**: Railway uses 1GB RAM, enough for `tensorflow`. Build takes ~5-10 min first time. The free tier does NOT sleep (unlike Render). Railway **ignores** `.python-version` — create `runtime.txt` with `python-3.11` or TensorFlow 2.15 build fails (no wheels for Python 3.12).

## Style notes

- SQLAlchemy models in `app/models/`, Pydantic schemas in `app/schemas/`.
- DB session dependency: `from app.core.database import get_db`.
- IA manager is a FastAPI `app.state` singleton, accessed via `request.app.state.detector` or the `get_ia_manager` dependency.
