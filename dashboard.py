"""
dashboard.py
────────────
Dashboard de monitoreo IoT en tiempo real con detección de anomalías por Deep Learning.
Ejecutar con:   streamlit run dashboard.py

Páginas:
   Tiempo Real    — Gráfico unificado de oscilación (V/I) en vivo y métricas híbridas
   Histórico      — Comportamiento por día/semana/mes desde la BD PostgreSQL (Neon)
   Consumo        — Consumo energético (kWh) diario y horario con proyecciones
   Incidencias    — Registro de eventos anómalos con nivel de criticidad
   Sistema        — Estado de salud del backend y del motor de IA (Bi-LSTM)
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, event

from app.services.pdf_reports import gen_pdf_incidencias as _gen_pdf_incidencias, gen_pdf_consumo as _gen_pdf_consumo

# ── Cargar variables de entorno del archivo .env
load_dotenv()

# ── Puente de Secrets (Streamlit Cloud): copia st.secrets -> os.environ
# Necesario para que os.getenv("DATABASE_URL"/"API_BASE") funcione en Cloud,
# donde los secrets NO se exponen automáticamente como variables de entorno.
try:
    if hasattr(st, "secrets"):
        for _key, _value in st.secrets.items():
            if isinstance(_value, dict):
                for _sub_key, _sub_value in _value.items():
                    os.environ[_sub_key.upper()] = str(_sub_value)
            else:
                os.environ[_key.upper()] = str(_value)
except Exception:
    pass

# ── Configuración de página 
st.set_page_config(
    page_title="IoT Anomaly Monitor",
    page_icon="chart_with_upwards_trend",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ── Constantes configurables 
API_BASE = os.getenv("API_BASE", "http://localhost:8000")

# Leer la base de datos desde las variables de entorno orientadas a PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if DATABASE_URL and DATABASE_URL.startswith("postgresql+psycopg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
if DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

DB_URL = DATABASE_URL

REFRESH_INTERVAL_S = 12                                        # Segundos entre actualizaciones en tiempo real
MAX_REALTIME_POINTS = 60                                       # Puntos visibles en el gráfico en vivo
OUTAGE_RISK_WINDOW_DAYS = 90                                   # Ventana histórica para la predicción de apagones
OUTAGE_RISK_MIN_APAGONES = 5                                   # Mínimo de apagones para usar esa fuente
SEVERIDAD_COLORS = {
    "baja":     "#3B82F6",   # azul
    "media":    "#F59E0B",   # ámbar
    "alta":     "#EF4444",   # rojo
    "critica":  "#7C3AED",   # púrpura
}

# ── Auth helpers ─────────────────────────────────────────────────────────────

def api_get(endpoint: str, timeout: int = 5) -> dict | None:
    token = st.session_state.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get(f"{API_BASE}{endpoint}", headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def api_post(endpoint: str, payload: dict, timeout: int = 5) -> dict | None:
    token = st.session_state.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.post(f"{API_BASE}{endpoint}", json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def api_post_auth(endpoint: str, payload: dict, timeout: int = 5) -> dict | None:
    """POST sin token — para login/register."""
    try:
        r = requests.post(f"{API_BASE}{endpoint}", json=payload, timeout=timeout)
        if r.ok:
            return r.json()
        return {"error": r.json().get("detail", f"Error {r.status_code}")}
    except Exception as e:
        return {"error": str(e)}


def api_put(endpoint: str, payload: dict, timeout: int = 5) -> dict | None:
    """PUT con token — para actualizar datos del usuario."""
    token = st.session_state.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.put(f"{API_BASE}{endpoint}", json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def api_patch(endpoint: str, payload: dict, timeout: int = 5) -> dict | None:
    """PATCH con token — para actualizar parcialmente datos del usuario."""
    token = st.session_state.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.patch(f"{API_BASE}{endpoint}", json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def api_delete(endpoint: str, timeout: int = 5) -> dict | None:
    """DELETE con token — para eliminar contactos."""
    token = st.session_state.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.delete(f"{API_BASE}{endpoint}", headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


# ── Helpers de acceso a datos ─────────────────────────────────────────────────

@st.cache_resource
def get_db_engine():
    """Crea el engine de SQLAlchemy para PostgreSQL (cacheado por Streamlit)."""
    engine = create_engine(
        DB_URL, 
        pool_pre_ping=True, 
        execution_options={"isolation_level": "AUTOCOMMIT"}
    )
    @event.listens_for(engine, "checkout")
    def _set_tz(dbapi_connection, connection_record, connection_proxy):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET TIME ZONE 'America/Caracas'")
        cursor.close()
    return engine


def query_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Ejecuta una consulta SQL parametrizada y devuelve un DataFrame. Devuelve vacío en error."""
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            return pd.read_sql_query(text(sql), conn, params=params or {})
    except Exception as exc:
        st.warning(f"Error de base de datos: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def get_outage_risk(dispositivo_id: int, dias: int = OUTAGE_RISK_WINDOW_DAYS) -> dict:
    """Riesgo histórico de apagón por hora local (America/Caracas)."""
    fecha_inicio = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()

    df_ap = query_df(
        """
        SELECT EXTRACT(HOUR FROM created_at AT TIME ZONE 'America/Caracas')::int AS hora,
               COUNT(*) AS eventos
        FROM incidencias
        WHERE dispositivo_id = :dispositivo_id
          AND tipo = 'APAGON'
          AND created_at >= :fecha_inicio
        GROUP BY 1
        """,
        params={"dispositivo_id": dispositivo_id, "fecha_inicio": fecha_inicio},
    )
    df_an = query_df(
        """
        SELECT EXTRACT(HOUR FROM timestamp AT TIME ZONE 'America/Caracas')::int AS hora,
               COUNT(*) AS total,
               SUM(CASE WHEN anomalia_detectada THEN 1 ELSE 0 END) AS anomalias
        FROM telemetrias
        WHERE dispositivo_id = :dispositivo_id
          AND timestamp >= :fecha_inicio
        GROUP BY 1
        """,
        params={"dispositivo_id": dispositivo_id, "fecha_inicio": fecha_inicio},
    )

    base = pd.DataFrame({"hora": range(24)})
    if df_ap.empty or "hora" not in df_ap.columns:
        ap = base.assign(eventos=0)
    else:
        ap = base.merge(df_ap, on="hora", how="left")
    ap["eventos"] = pd.to_numeric(ap["eventos"], errors="coerce").fillna(0).astype(int)
    total_apagones = int(ap["eventos"].sum())

    if df_an.empty or "hora" not in df_an.columns:
        an = base.assign(total=0, anomalias=0)
    else:
        an = base.merge(df_an, on="hora", how="left")
        an["total"] = pd.to_numeric(an["total"], errors="coerce").fillna(0).astype(int)
        an["anomalias"] = pd.to_numeric(an["anomalias"], errors="coerce").fillna(0).astype(int)
    total_lecturas = int(an["total"].sum())
    total_anomalias = int(an["anomalias"].sum())

    if total_apagones >= OUTAGE_RISK_MIN_APAGONES:
        df = ap.copy()
        max_eventos = df["eventos"].max()
        df["riesgo"] = (df["eventos"] / max_eventos * 100).round(1) if max_eventos > 0 else 0.0
        df["fuente"] = "apagones"
        df["hover"] = df["eventos"].apply(lambda n: f"{int(n)} apagones registrados")
        suficiente = True
    elif total_lecturas > 0:
        df = an.copy()
        df["tasa"] = (
            (df["anomalias"] / df["total"].where(df["total"] > 0)) * 100
        ).fillna(0).round(1)
        max_tasa = df["tasa"].max()
        df["riesgo"] = (df["tasa"] / max_tasa * 100).round(1) if max_tasa > 0 else 0.0
        df["fuente"] = "anomalias"
        df["hover"] = df.apply(
            lambda r: f"{r['tasa']:.1f}% anomalías ({int(r['anomalias'])}/{int(r['total'])} lecturas)",
            axis=1,
        )
        suficiente = total_lecturas >= 100
    else:
        df = ap.assign(riesgo=0.0, fuente="insuficiente", hover="Sin historial")
        suficiente = False

    if suficiente and df["riesgo"].max() <= 0:
        suficiente = False

    hora_pico = None
    riesgo_pico = 0.0
    top_horas: list[int] = []
    if suficiente:
        orden = df.sort_values("riesgo", ascending=False)
        top_horas = [int(h) for h in orden.head(3)["hora"].tolist()]
        hora_pico = top_horas[0]
        riesgo_pico = float(df.loc[df["hora"] == hora_pico, "riesgo"].iloc[0])

    return {
        "df": df,
        "fuente": str(df["fuente"].iloc[0]),
        "suficiente": suficiente,
        "total_apagones": total_apagones,
        "total_anomalias": total_anomalias,
        "total_lecturas": total_lecturas,
        "hora_pico": hora_pico,
        "riesgo_pico": riesgo_pico,
        "top_horas": top_horas,
        "dias": dias,
    }



# ── Helpers de consumo energético (kWh) ─────────────────────────────────────

def compute_kwh_daily(dispositivo_id: int, dias: int) -> pd.DataFrame:
    """Consumo kWh por día integrando potencia trapezoidal entre lecturas."""
    fecha_inicio = (datetime.now(ZoneInfo("America/Caracas")) - timedelta(days=dias)).isoformat()
    sql = """
        WITH base AS (
            SELECT timestamp, potencia,
                   LAG(timestamp) OVER (ORDER BY timestamp) as prev_ts,
                   LAG(potencia) OVER (ORDER BY timestamp) as prev_p
            FROM telemetrias
            WHERE dispositivo_id = :id
              AND timestamp >= :fecha_inicio
              AND potencia IS NOT NULL
        )
        SELECT
            DATE(timestamp) as fecha,
            ROUND(SUM(
                CASE
                    WHEN prev_ts IS NOT NULL AND prev_p IS NOT NULL
                    THEN ((prev_p + potencia) / 2.0) *
                         EXTRACT(EPOCH FROM (timestamp - prev_ts)) / 3600.0 / 1000.0
                    ELSE 0
                END
            )::numeric, 3) as kwh
        FROM base
        GROUP BY DATE(timestamp)
        ORDER BY fecha
    """
    return query_df(sql, params={"id": dispositivo_id, "fecha_inicio": fecha_inicio})


def compute_kwh_hourly(dispositivo_id: int) -> pd.DataFrame:
    """Consumo kWh por hora (hoy) integrando potencia trapezoidal."""
    sql = """
        WITH base AS (
            SELECT timestamp, potencia,
                   LAG(timestamp) OVER (ORDER BY timestamp) as prev_ts,
                   LAG(potencia) OVER (ORDER BY timestamp) as prev_p
            FROM telemetrias
            WHERE dispositivo_id = :id
              AND timestamp >= CURRENT_DATE
              AND potencia IS NOT NULL
        )
        SELECT
            EXTRACT(HOUR FROM timestamp)::int as hora,
            ROUND(SUM(
                CASE
                    WHEN prev_ts IS NOT NULL AND prev_p IS NOT NULL
                    THEN ((prev_p + potencia) / 2.0) *
                         EXTRACT(EPOCH FROM (timestamp - prev_ts)) / 3600.0 / 1000.0
                    ELSE 0
                END
            )::numeric, 4) as kwh
        FROM base
        GROUP BY EXTRACT(HOUR FROM timestamp)
        ORDER BY hora
    """
    return query_df(sql, params={"id": dispositivo_id})



# ── Helpers cacheados (evitan llamadas repetidas en cada rerun) ───────────────

@st.cache_data(ttl=5)
def check_health() -> dict | None:
    return api_get("/health")


@st.cache_data(ttl=30)
def get_user_devices(uid: int) -> pd.DataFrame:
    return query_df(
        "SELECT id, nombre FROM dispositivos WHERE is_active = TRUE AND usuario_id = :uid",
        params={"uid": uid},
    )


@st.cache_data(ttl=5)
def get_device_status(uid: int) -> list[dict]:
    res = api_get("/api/v1/devices/status")
    if not res:
        return []
    return res.get("dispositivos", [])


# ── Estilos globales ──────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Ocultar elementos heredados de Streamlit */
    footer {visibility: hidden;}

    /* Tarjetas de métricas personalizadas con soporte para transiciones */
    .metric-card {
        background: linear-gradient(135deg, #1e293b, #0f172a);
        border-radius: 12px;
        padding: 16px 20px;
        margin: 4px 0;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }
    .metric-title { color: #94a3b8; font-size: 13px; margin-bottom: 4px; font-weight: 500; }
    .metric-value { color: #f1f5f9; font-size: 28px; font-weight: 700; }
    
    /* Badges de severidad */
    .badge-baja    { background:#1d4ed8;color:#bfdbfe;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:600; }
    .badge-media   { background:#92400e;color:#fde68a;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:600; }
    .badge-alta    { background:#991b1b;color:#fecaca;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:600; }
    .badge-critica { background:#5b21b6;color:#e9d5ff;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:600; }

    /* Separador de sección elegante */
    .section-header {
        font-size: 16px; font-weight: 600; color: #e2e8f0;
        border-left: 3px solid #6366f1; padding-left: 10px; margin: 20px 0 12px;
    }

    /* Quita la "sombra/fantasma" al cambiar de pestaña: Streamlit atenúa
       los elementos stale a opacity 0.33 con un fade de 1s. Lo forzamos
       a opacidad completa y sin transición para que no quede el residuo. */
    [data-testid="stElementContainer"][data-stale="true"] {
        opacity: 1 !important;
        transition: none !important;
    }
</style>
""", unsafe_allow_html=True)


# ── Auth state ────────────────────────────────────────────────────────────────

if "token" not in st.session_state:
    st.session_state.token = None
if "user" not in st.session_state:
    st.session_state.user = None
if "login_success" not in st.session_state:
    st.session_state.login_success = False

# ── Login / Forgot password state ──────────────────────────────────────────────

if "forgot_mode" not in st.session_state:
    st.session_state.forgot_mode = False
if "code_sent" not in st.session_state:
    st.session_state.code_sent = False

# ── Login / Register page ─────────────────────────────────────────────────────

if not st.session_state.token:
    st.title("Inicio de Sesión")

    if not st.session_state.forgot_mode:
        with st.form("login_form"):
            l_user = st.text_input("Usuario")
            l_pass = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Ingresar", type="primary"):
                with st.spinner("Iniciando sesión..."):
                    res = api_post_auth("/api/v1/auth/login", {"username": l_user, "password": l_pass})
                if res and "access_token" in res:
                    st.session_state.token = res["access_token"]
                    st.session_state.user = res["user"]
                    st.session_state.login_success = True
                    st.session_state.forgot_mode = False
                    st.rerun()
                else:
                    err = res.get("error", "Credenciales inválidas o backend sin conexión") if res else "Backend sin conexión"
                    st.error(err)

        if st.button("¿Olvidaste tu contraseña?", type="tertiary"):
            st.session_state.forgot_mode = True
            st.rerun()

    else:
        st.markdown("### Recuperar contraseña")
        st.caption("Ingresa tu usuario para recibir un código en tu Telegram.")

        if not st.session_state.code_sent:
            fp_user = st.text_input("Usuario", key="fp_user")
            if st.button("Enviar código a Telegram", type="primary"):
                if not fp_user:
                    st.error("Ingresa tu usuario")
                else:
                    with st.spinner("Enviando código..."):
                        res = api_post_auth("/api/v1/auth/forgot-password", {"username": fp_user})
                    if res and "error" not in res:
                        st.session_state.code_sent = True
                        st.session_state.fp_username = fp_user
                        st.rerun()
                    else:
                        err = res.get("error") if res else "Backend sin conexión"
                        st.error(err)
        else:
            st.success("Si el usuario existe, revisa tu Telegram para el código de 6 dígitos.")
            fp_code = st.text_input("Código de 6 dígitos", max_chars=6, key="fp_code")
            fp_new_pass = st.text_input("Nueva contraseña", type="password", key="fp_new_pass")
            fp_confirm = st.text_input("Confirmar contraseña", type="password", key="fp_confirm")

            cols = st.columns(2)
            with cols[0]:
                if st.button("Restablecer", type="primary"):
                    if not fp_code or not fp_new_pass or not fp_confirm:
                        st.error("Completa todos los campos")
                    elif fp_new_pass != fp_confirm:
                        st.error("Las contraseñas no coinciden")
                    elif len(fp_new_pass) < 6:
                        st.error("La contraseña debe tener al menos 6 caracteres")
                    else:
                        with st.spinner("Restableciendo..."):
                            res = api_post_auth("/api/v1/auth/reset-password", {
                                "username": st.session_state.fp_username,
                                "code": fp_code,
                                "new_password": fp_new_pass,
                            })
                        if res and "error" not in res:
                            st.session_state.forgot_mode = False
                            st.session_state.code_sent = False
                            st.success("✅ Contraseña restablecida. Ahora puedes iniciar sesión.")
                            st.rerun()
                        else:
                            err = res.get("error") if res else "Backend sin conexión"
                            st.error(err)
            with cols[1]:
                if st.button("Volver"):
                    st.session_state.forgot_mode = False
                    st.session_state.code_sent = False
                    st.rerun()

    st.stop()

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/circuit.png", width=64)
    st.title("IoT Monitor")
    st.caption(f"Usuario: {st.session_state.user.get('username', '')}")
    if st.button("Cerrar Sesión"):
        st.session_state.token = None
        st.session_state.user = None
        st.cache_data.clear()
        st.rerun()
    st.divider()

    pagina = st.radio(
        "Navegación",
        ["Tiempo Real", "Histórico", "Consumo", "Incidencias", "Sistema"],
        label_visibility="collapsed",
    )
    st.divider()

    # Selector de dispositivo — solo muestra los asignados al usuario actual (cacheado 30s)
    uid = st.session_state.user.get("id")
    df_disp = get_user_devices(uid)
        
    if not df_disp.empty:
        dispositivo_id = st.selectbox(
            "Dispositivo activo",
            options=df_disp["id"].tolist(),
            format_func=lambda i: df_disp.loc[df_disp["id"] == i, "nombre"].values[0],
        )
    else:
        dispositivo_id = 1
        st.warning("No hay dispositivos activos en la BD.")

    # Estado de conexión del dispositivo seleccionado
    dev_status_list = get_device_status(uid)
    current_dev_status = next(
        (d for d in dev_status_list if d["id"] == dispositivo_id),
        None,
    )
    if current_dev_status:
        estado = current_dev_status["estado"]
        if estado == "conectado":
            st.success(f"✅ {current_dev_status['nombre']}: **Conectado**")
        elif estado and estado.startswith("desconectado"):
            st.error(f"⚠️ {current_dev_status['nombre']}: **{estado.upper()}**")
        elif estado == "nunca_conectado":
            st.warning(f"🟡 {current_dev_status['nombre']}: **Sin datos**")
        else:
            st.info(f"❓ {current_dev_status['nombre']}: {estado}")

    st.caption(f"API: `{API_BASE}`")

    # Indicador de salud del API (cacheado 5s)
    health = check_health()
    if health and health.get("status") == "ok":
        st.success("Backend conectado")
    else:
        st.error("Backend sin conexion")

# ── Toast de bienvenida después del login ─────────────────────────────────────

if st.session_state.login_success:
    st.session_state.login_success = False
    st.toast("Sesion iniciada correctamente")

# ══════════════════════════════════════════════════════════════════════════════
# PÁGINA 1: TIEMPO REAL
# ══════════════════════════════════════════════════════════════════════════════

if pagina == "Tiempo Real":
    st.title("Monitoreo en Tiempo Real")
    st.caption("Los gráficos se actualizan automáticamente consultando la API y la base de datos.")
    st.write(f"Reloj Venezuela: {datetime.now(ZoneInfo('America/Caracas')).strftime('%H:%M:%S')}")

    # ── Estado del dispositivo (conectado / apagón) ──
    dev_status_list = get_device_status(uid)
    current_dev_status = next(
        (d for d in dev_status_list if d["id"] == dispositivo_id),
        None,
    )
    en_apagon = current_dev_status and current_dev_status.get("apagon_activo", False)
    apagon_desde = current_dev_status.get("apagon_desde") if en_apagon else None

    col1, col2, col3, col4 = st.columns(4)

    sql_ultimo = """
        SELECT voltaje, corriente, potencia, frecuencia, timestamp, anomalia_detectada
        FROM telemetrias
        WHERE dispositivo_id = :dispositivo_id
        ORDER BY timestamp DESC LIMIT 1
    """
    df_ultimo = query_df(sql_ultimo, params={"dispositivo_id": dispositivo_id})

    if en_apagon:
        # ── APAGÓN: mostrar 0s + hora del corte ──
        RED = "#EF4444"
        apagon_hora = ""
        if apagon_desde:
            try:
                dt = datetime.fromisoformat(apagon_desde)
                apagon_hora = dt.strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                apagon_hora = apagon_desde

        def metric_apagon(title, unit):
            return f"""
            <div class="metric-card" style="border: 2px solid {RED};">
              <div class="metric-title">{title}</div>
              <div class="metric-value">0.00 <span style="font-size:14px;color:#64748b">{unit}</span></div>
            </div>"""

        col1.markdown(metric_apagon("Voltaje", "V"), unsafe_allow_html=True)
        col2.markdown(metric_apagon("Corriente", "A"), unsafe_allow_html=True)
        col3.markdown(metric_apagon("Potencia", "W"), unsafe_allow_html=True)
        col4.markdown(metric_apagon("Frecuencia", "Hz"), unsafe_allow_html=True)

        st.markdown(f"""
        <div style="background:#7f1d1d; border:2px solid #ef4444; border-radius:12px; padding:20px; margin:12px 0; text-align:center;">
            <span style="font-size:32px;">⚡🚨</span>
            <h2 style="color:#fecaca; margin:8px 0;">APAGÓN</h2>
            <p style="color:#fca5a5; font-size:18px; margin:0;">
                {apagon_hora}
            </p>
        </div>
        """, unsafe_allow_html=True)

    elif not df_ultimo.empty:
        row = df_ultimo.iloc[0]
        v, i, p, f = row["voltaje"], row["corriente"], row["potencia"], row.get("frecuencia", 0)
        
        # ── 1. REGLAS DE INGENIERÍA ──
        voltaje_fuera = (v < 114.0 or v > 134.0)
        frecuencia_fuera = (f < 59.0 or f > 61.0) if f > 0 else False
        corriente_fuera = (i > 50.0)
        
        es_anomalia_ia = bool(row["anomalia_detectada"])
        es_anomalia_regla = (voltaje_fuera or frecuencia_fuera or corriente_fuera)

        # ── 2. COLORES DINÁMICOS PARA LOS BORDES ──
        v_border = "#EF4444" if voltaje_fuera else "#334155"
        i_border = "#EF4444" if corriente_fuera else "#334155"
        p_border = "#334155"  
        f_border = "#EF4444" if frecuencia_fuera else "#334155"

        def metric_html(title, value, unit, border_color="#334155"):
            return f"""
            <div class="metric-card" style="border: 2px solid {border_color}; transition: border 0.4s ease-in-out;">
              <div class="metric-title">{title}</div>
              <div class="metric-value">{value:.2f} <span style="font-size:14px;color:#64748b">{unit}</span></div>
            </div>"""

        col1.markdown(metric_html("Voltaje", v, "V", v_border), unsafe_allow_html=True)
        col2.markdown(metric_html("Corriente", i, "A", i_border), unsafe_allow_html=True)
        col3.markdown(metric_html("Potencia", p or 0, "W", p_border), unsafe_allow_html=True)
        col4.markdown(metric_html("Frecuencia", f or 0, "Hz", f_border), unsafe_allow_html=True)

        st.write("") 

        # ── 3. ALERTAS DINÁMICAS ──
        if es_anomalia_ia:
            st.error("**ANOMALIA DETECTADA POR IA (Bi-LSTM)** — El modelo ha identificado una firma temporal de riesgo en el flujo electrico.")
        elif es_anomalia_regla:
            st.warning("**ALERTA DE SEGURIDAD (Umbral Fisico)** — Valores fuera de rangos nominales de ingenieria.")
        else:
            st.success("**Operacion Electrica Normal** — Parametros estables.")

    else:
        st.info("No hay datos de telemetría disponibles para este dispositivo en este momento.")

    st.divider()

    # ── 4. GRÁFICO UNIFICADO DE OSCILACIÓN (Doble Eje Y con Marcadores de Anomalía de la IA) ──
    st.markdown('<div class="section-header">Gráfico de Oscilación Eléctrica Combinada (Voltaje vs Corriente)</div>', unsafe_allow_html=True)
    
    sql_rt = f"""
        SELECT timestamp, voltaje, corriente, anomalia_detectada
        FROM telemetrias
        WHERE dispositivo_id = :dispositivo_id
        ORDER BY timestamp DESC LIMIT {MAX_REALTIME_POINTS}
    """
    df_rt = query_df(sql_rt, params={"dispositivo_id": dispositivo_id})
    
    if not df_rt.empty:
        df_rt = df_rt.sort_values("timestamp")
        df_rt["timestamp"] = pd.to_datetime(df_rt["timestamp"])
        if df_rt["timestamp"].dt.tz is None:
            df_rt["timestamp"] = df_rt["timestamp"].dt.tz_localize("UTC")
        df_rt["timestamp"] = df_rt["timestamp"].dt.tz_convert("America/Caracas")
        
        # Crear figura con doble eje Y
        fig_combined = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Trazo de Oscilación de Voltaje (Eje izquierdo)
        fig_combined.add_trace(go.Scatter(
            x=df_rt["timestamp"], y=df_rt["voltaje"],
            mode="lines",
            line=dict(color="#6366f1", width=2.5),
            name="Voltaje (V)"
        ), secondary_y=False)
        
        # Trazo de Oscilación de Corriente (Eje derecho)
        fig_combined.add_trace(go.Scatter(
            x=df_rt["timestamp"], y=df_rt["corriente"],
            mode="lines",
            line=dict(color="#f59e0b", width=2),
            name="Corriente (A)"
        ), secondary_y=True)
        
        # Resaltar puntos de anomalías detectados por la IA sobre la gráfica
        df_anom = df_rt[df_rt["anomalia_detectada"] == True]
        if not df_anom.empty:
            fig_combined.add_trace(go.Scatter(
                x=df_anom["timestamp"], y=df_anom["voltaje"],
                mode="markers",
                marker=dict(color="#ef4444", size=9, symbol="circle", line=dict(color="#ffffff", width=1)),
                name="Firma Anómala (IA)"
            ), secondary_y=False)

        # Línea guía nominal para el Voltaje
        fig_combined.add_hline(y=120, line_dash="dash", line_color="#22c55e", annotation_text="Nominal 120V")
        
        # Parámetros reestructurados titlefont -> title=dict(font=...)
        fig_combined.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#94a3b8", margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(showgrid=False),
            yaxis=dict(
                title=dict(text="Voltaje (V)", font=dict(color="#6366f1")), 
                gridcolor="#1e293b", 
                tickfont=dict(color="#6366f1")
            ),
            yaxis2=dict(
                title=dict(text="Corriente (A)", font=dict(color="#f59e0b")), 
                showgrid=False, 
                tickfont=dict(color="#f59e0b")
            ),
            height=340,
            legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1)
        )
        st.plotly_chart(fig_combined, width='stretch')
    else:
        st.info("Esperando flujo de series de datos temporales...")

    # ── 5. PREDICCIÓN DE RIESGO DE APAGÓN POR HORA ──
    st.markdown('<div class="section-header">Predicción de apagones por hora (histórico)</div>', unsafe_allow_html=True)

    riesgo = get_outage_risk(dispositivo_id)
    df_risk = riesgo["df"]

    if not riesgo["suficiente"]:
        st.info(
            "Todavía no hay suficiente historial para estimar la hora de riesgo. "
            f"Se necesitan al menos {OUTAGE_RISK_MIN_APAGONES} apagones o 100 lecturas."
        )
        st.caption(
            f"Ventana analizada: {riesgo['dias']} días · "
            f"Apagones: {riesgo['total_apagones']} · Lecturas: {riesgo['total_lecturas']}"
        )
    else:
        pico = int(riesgo["hora_pico"])
        fuente_txt = (
            "apagones históricos"
            if riesgo["fuente"] == "apagones"
            else "tasa de anomalías (respaldo)"
        )
        fig_risk = go.Figure()
        fig_risk.add_trace(go.Bar(
            x=df_risk["hora"],
            y=df_risk["riesgo"],
            marker=dict(
                color=df_risk["riesgo"],
                colorscale=[[0, "#22c55e"], [0.5, "#f59e0b"], [1, "#ef4444"]],
                cmin=0,
                cmax=100,
                line=dict(width=0),
            ),
            customdata=df_risk[["hover"]],
            hovertemplate=(
                "%{x}:00<br>%{customdata[0]}"
                "<br>Índice de riesgo: %{y:.0f}/100<extra></extra>"
            ),
        ))
        fig_risk.add_trace(go.Scatter(
            x=df_risk["hora"],
            y=df_risk["riesgo"].rolling(3, center=True, min_periods=1).mean(),
            mode="lines",
            line=dict(color="#93c5fd", width=2, dash="dot"),
            hoverinfo="skip",
        ))
        fig_risk.add_trace(go.Scatter(
            x=[pico],
            y=[riesgo["riesgo_pico"]],
            mode="markers+text",
            marker=dict(color="#ef4444", size=14, symbol="star", line=dict(color="#ffffff", width=1)),
            text=[f"Pico {pico:02d}:00"],
            textposition="top center",
            textfont=dict(color="#fecaca"),
            hoverinfo="skip",
        ))
        fig_risk.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#94a3b8", height=320, margin=dict(l=0, r=0, t=30, b=0),
            xaxis=dict(
                title="Hora (Venezuela)",
                tickmode="array",
                tickvals=list(range(0, 24, 2)),
                ticktext=[f"{h:02d}:00" for h in range(0, 24, 2)],
                showgrid=False,
            ),
            yaxis=dict(
                title="Índice de riesgo (0-100)",
                range=[0, 105],
                gridcolor="#1e293b",
            ),
            showlegend=False,
            bargap=0.25,
        )
        st.plotly_chart(fig_risk, width='stretch')

        ahora = datetime.now(ZoneInfo("America/Caracas")).hour
        proximas = [h for h in riesgo["top_horas"] if h >= ahora]
        if proximas:
            prox = min(proximas)
            cuando = "ahora" if prox == ahora else f"hoy a las {prox:02d}:00"
        else:
            prox = min(riesgo["top_horas"])
            cuando = f"mañana a las {prox:02d}:00"
        prox_riesgo = float(df_risk.loc[df_risk["hora"] == prox, "riesgo"].iloc[0])

        c1, c2, c3 = st.columns(3)
        c1.metric("Hora pico histórica", f"{pico:02d}:00", f"Índice {riesgo['riesgo_pico']:.0f}/100")
        c2.metric("Próxima ventana de riesgo", cuando, f"Índice {prox_riesgo:.0f}/100")
        c3.metric("Base histórica", f"{riesgo['total_apagones']} apagones", f"{riesgo['dias']} días")

        st.caption(
            "Estimación estadística basada en el historial por hora. No es una garantía de corte. "
            f"Fuente: {fuente_txt}."
        )

    st.caption(f"Actualizacion automatica activa cada {REFRESH_INTERVAL_S}s")
    if not os.getenv("DASHBOARD_NO_AUTOREFRESH"):
        time.sleep(REFRESH_INTERVAL_S)
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PÁGINA 2: HISTÓRICO
# ══════════════════════════════════════════════════════════════════════════════

elif pagina == "Histórico":
    st.title("Análisis Histórico")

    rango = st.radio(
        "Período de análisis",
        ["Hoy", "Última semana", "Último mes"],
        horizontal=True,
    )
    dias = {"Hoy": 1, "Última semana": 7, "Último mes": 30}[rango]
    fecha_inicio = (datetime.now(ZoneInfo("America/Caracas")) - timedelta(days=dias)).isoformat()

    sql_historico = """
        SELECT
            DATE(timestamp) as fecha,
            TO_CHAR(timestamp, 'HH24') as hora,
            AVG(voltaje)   as voltaje_avg,
            MAX(voltaje)   as voltaje_max,
            MIN(voltaje)   as voltaje_min,
            AVG(corriente) as corriente_avg,
            AVG(potencia)  as potencia_avg,
            COUNT(*)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    as total,
            SUM(CASE WHEN anomalia_detectada THEN 1 ELSE 0 END) as anomalias
        FROM telemetrias
        WHERE dispositivo_id = :dispositivo_id
          AND timestamp >= :fecha_inicio
        GROUP BY DATE(timestamp), TO_CHAR(timestamp, 'HH24')
        ORDER BY fecha, hora
    """

    df_hist = query_df(sql_historico, params={"dispositivo_id": dispositivo_id, "fecha_inicio": fecha_inicio})

    if df_hist.empty:
        st.info("No hay datos históricos almacenados para el período seleccionado.")
    else:
        df_hist["datetime"] = pd.to_datetime(df_hist["fecha"].astype(str) + " " + df_hist["hora"].astype(str) + ":00")
        df_hist["tasa_anomalia"] = (df_hist["anomalias"] / df_hist["total"] * 100).round(1)

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Voltaje promedio", f"{df_hist['voltaje_avg'].mean():.1f} V")
        kpi2.metric("Corriente promedio", f"{df_hist['corriente_avg'].mean():.2f} A")
        kpi3.metric("Total registros", f"{int(df_hist['total'].sum()):,}")
        kpi4.metric("Anomalías totales", f"{int(df_hist['anomalias'].sum()):,}",
                    delta=f"{df_hist['tasa_anomalia'].mean():.1f}% tasa",
                    delta_color="inverse")

        st.divider()

        st.markdown('<div class="section-header">Voltaje — Promedio, Mínimo y Máximo</div>', unsafe_allow_html=True)
        fig_v = go.Figure([
            go.Scatter(
                x=df_hist["datetime"], y=df_hist["voltaje_max"],
                fill=None, mode="lines", line_color="rgba(99,102,241,0.2)", name="Máximo",
            ),
            go.Scatter(
                x=df_hist["datetime"], y=df_hist["voltaje_min"],
                fill="tonexty", mode="lines", line_color="rgba(99,102,241,0.2)",
                fillcolor="rgba(99,102,241,0.08)", name="Mínimo",
            ),
            go.Scatter(
                x=df_hist["datetime"], y=df_hist["voltaje_avg"],
                mode="lines", line=dict(color="#6366f1", width=2.5), name="Promedio",
            ),
        ])
        fig_v.add_hline(y=120, line_dash="dot", line_color="#22c55e", annotation_text="Nominal")
        fig_v.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#94a3b8", height=300, margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#1e293b"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_v, width='stretch')

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown('<div class="section-header">Potencia consumida promedio por hora</div>', unsafe_allow_html=True)
            fig_p = px.bar(
                df_hist, x="datetime", y="potencia_avg",
                color="potencia_avg", color_continuous_scale="Viridis",
                labels={"potencia_avg": "Potencia (W)", "datetime": ""},
            )
            fig_p.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#94a3b8", height=280, margin=dict(l=0, r=0, t=10, b=0),
                coloraxis_showscale=False, showlegend=False,
            )
            st.plotly_chart(fig_p, width='stretch')

        with col_b:
            st.markdown('<div class="section-header">Tasa de anomalías (%) por segmento horario</div>', unsafe_allow_html=True)
            df_hist["color"] = df_hist["tasa_anomalia"].apply(
                lambda x: "#ef4444" if x > 20 else ("#f59e0b" if x > 5 else "#22c55e")
            )
            fig_t = go.Figure(go.Bar(
                x=df_hist["datetime"],
                y=df_hist["tasa_anomalia"],
                marker_color=df_hist["color"],
            ))
            fig_t.add_hline(y=5, line_dash="dash", line_color="#f59e0b", annotation_text="Umbral de Alerta (5%)")
            fig_t.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#94a3b8", height=280, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title="% anomalías", xaxis=dict(showgrid=False),
                yaxis=dict(gridcolor="#1e293b"),
            )
            st.plotly_chart(fig_t, width='stretch')

        st.markdown('<div class="section-header">Resumen de comportamiento diario</div>', unsafe_allow_html=True)
        df_dia = df_hist.groupby("fecha").agg(
            registros=("total", "sum"),
            anomalias=("anomalias", "sum"),
            voltaje_prom=("voltaje_avg", "mean"),
            corriente_prom=("corriente_avg", "mean"),
        ).reset_index()
        df_dia["tasa"] = (df_dia["anomalias"] / df_dia["registros"] * 100).round(1).astype(str) + "%"
        df_dia["voltaje_prom"] = df_dia["voltaje_prom"].round(2)
        df_dia["corriente_prom"] = df_dia["corriente_prom"].round(3)
        st.dataframe(
            df_dia.rename(columns={
                "fecha": "Fecha", "registros": "Registros", "anomalias": "Anomalías",
                "voltaje_prom": "V prom (V)", "corriente_prom": "I prom (A)", "tasa": "Tasa Diario",
            }),
            width='stretch', hide_index=True,
        )

# ══════════════════════════════════════════════════════════════════════════════
# PÁGINA 3: CONSUMO
# ══════════════════════════════════════════════════════════════════════════════

elif pagina == "Consumo":
    st.title("Consumo Energético (kWh)")
    st.caption("Integración trapezoidal de potencia eléctrica para energía acumulada.")

    df_daily = compute_kwh_daily(dispositivo_id, 30)
    today = datetime.now(ZoneInfo("America/Caracas")).date()

    if df_daily.empty:
        st.info("No hay suficientes datos de telemetría para calcular consumo.")
    else:
        # ── KPIs ──
        kwh_hoy = df_daily.loc[df_daily["fecha"] == today, "kwh"].sum()
        semana_start = today - timedelta(days=7)
        kwh_semana = df_daily.loc[df_daily["fecha"] >= semana_start, "kwh"].sum()
        kwh_mes = df_daily["kwh"].sum()

        hora_actual = datetime.now(ZoneInfo("America/Caracas")).hour
        minuto_actual = datetime.now(ZoneInfo("America/Caracas")).minute
        hora_decimal = hora_actual + minuto_actual / 60.0
        proyeccion = (kwh_hoy / hora_decimal * 24 * 30) if hora_decimal > 0 and kwh_hoy > 0 else 0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("kWh Hoy", f"{kwh_hoy:.3f}")
        k2.metric("kWh Última Semana", f"{kwh_semana:.3f}")
        k3.metric("kWh Últimos 30 Días", f"{kwh_mes:.3f}")
        k4.metric("Proyección Mensual", f"{proyeccion:.3f}")

        st.divider()

        # ── Selector de período para la gráfica ──
        periodo_consumo = st.radio(
            "Período de visualización",
            ["Hoy", "Última semana", "Último mes"],
            horizontal=True,
            key="consumo_periodo",
        )
        dias_consumo = {"Hoy": 1, "Última semana": 7, "Último mes": 30}[periodo_consumo]
        fecha_corte = today - timedelta(days=dias_consumo - 1)
        df_display = df_daily[df_daily["fecha"] >= fecha_corte]

        # ── Gráfica 1: Consumo diario ──
        st.markdown('<div class="section-header">Consumo diario (kWh)</div>', unsafe_allow_html=True)
        if not df_display.empty:
            fig_daily = px.bar(
                df_display, x="fecha", y="kwh",
                labels={"fecha": "", "kwh": "kWh"},
                color="kwh", color_continuous_scale="Viridis",
            )
            fig_daily.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#94a3b8", height=280, margin=dict(l=0, r=0, t=10, b=0),
                coloraxis_showscale=False,
                xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#1e293b"),
            )
            st.plotly_chart(fig_daily, width='stretch')
        else:
            st.info("No hay datos para el período seleccionado.")

        # ── Gráfica 2: Perfil horario (hoy) ──
        st.markdown('<div class="section-header">Perfil horario de consumo (hoy)</div>', unsafe_allow_html=True)
        df_hourly = compute_kwh_hourly(dispositivo_id)
        if not df_hourly.empty:
            fig_hourly = px.bar(
                df_hourly, x="hora", y="kwh",
                labels={"hora": "Hora", "kwh": "kWh"},
                color="kwh", color_continuous_scale="Viridis",
            )
            fig_hourly.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#94a3b8", height=280, margin=dict(l=0, r=0, t=10, b=0),
                coloraxis_showscale=False,
                xaxis=dict(dtick=1, showgrid=False), yaxis=dict(gridcolor="#1e293b"),
            )
            st.plotly_chart(fig_hourly, width='stretch')
        else:
            st.info("No hay datos horarios disponibles para hoy.")

        st.divider()

        # ── PDF ──
        periodo_label = {"Hoy": "Hoy", "Última semana": "Semana", "Último mes": "Mes"}[periodo_consumo]
        total_display = df_display["kwh"].sum()
        pdf_bytes = _gen_pdf_consumo(df_display, total_display, periodo_label)
        st.download_button(
            "Descargar reporte de consumo (PDF)",
            data=pdf_bytes,
            file_name=f"consumo_{datetime.now(ZoneInfo('America/Caracas')).strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
        )

# ══════════════════════════════════════════════════════════════════════════════
# PÁGINA 4: INCIDENCIAS
# ══════════════════════════════════════════════════════════════════════════════

elif pagina == "Incidencias":
    st.title("Registro de Incidencias Históricas")
    st.caption("Historial de anomalías críticas validadas y estructuradas por criticidad.")

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        sev_filtro = st.multiselect(
            "Filtrar por Severidad", ["baja", "media", "alta", "critica"],
            default=["media", "alta", "critica"],
        )
    with col_f2:
        estado_filtro = st.multiselect(
            "Filtrar por Estado", ["abierta", "en_revision", "resuelta", "descartada"],
            default=["abierta", "en_revision"],
        )
    with col_f3:
        dias_inc = st.slider("Ventana de días", 1, 90, 30)

    fecha_inicio_inc = (datetime.now(timezone.utc) - timedelta(days=dias_inc)).isoformat()
    
    sev_list = sev_filtro if sev_filtro else ["baja", "media", "alta", "critica"]
    est_list = estado_filtro if estado_filtro else ["abierta", "en_revision", "resuelta", "descartada"]

    # Evita conflictos con vinculación de tuplas nativas en PostgreSQL
    sql_incidencias = f"""
        SELECT
            i.id, i.created_at as fecha_hora, i.tipo, i.descripcion,
            i.severidad, i.estado, i.score_anomalia, d.nombre as dispositivo
        FROM incidencias i
        LEFT JOIN dispositivos d ON d.id = i.dispositivo_id
        WHERE i.dispositivo_id = :dispositivo_id
          AND i.severidad IN ({','.join([f"'{s}'" for s in sev_list])})
          AND i.estado IN ({','.join([f"'{e}'" for e in est_list])})
          AND i.created_at >= :fecha_inicio_inc
        ORDER BY i.created_at DESC LIMIT 500
    """

    df_inc = query_df(sql_incidencias, params={
        "dispositivo_id": dispositivo_id,
        "fecha_inicio_inc": fecha_inicio_inc
    })

    total_inc = len(df_inc)
    criticas = len(df_inc[df_inc["severidad"] == "critica"]) if not df_inc.empty else 0
    abiertas = len(df_inc[df_inc["estado"] == "abierta"]) if not df_inc.empty else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("Total incidencias", total_inc)
    m2.metric("Críticas", criticas, delta="Acción requerida" if criticas > 0 else "Sin alertas críticas")
    m3.metric("Abiertas / En revisión", abiertas)

    st.divider()

    if df_inc.empty:
        st.success("No se registran incidencias bajo los filtros seleccionados.")
    else:
        st.markdown('<div class="section-header">Distribución de incidencias por severidad temporal</div>', unsafe_allow_html=True)
        df_inc["fecha"] = pd.to_datetime(df_inc["fecha_hora"]).dt.date
        df_grouped = df_inc.groupby(["fecha", "severidad"]).size().reset_index(name="count")
        
        fig_inc = px.bar(
            df_grouped, x="fecha", y="count", color="severidad",
            color_discrete_map=SEVERIDAD_COLORS,
            labels={"fecha": "", "count": "Incidencias", "severidad": "Severidad"},
            barmode="stack",
        )
        fig_inc.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#94a3b8", height=280, margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#1e293b"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_inc, width='stretch')

        st.markdown('<div class="section-header">Historial detallado de eventos eléctricos</div>', unsafe_allow_html=True)

        def badge(sev: str) -> str:
            return f'<span class="badge-{sev}">{sev.upper()}</span>'

        for _, row in df_inc.iterrows():
            with st.container():
                c1, c2, c3, c4, c5 = st.columns([2, 3, 2, 1.5, 1])
                ts_val = pd.to_datetime(row["fecha_hora"])
                if ts_val.tz is None:
                    ts_val = ts_val.replace(tzinfo=ZoneInfo("UTC"))
                ts = ts_val.astimezone(ZoneInfo("America/Caracas")).strftime("%d/%m/%Y %H:%M:%S")
                c1.markdown(f"`{ts}`")
                c2.markdown(f"**{row['tipo']}** — {str(row['descripcion'])[:80]}")
                c3.markdown(f"Dispositivo: {row['dispositivo']}")
                c4.markdown(badge(row["severidad"]), unsafe_allow_html=True)
                score_val = row["score_anomalia"]
                score_str = f"{float(score_val):.2f}" if score_val is not None else "—"
                c5.markdown(f"score: `{score_str}`")
            st.divider()

        pdf_bytes = _gen_pdf_incidencias(df_inc)
        st.download_button(
            "Descargar incidencias filtradas (PDF)",
            data=pdf_bytes,
            file_name=f"incidencias_{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
        )

# ══════════════════════════════════════════════════════════════════════════════
# PÁGINA 5: SISTEMA
# ══════════════════════════════════════════════════════════════════════════════

elif pagina == "Sistema":
    st.title("Configuración de la Cuenta")

    user = st.session_state.get("user", {})

    st.markdown('<div class="section-header">Datos de la Cuenta</div>', unsafe_allow_html=True)
    st.caption("Actualiza tu email o nombre de usuario.")

    col_e1, col_e2 = st.columns([3, 1])
    current_email = user.get("email", "")
    email_input = col_e1.text_input(
        "Correo electrónico",
        value=current_email,
        key="email_input",
        label_visibility="collapsed",
        placeholder="correo@ejemplo.com",
    )
    if col_e2.button("Guardar Email", type="primary", use_container_width=True):
        if email_input.strip() and email_input.strip() != current_email:
            res = api_patch("/api/v1/auth/me", {"email": email_input.strip()})
            if res:
                st.success("✅ Email actualizado correctamente")
                st.session_state.user["email"] = email_input.strip()
            else:
                st.error("Error — ese email podría estar ya registrado")
        else:
            st.info("No hay cambios en el email.")

    col_u1, col_u2 = st.columns([3, 1])
    current_username = user.get("username", "")
    username_input = col_u1.text_input(
        "Nombre de usuario",
        value=current_username,
        key="username_input",
        label_visibility="collapsed",
        placeholder="nombre_usuario",
    )
    if col_u2.button("Guardar Usuario", type="primary", use_container_width=True):
        if username_input.strip() and username_input.strip() != current_username:
            res = api_patch("/api/v1/auth/me", {"username": username_input.strip()})
            if res:
                st.success("✅ Usuario actualizado correctamente")
                st.session_state.user["username"] = username_input.strip()
            else:
                st.error("Error — ese nombre de usuario podría estar ya registrado")
        else:
            st.info("No hay cambios en el usuario.")

    st.divider()

    st.markdown('<div class="section-header">Notificaciones Telegram</div>', unsafe_allow_html=True)
    st.caption("Vincula tu ID de Telegram para recibir alertas de anomalías en tus dispositivos.")

    col_tg1, col_tg2 = st.columns([3, 1])
    current_tg = user.get("telegram_id", "")
    tg_input = col_tg1.text_input(
        "ID de Telegram (ej: 1885567115)",
        value=current_tg if current_tg else "",
        key="tg_id_input",
        label_visibility="collapsed",
        placeholder="Ej: 1885567115",
    )
    if col_tg2.button("Guardar", type="primary", use_container_width=True):
        if tg_input.strip().isdigit():
            res = api_put("/api/v1/auth/telegram", {"telegram_id": int(tg_input.strip())})
            if res:
                st.success("✅ ID de Telegram guardado correctamente")
                st.session_state.user["telegram_id"] = str(tg_input.strip())
                st.cache_data.clear()
            else:
                st.error("Error al guardar — verifica que el backend esté corriendo")
        else:
            st.error("El ID debe ser un número (ej: 1885567115)")

    import requests
    if st.button("📨 Probar Telegram", type="secondary", use_container_width=True):
        with st.spinner("Enviando mensaje de prueba..."):
            token = st.session_state.get("token", "")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            try:
                r = requests.post(f"{API_BASE}/api/v1/auth/telegram/test", json={}, headers=headers, timeout=10)
                if r.ok:
                    st.success("✅ Mensaje de prueba enviado — revisa tu Telegram")
                else:
                    st.error(f"❌ {r.json().get('detail', 'Error desconocido')}")
            except Exception:
                st.error("❌ Backend sin conexión")

    st.divider()

    # ── Contactos de notificación por dispositivo ──────────────────────────
    st.markdown('<div class="section-header">Contactos de Notificación</div>', unsafe_allow_html=True)
    st.caption("Agrega contactos (hasta 3 por dispositivo) que recibirán alertas por Telegram o Email.")

    df_mis_dispositivos = get_user_devices(uid)
    if not df_mis_dispositivos.empty:
        ROL_OPCIONES = ["tecnico", "emergencia", "distribuidor", "conocidos", "familiar", "proveedor"]
        ROL_LABELS = {
            "tecnico": "Técnico", "emergencia": "Emergencia", "distribuidor": "Distribuidor",
            "conocidos": "Conocidos", "familiar": "Familiar", "proveedor": "Proveedor",
        }

        selected_device_label = st.selectbox(
            "Selecciona un dispositivo para gestionar contactos",
            [f"{r['nombre']} (ID {r['id']})" for _, r in df_mis_dispositivos.iterrows()],
            key="contacto_device_select",
        )
        selected_device_id = int(selected_device_label.split("ID ")[-1].rstrip(")"))

        contactos = api_get(f"/api/v1/contactos/{selected_device_id}") or []
        if contactos:
            st.markdown(f"**{len(contactos)}/3** contactos registrados:")
            for c in contactos:
                canal = []
                if c.get("telegram_id"):
                    canal.append(f"TG: {c['telegram_id']}")
                if c.get("email"):
                    canal.append(f"Email: {c['email']}")
                col1, col2 = st.columns([5, 1])
                col1.markdown(
                    f"{'🟢' if c.get('is_active') else '🔴'} "
                    f"**{c['nombre']}** — {ROL_LABELS.get(c.get('rol', ''), c.get('rol', ''))} — {', '.join(canal)}"
                )
                if col2.button("🗑️", key=f"del_contacto_{c['id']}"):
                    res = api_delete(f"/api/v1/contactos/{c['id']}")
                    if res:
                        st.success("Contacto eliminado")
                        st.rerun()
                    else:
                        st.error("Error al eliminar")
        else:
            st.info("No hay contactos registrados para este dispositivo.")

        if len(contactos) < 3:
            with st.expander("➕ Agregar nuevo contacto"):
                with st.form("form_nuevo_contacto"):
                    cn_nombre = st.text_input("Nombre del contacto", placeholder="Ej: Juan Pérez")
                    cn_tg = st.text_input("Telegram ID (opcional)", placeholder="Ej: 1885567115")
                    cn_email = st.text_input("Email (opcional)", placeholder="Ej: juan@ejemplo.com")
                    cn_rol = st.selectbox("Rol", ROL_OPCIONES, format_func=lambda x: ROL_LABELS[x])
                    submitted = st.form_submit_button("Guardar contacto", type="primary")
                    if submitted:
                        if not cn_nombre.strip():
                            st.error("El nombre es obligatorio")
                        elif not cn_tg.strip() and not cn_email.strip():
                            st.error("Debes proporcionar al menos un Telegram ID o un Email")
                        elif cn_tg.strip() and not cn_tg.strip().isdigit():
                            st.error("El Telegram ID debe ser numérico (ej: 1885567115)")
                        elif cn_email.strip() and "@" not in cn_email.strip():
                            st.error("El email debe tener un formato válido (ej: usuario@dominio.com)")
                        else:
                            payload = {
                                "dispositivo_id": selected_device_id,
                                "nombre": cn_nombre.strip(),
                                "rol": cn_rol,
                            }
                            if cn_tg.strip():
                                payload["telegram_id"] = cn_tg.strip()
                            if cn_email.strip():
                                payload["email"] = cn_email.strip()
                            res = api_post("/api/v1/contactos", payload)
                            if res and not res.get("error"):
                                st.success("Contacto agregado")
                                st.rerun()
                            else:
                                detail = res.get("detail", res.get("error", "Error desconocido")) if res else "Backend sin conexión"
                                st.error(f"Error: {detail}")
    else:
        st.info("Asigna un dispositivo primero para poder agregar contactos de notificación.")

    st.divider()
    st.markdown('<div class="section-header">Dispositivos</div>', unsafe_allow_html=True)

    df_asignados = get_user_devices(uid)
    if not df_asignados.empty:
        st.caption(f"Tienes **{len(df_asignados)}** dispositivo(s) asignado(s):")
        for _, row in df_asignados.iterrows():
            st.markdown(f"- ✅ {row['nombre']} (ID {row['id']})")
    else:
        st.info("No tienes dispositivos asignados.")

    df_libres = query_df(
        "SELECT id, nombre FROM dispositivos WHERE is_active = TRUE AND usuario_id IS NULL",
    )
    if not df_libres.empty:
        st.markdown("##### Asignar un dispositivo nuevo")
        opts = {f"{r['nombre']} (ID {r['id']})": r['id'] for _, r in df_libres.iterrows()}
        selected_label = st.selectbox("Selecciona un dispositivo disponible", list(opts.keys()), label_visibility="collapsed")
        if st.button("🔗 Asignar este dispositivo", type="primary", use_container_width=True):
            res = api_post("/api/v1/auth/asignar-dispositivo", {"dispositivo_id": opts[selected_label]})
            if res:
                st.success(f"✅ {res['mensaje']}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Error al asignar — verifica que el backend esté corriendo")
    else:
        st.caption("No hay dispositivos libres disponibles.")

    # fin página Sistema