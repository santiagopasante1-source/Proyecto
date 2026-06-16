"""
dashboard.py
────────────
Dashboard de monitoreo IoT en tiempo real con detección de anomalías por Deep Learning.
Ejecutar con:   streamlit run dashboard.py

Páginas:
   Tiempo Real    — Gráfico unificado de oscilación (V/I) en vivo y métricas híbridas
   Histórico      — Comportamiento por día/semana/mes desde la BD PostgreSQL (Neon)
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

# ── Cargar variables de entorno del archivo .env
load_dotenv()

# ── Configuración de página 
st.set_page_config(
    page_title="IoT Anomaly Monitor",
    page_icon="chart_with_upwards_trend",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constantes configurables 
API_BASE = os.getenv("API_BASE", "http://localhost:8000")

# Leer la base de datos desde las variables de entorno orientadas a PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DB_URL = DATABASE_URL

REFRESH_INTERVAL_S = 12                                        # Segundos entre actualizaciones en tiempo real
MAX_REALTIME_POINTS = 60                                       # Puntos visibles en el gráfico en vivo
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
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


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


# ── Helper PDF ────────────────────────────────────────────────────────────────

def _gen_pdf_incidencias(df):
    """Genera un PDF con tabla de incidencias."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Reporte de Incidencias", ln=True, align="C")
    pdf.ln(5)
    pdf.set_font("Arial", "", 9)
    pdf.cell(0, 6, f"Generado: {datetime.now(ZoneInfo('America/Caracas')).strftime('%d/%m/%Y %H:%M')} (Venezuela)", ln=True)
    pdf.ln(5)

    col_w = [12, 30, 25, 63, 16, 22, 22]
    headers = ["ID", "Fecha/Hora", "Tipo", "Descripcion", "Severidad", "Estado", "Score"]

    pdf.set_font("Arial", "B", 7)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=1)
    pdf.ln()

    pdf.set_font("Arial", "", 7)
    for _, r in df.iterrows():
        ts = pd.to_datetime(r["fecha_hora"])
        if ts.tz is None:
            ts = ts.replace(tzinfo=ZoneInfo("UTC"))
        ts_str = ts.astimezone(ZoneInfo("America/Caracas")).strftime("%d/%m/%Y %H:%M")
        desc = str(r.get("descripcion", ""))[:55]
        score = f"{float(r['score_anomalia']):.2f}" if r.get("score_anomalia") is not None else "-"
        row_data = [
            str(r["id"]), ts_str, str(r["tipo"])[:12], desc,
            str(r["severidad"])[:8], str(r["estado"])[:10], score,
        ]
        for i, v in enumerate(row_data):
            pdf.cell(col_w[i], 6, v.encode("latin-1", errors="replace").decode("latin-1"), border=1)
        pdf.ln()

    result = pdf.output(dest="S")
    return bytes(result)


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
</style>
""", unsafe_allow_html=True)


# ── Auth state ────────────────────────────────────────────────────────────────

if "token" not in st.session_state:
    st.session_state.token = None
if "user" not in st.session_state:
    st.session_state.user = None
if "login_success" not in st.session_state:
    st.session_state.login_success = False

# ── Login / Register page ─────────────────────────────────────────────────────

if not st.session_state.token:
    st.title("Inicio de Sesión")
    with st.form("login_form"):
        l_user = st.text_input("Usuario")
        l_pass = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar", type="primary"):
            with st.spinner("Iniciando sesión..."):
                res = api_post_auth("/api/v1/auth/login", {"username": l_user, "password": l_pass})
            if res:
                st.session_state.token = res["access_token"]
                st.session_state.user = res["user"]
                st.session_state.login_success = True
                st.rerun()
            else:
                st.error("Credenciales inválidas o backend sin conexión")

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
        ["Tiempo Real", "Histórico", "Incidencias", "Sistema"],
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

    # ── 5. DISTRIBUCIÓN DE ANOMALÍAS (GAUGE) ──
    st.markdown('<div class="section-header">Tasa de anomalías (últimas 100 muestras)</div>', unsafe_allow_html=True)
    
    sql_rate = """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN anomalia_detectada THEN 1 ELSE 0 END) as anomalias
        FROM (
            SELECT anomalia_detectada FROM telemetrias
            WHERE dispositivo_id = :dispositivo_id
            ORDER BY timestamp DESC LIMIT 100
        ) sub_rate
    """
    df_rate = query_df(sql_rate, params={"dispositivo_id": dispositivo_id})
    if not df_rate.empty and df_rate.iloc[0]["total"] > 0:
        row = df_rate.iloc[0]
        tasa = (row["anomalias"] / row["total"]) * 100
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=tasa,
            number={"suffix": "%", "font": {"color": "#f1f5f9"}},
            delta={"reference": 5, "increasing": {"color": "#ef4444"}, "decreasing": {"color": "#22c55e"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#475569"},
                "bar": {"color": "#6366f1"},
                "steps": [
                    {"range": [0, 5],   "color": "#14532d"},
                    {"range": [5, 20],  "color": "#78350f"},
                    {"range": [20, 100],"color": "#7f1d1d"},
                ],
                "threshold": {"line": {"color": "#ef4444", "width": 3}, "value": 20},
            },
            title={"text": "Tasa de anomalías", "font": {"color": "#94a3b8"}},
        ))
        fig_gauge.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", font_color="#94a3b8",
            height=250, margin=dict(l=20, r=20, t=40, b=0),
        )
        st.plotly_chart(fig_gauge, width='stretch')

    st.caption(f"Actualizacion automatica activa cada {REFRESH_INTERVAL_S}s")
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
# PÁGINA 3: INCIDENCIAS
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
# PÁGINA 4: SISTEMA
# ══════════════════════════════════════════════════════════════════════════════

elif pagina == "Sistema":
    st.title("Estado de Salud e Inferencia de Dispositivos")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown('<div class="section-header">Estatus Backend FastAPI</div>', unsafe_allow_html=True)
        health = api_get("/health")
        if health:
            st.success("Conectado exitosamente con el backend.")
            st.json(health)
        else:
            st.error(f"Imposible conectar con la dirección: {API_BASE}/health")
            st.info("Por favor verifica si el servicio de FastAPI se encuentra inicializado localmente.")

    with col2:
        st.markdown('<div class="section-header">Estatus Motor de IA (Bidirectional-LSTM)</div>', unsafe_allow_html=True)
        ia_status = api_get("/ia/status")
        if ia_status:
            modo = ia_status.get("mode", "—")
            listo = ia_status.get("ready", False)
            if listo:
                st.success(f"Modo actual: **{modo.upper()}** — Listo para inferencias de red en vivo.")
            else:
                st.warning(f"Modo: **{modo}** — El modelo se encuentra cargando estructuras o fuera de línea.")
            st.json(ia_status)
        else:
            st.error("Error crítico al recuperar el estado del modelo neuronal.")

    st.divider()

    st.markdown('<div class="section-header">Notificaciones Telegram</div>', unsafe_allow_html=True)
    st.caption("Vincula tu ID de Telegram para recibir alertas de anomalías en tus dispositivos.")

    col_tg1, col_tg2 = st.columns([3, 1])
    user = st.session_state.get("user", {})
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

    st.divider()

    st.markdown('<div class="section-header">Módulo de inferencia en vivo (Prueba Manual)</div>', unsafe_allow_html=True)
    st.caption("Inserta parámetros eléctricos directamente para evaluar el comportamiento predictivo del motor.")

    tc1, tc2, tc3 = st.columns(3)
    test_v = tc1.number_input("Voltaje Simulado (V)", value=120.0, min_value=0.0, max_value=1000.0, step=0.5)
    test_i = tc2.number_input("Corriente Simulada (A)", value=10.0, min_value=0.0, max_value=500.0, step=0.1)
    test_f = tc3.number_input("Frecuencia Simulada (Hz)", value=60.0, min_value=0.0, max_value=200.0, step=0.5)

    if st.button("Ejecutar Analisis Funcional", type="primary"):
        resultado = api_post("/analizar", {
            "voltaje": test_v,
            "corriente": test_i,
            "frecuencia": test_f,
        })
        if resultado:
            if resultado.get("anomalia"):
                st.error(f"**ANOMALIA CAPTURADA** — Tipo: `{resultado.get('tipo')}` — Score: `{resultado.get('score', 0):.3f}`")
            else:
                st.success(f"**Muestra Estable** — Comportamiento Electrico Seguro — Score: `{resultado.get('score', 0):.3f}`")
            with st.expander("Ver metadata cruda de respuesta del backend"):
                st.json(resultado)
        else:
            st.error("Error al establecer comunicación con el endpoint de inferencias.")

    st.divider()

    st.markdown('<div class="section-header">Métricas Estructurales de Base de Datos</div>', unsafe_allow_html=True)
    df_stats = query_df("""
        SELECT
            (SELECT COUNT(*) FROM telemetrias)  as total_telemetrias,
            (SELECT COUNT(*) FROM incidencias)  as total_incidencias,
            (SELECT COUNT(*) FROM dispositivos) as total_dispositivos,
            (SELECT COUNT(*) FROM usuarios)     as total_usuarios
    """)
    if not df_stats.empty:
        row = df_stats.iloc[0]
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Registros de Telemetría", f"{int(row['total_telemetrias']):,}")
        s2.metric("Historial de Incidencias", f"{int(row['total_incidencias']):,}")
        s3.metric("Dispositivos Registrados", int(row["total_dispositivos"]))
        s4.metric("Usuarios de Plataforma", int(row["total_usuarios"]))