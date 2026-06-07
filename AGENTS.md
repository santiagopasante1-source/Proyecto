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
|---|---|
| Train LSTM model | `python scripts/train_local.py` → writes `models/lstm_anomaly_detector.keras` (note: detector loads `.h5`, not `.keras`) |
| Generate dataset (20k rows) | `python scripts/Fallas.py` → writes `dataset_entrenamiento.csv` |
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
- **Python version**: project requires Python ≤ 3.11 for TensorFlow 2.15. Railway **ignores** `.python-version` — add a `runtime.txt` with `python-3.11` or the build fails.
- **IA_MODE values**: `.env` has `IA_MODE=BI-LSTM` but only `"deep"` is valid.
- **Model format mismatch**: `scripts/train_local.py` saves as `.keras` but `app/services/ia_deep_learning.py` loads from `.h5`. Keep both or retrain after deploy.
- **Model file is mandatory in production**: `models/lstm_anomaly_detector.h5` must exist. The app crashes on startup if missing and `ENVIRONMENT != "development"`.
- **Auto-training is dev-only**: In development, if no model file exists, the app trains from `dataset_entrenamiento.csv` or dummy data. Production never auto-trains.
- **DB tables auto-create** on every startup (`Base.metadata.create_all`). New columns (`username`, `password_hash`) also auto-migrate with ALTER TABLE IF NOT EXISTS. No Alembic needed.
- **`.env` is gitignored but is already committed** with a real Neon PostgreSQL credential. Do not re-commit secrets.
- **`postgres://` → `postgresql://`**: `dashboard.py` auto-fixes the prefix; `settings.py` does not.
- **CORS wide open** (`allow_origins=["*"]`) — intentional for Streamlit<->FastAPI communication.
- **Telegram notifications**: optional, configured via `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` in `.env`. Service file (`app/services/telegram.py`) doesn't exist yet — import is wrapped in try/except, fails silently.
- **Devcontainer `postAttachCommand` is wrong**: it runs `streamlit run app/main.py` (should be `uvicorn app.main:app`).
- **`stream.py` is an abandoned file** — not the real dashboard (use `dashboard.py`).

## Dataset

`dataset_entrenamiento.csv` (20,000 rows) has columns: `voltaje, corriente, frecuencia, anomalia`. Generated in 100-row blocks alternating normal / fault states. Fault types: sobretension, bajo_voltaje, sobrecarga, ruido_frecuencia.

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
