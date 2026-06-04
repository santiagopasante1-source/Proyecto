"""
dashboard.py
────────────
Dashboard de monitoreo IoT en tiempo real.
Ejecutar con:   streamlit run dashboard.py

Páginas:
   Tiempo Real    — gráficos de voltaje/corriente en vivo desde la API
   Histórico      — comportamiento por día/semana/mes desde la BD
   Incidencias    — registro de eventos anómalos con nivel de criticidad
   Sistema        — estado de salud del backend y del motor de IA
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ── Cargar variables de entorno del archivo .env
load_dotenv()

# ── Configuración de página 

st.set_page_config(
    page_title="IoT Anomaly Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constantes configurables 

API_BASE = "http://localhost:8000"

# Leer la base de datos desde las variables de entorno orientadas a PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DB_URL = DATABASE_URL

REFRESH_INTERVAL_S = 3                                         # Segundos entre actualizaciones en tiempo real
MAX_REALTIME_POINTS = 60                                       # Puntos visibles en el gráfico en vivo
SEVERIDAD_COLORS = {
    "baja":     "#3B82F6",   # azul
    "media":    "#F59E0B",   # ámbar
    "alta":     "#EF4444",   # rojo
    "critica": "#7C3AED",   # púrpura
}

# ── Helpers de acceso a datos ─────────────────────────────────────────────────

@st.cache_resource
def get_db_engine():
    """Crea el engine de SQLAlchemy para PostgreSQL Neon (cacheado por Streamlit)."""
    return create_engine(
        DB_URL, 
        pool_pre_ping=True, 
        execution_options={"isolation_level": "AUTOCOMMIT"}
    )


def api_get(endpoint: str, timeout: int = 5) -> dict | None:
    try:
        r = requests.get(f"{API_BASE}{endpoint}", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def api_post(endpoint: str, payload: dict, timeout: int = 5) -> dict | None:
    try:
        r = requests.post(f"{API_BASE}{endpoint}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def query_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Ejecuta una consulta SQL y devuelve un DataFrame. Devuelve vacío en error."""
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            return pd.read_sql_query(text(sql), conn, params=params or {})
    except Exception as exc:
        st.warning(f"Error de base de datos: {exc}")
        return pd.DataFrame()


# ── Estilos globales ──────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Ocultar el menú hamburguesa de Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Tarjetas de métricas personalizadas */
    .metric-card {
        background: linear-gradient(135deg, #1e293b, #0f172a);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 16px 20px;
        margin: 4px 0;
    }
    .metric-title { color: #94a3b8; font-size: 13px; margin-bottom: 4px; }
    .metric-value { color: #f1f5f9; font-size: 28px; font-weight: 700; }
    .metric-delta { font-size: 12px; margin-top: 2px; }
    .delta-ok   { color: #22c55e; }
    .delta-warn { color: #f59e0b; }
    .delta-crit { color: #ef4444; }

    /* Badges de severidad */
    .badge-baja    { background:#1d4ed8;color:#bfdbfe;padding:2px 10px;border-radius:99px;font-size:12px; }
    .badge-media   { background:#92400e;color:#fde68a;padding:2px 10px;border-radius:99px;font-size:12px; }
    .badge-alta    { background:#991b1b;color:#fecaca;padding:2px 10px;border-radius:99px;font-size:12px; }
    .badge-critica { background:#5b21b6;color:#e9d5ff;padding:2px 10px;border-radius:99px;font-size:12px; }

    /* Separador de sección */
    .section-header {
        font-size: 16px; font-weight: 600; color: #e2e8f0;
        border-left: 3px solid #6366f1; padding-left: 10px; margin: 20px 0 12px;
    }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/circuit.png", width=64)
    st.title("IoT Monitor ⚡")
    st.caption("Sistema de detección de anomalías eléctricas")
    st.divider()

    pagina = st.radio(
        "Navegación",
        ["Tiempo Real", "Histórico", "Incidencias", "Sistema"],
        label_visibility="collapsed",
    )
    st.divider()

    # Selector de dispositivo con soporte estricto de PostgreSQL (is_active = TRUE)
    df_disp = query_df("SELECT id, nombre FROM dispositivos WHERE is_active = TRUE")
        
    if not df_disp.empty:
        dispositivo_id = st.selectbox(
            "Dispositivo activo",
            options=df_disp["id"].tolist(),
            format_func=lambda i: df_disp.loc[df_disp["id"] == i, "nombre"].values[0],
        )
    else:
        dispositivo_id = 1
        st.warning("No hay dispositivos activos en la BD.")

    st.caption(f"API: `{API_BASE}`")

    # Indicador de salud del API
    health = api_get("/health")
    if health and health.get("status") == "ok":
        st.success("Backend ✓ conectado")
    else:
        st.error("Backend ✗ sin conexión")

# ══════════════════════════════════════════════════════════════════════════════
# PÁGINA 1: TIEMPO REAL
# ══════════════════════════════════════════════════════════════════════════════

if pagina == "Tiempo Real":
    st.title("Monitoreo en Tiempo Real")
    st.caption("Los gráficos se actualizan automáticamente consultando la API y la base de datos.")
    st.write(f"⏱️ Reloj del sistema: {datetime.now().strftime('%H:%M:%S')}")
    # Estado en vivo del último registro
    col1, col2, col3, col4 = st.columns(4)

    df_ultimo = query_df(f"""
        SELECT voltaje, corriente, potencia, frecuencia, timestamp, anomalia_detectada
        FROM telemetrias
        WHERE dispositivo_id = {dispositivo_id}
        ORDER BY timestamp DESC LIMIT 1
    """)

    if not df_ultimo.empty:
        row = df_ultimo.iloc[0]
        v, i, p, f = row["voltaje"], row["corriente"], row["potencia"], row.get("frecuencia", 0)
        
        # ── 1. RESPALDO POR REGLAS DE INGENIERÍA ──
        # Parámetros nominales estándar: Voltaje (100V - 140V) | Frecuencia (59Hz - 61Hz)
        voltaje_fuera = (v < 100.0 or v > 140.0)
        frecuencia_fuera = (f < 59.0 or f > 61.0) if f > 0 else False
        corriente_fuera = (i > 15.0) 
        
        es_anomalia_ia = bool(row["anomalia_detectada"])
        es_anomalia_regla = (voltaje_fuera or frecuencia_fuera or corriente_fuera)
        
        # El sistema alerta si la IA lo detecta O si se rompe una regla física
        es_anomalia = es_anomalia_ia or es_anomalia_regla

        # ── 2. COLORES DINÁMICOS PARA LOS BORDES DE LAS TARJETAS ──
        v_border = "#EF4444" if voltaje_fuera else "#334155"
        i_border = "#EF4444" if corriente_fuera else "#334155"
        p_border = "#334155"  
        f_border = "#EF4444" if frecuencia_fuera else "#334155"

        # Función helper actualizada para recibir el color del borde dinámico
        def metric_html(title, value, unit, border_color="#334155"):
            return f"""
            <div class="metric-card" style="border: 2px solid {border_color}; transition: border 0.5s ease;">
              <div class="metric-title">{title}</div>
              <div class="metric-value">{value:.2f} <span style="font-size:14px;color:#64748b">{unit}</span></div>
            </div>"""

        # Dibujar las tarjetas con sus respectivos colores de alerta
        col1.markdown(metric_html("⚡ Voltaje", v, "V", v_border), unsafe_allow_html=True)
        col2.markdown(metric_html("🔌 Corriente", i, "A", i_border), unsafe_allow_html=True)
        col3.markdown(metric_html("🔥 Potencia", p or 0, "W", p_border), unsafe_allow_html=True)
        col4.markdown(metric_html("📈 Frecuencia", f or 0, "Hz", f_border), unsafe_allow_html=True)

        st.write("") # Espaciador

        # ── 3. ALERTAS DINÁMICAS (Lógica de Banners) ──
        if es_anomalia_ia:
            st.error("🚨 **ANOMALÍA CRÍTICA DETECTADA POR IA (Bi-LSTM)** — El modelo predictivo ha identificado un patrón de riesgo.")
        elif es_anomalia_regla:
            st.warning("⚠️ **ALERTA DE SEGURIDAD (Umbral Físico)** — Valores fuera de rangos nominales. El motor analítico de respaldo ha asegurado la lectura.")
        else:
            st.success("✅ **Operación Eléctrica Normal** — Parámetros estables y validados por el sistema híbrido.")
            
    else:
        st.info("No hay datos de telemetría para este dispositivo aún.")

    st.divider()

    # ── 4. GRÁFICOS DE SERIE TEMPORAL (Últimos N registros) ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown('<div class="section-header">Voltaje en el tiempo</div>', unsafe_allow_html=True)
        df_v = query_df(f"""
            SELECT timestamp, voltaje, anomalia_detectada
            FROM telemetrias
            WHERE dispositivo_id = {dispositivo_id}
            ORDER BY timestamp DESC LIMIT {MAX_REALTIME_POINTS}
        """)
        if not df_v.empty:
            df_v = df_v.sort_values("timestamp")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_v["timestamp"], y=df_v["voltaje"],
                mode="lines+markers",
                line=dict(color="#6366f1", width=2),
                marker=dict(
                    color=df_v["anomalia_detectada"].map({True: "#ef4444", False: "#6366f1"}),
                    size=6,
                ),
                name="Voltaje (V)",
            ))
            fig.add_hline(y=120, line_dash="dash", line_color="#22c55e", annotation_text="Nominal 120V")
            fig.add_hrect(y0=108, y1=132, fillcolor="#22c55e", opacity=0.05, line_width=0)
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#94a3b8", margin=dict(l=0, r=0, t=10, b=0),
                xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#1e293b"),
                showlegend=False, height=280,
            )
            st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.markdown('<div class="section-header">Corriente en el tiempo</div>', unsafe_allow_html=True)
        df_i = query_df(f"""
            SELECT timestamp, corriente, anomalia_detectada
            FROM telemetrias
            WHERE dispositivo_id = {dispositivo_id}
            ORDER BY timestamp DESC LIMIT {MAX_REALTIME_POINTS}
        """)
        if not df_i.empty:
            df_i = df_i.sort_values("timestamp")
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=df_i["timestamp"], y=df_i["corriente"],
                mode="lines+markers",
                line=dict(color="#f59e0b", width=2),
                marker=dict(
                    color=df_i["anomalia_detectada"].map({True: "#ef4444", False: "#f59e0b"}),
                    size=6,
                ),
                name="Corriente (A)",
            ))
            fig2.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#94a3b8", margin=dict(l=0, r=0, t=10, b=0),
                xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#1e293b"),
                showlegend=False, height=280,
            )
            st.plotly_chart(fig2, use_container_width=True)

    # ── 5. DISTRIBUCIÓN DE ANOMALÍAS (GAUGE) ──
    st.markdown('<div class="section-header">Tasa de anomalías (últimas 100 muestras)</div>', unsafe_allow_html=True)
    
    df_rate = query_df(f"""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN anomalia_detectada THEN 1 ELSE 0 END) as anomalias
        FROM (
            SELECT anomalia_detectada FROM telemetrias
            WHERE dispositivo_id = {dispositivo_id}
            ORDER BY timestamp DESC LIMIT 100
        ) sub_rate
    """)
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
        st.plotly_chart(fig_gauge, use_container_width=True)

    # Auto-refresh
    st.caption(f"🔄 Actualización automática cada {REFRESH_INTERVAL_S}s")
    time.sleep(REFRESH_INTERVAL_S)
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PÁGINA 2: HISTÓRICO
# ══════════════════════════════════════════════════════════════════════════════

elif pagina == "Histórico":
    st.title("Análisis Histórico")

    # Selector de rango temporal
    rango = st.radio(
        "Período de análisis",
        ["Hoy", "Última semana", "Último mes"],
        horizontal=True,
    )
    dias = {"Hoy": 1, "Última semana": 7, "Último mes": 30}[rango]
    fecha_inicio = (datetime.utcnow() - timedelta(days=dias)).isoformat()

    # ── Agregados por hora/día adaptados estructuralmente para PostgreSQL ──
    sql_historico = f"""
        SELECT
            DATE(timestamp) as fecha,
            TO_CHAR(timestamp, 'HH24') as hora,
            AVG(voltaje)   as voltaje_avg,
            MAX(voltaje)   as voltaje_max,
            MIN(voltaje)   as voltaje_min,
            AVG(corriente) as corriente_avg,
            AVG(potencia)  as potencia_avg,
            COUNT(*)                                                           as total,
            SUM(CASE WHEN anomalia_detectada THEN 1 ELSE 0 END) as anomalias
        FROM telemetrias
        WHERE dispositivo_id = {dispositivo_id}
          AND timestamp >= '{fecha_inicio}'
        GROUP BY DATE(timestamp), TO_CHAR(timestamp, 'HH24')
        ORDER BY fecha, hora
    """

    df_hist = query_df(sql_historico)

    if df_hist.empty:
        st.info("No hay datos históricos para el período seleccionado.")
    else:
        df_hist["datetime"] = pd.to_datetime(df_hist["fecha"].astype(str) + " " + df_hist["hora"].astype(str) + ":00")
        df_hist["tasa_anomalia"] = (df_hist["anomalias"] / df_hist["total"] * 100).round(1)

        # KPIs en la cabecera
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Voltaje promedio", f"{df_hist['voltaje_avg'].mean():.1f} V")
        kpi2.metric("Corriente promedio", f"{df_hist['corriente_avg'].mean():.2f} A")
        kpi3.metric("Total registros", f"{int(df_hist['total'].sum()):,}")
        kpi4.metric("Anomalías totales", f"{int(df_hist['anomalias'].sum()):,}",
                    delta=f"{df_hist['tasa_anomalia'].mean():.1f}% tasa",
                    delta_color="inverse")

        st.divider()

        # Gráfico de voltaje con banda min/max
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
        st.plotly_chart(fig_v, use_container_width=True)

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown('<div class="section-header">Potencia consumida por hora</div>', unsafe_allow_html=True)
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
            st.plotly_chart(fig_p, use_container_width=True)

        with col_b:
            st.markdown('<div class="section-header">Tasa de anomalías (%) por hora</div>', unsafe_allow_html=True)
            df_hist["color"] = df_hist["tasa_anomalia"].apply(
                lambda x: "#ef4444" if x > 20 else ("#f59e0b" if x > 5 else "#22c55e")
            )
            fig_t = go.Figure(go.Bar(
                x=df_hist["datetime"],
                y=df_hist["tasa_anomalia"],
                marker_color=df_hist["color"],
            ))
            fig_t.add_hline(y=5, line_dash="dash", line_color="#f59e0b", annotation_text="Umbral 5%")
            fig_t.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#94a3b8", height=280, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title="% anomalías", xaxis=dict(showgrid=False),
                yaxis=dict(gridcolor="#1e293b"),
            )
            st.plotly_chart(fig_t, use_container_width=True)

        # Tabla de resumen por día
        st.markdown('<div class="section-header">Resumen diario</div>', unsafe_allow_html=True)
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
                "voltaje_prom": "V prom (V)", "corriente_prom": "I prom (A)", "tasa": "Tasa",
            }),
            use_container_width=True, hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# PÁGINA 3: INCIDENCIAS
# ══════════════════════════════════════════════════════════════════════════════

elif pagina == "Incidencias":
    st.title("Registro de Incidencias")
    st.caption("Historial completo de anomalías detectadas, con fecha, hora y nivel de criticidad.")

    # Filtros
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        sev_filtro = st.multiselect(
            "Severidad", ["baja", "media", "alta", "critica"],
            default=["media", "alta", "critica"],
        )
    with col_f2:
        estado_filtro = st.multiselect(
            "Estado", ["abierta", "en_revision", "resuelta", "descartada"],
            default=["abierta", "en_revision"],
        )
    with col_f3:
        dias_inc = st.slider("Últimos días", 1, 90, 30)

    fecha_inicio_inc = (datetime.utcnow() - timedelta(days=dias_inc)).isoformat()
    sev_str = ", ".join(f"'{s}'" for s in sev_filtro) or "'baja','media','alta','critica'"
    est_str = ", ".join(f"'{e}'" for e in estado_filtro) or "'abierta','en_revision','resuelta','descartada'"

    df_inc = query_df(f"""
        SELECT
            i.id,
            i.created_at as fecha_hora,
            i.tipo,
            i.descripcion,
            i.severidad,
            i.estado,
            i.score_anomalia,
            d.nombre as dispositivo
        FROM incidencias i
        LEFT JOIN dispositivos d ON d.id = i.dispositivo_id
        WHERE i.dispositivo_id = {dispositivo_id}
          AND i.severidad IN ({sev_str})
          AND i.estado IN ({est_str})
          AND i.created_at >= '{fecha_inicio_inc}'
        ORDER BY i.created_at DESC
        LIMIT 500
    """)

    # KPIs rápidos
    total_inc = len(df_inc)
    criticas = len(df_inc[df_inc["severidad"] == "critica"]) if not df_inc.empty else 0
    abiertas = len(df_inc[df_inc["estado"] == "abierta"]) if not df_inc.empty else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("Total incidencias", total_inc)
    m2.metric("Críticas", criticas, delta="Requieren atención" if criticas > 0 else "Sin críticas")
    m3.metric("Abiertas", abiertas)

    st.divider()

    if df_inc.empty:
        st.success("No hay incidencias para los filtros seleccionados.")
    else:
        # Gráfico de barras apiladas por severidad en el tiempo
        st.markdown('<div class="section-header">Distribución de incidencias por severidad</div>', unsafe_allow_html=True)
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
        st.plotly_chart(fig_inc, use_container_width=True)

        # Tabla de eventos
        st.markdown('<div class="section-header">Historial detallado de eventos</div>', unsafe_allow_html=True)

        def badge(sev: str) -> str:
            return f'<span class="badge-{sev}">{sev.upper()}</span>'

        # Renderizado fila por fila con badge HTML
        for _, row in df_inc.iterrows():
            with st.container():
                c1, c2, c3, c4, c5 = st.columns([2, 3, 2, 1.5, 1])
                ts = pd.to_datetime(row["fecha_hora"]).strftime("%d/%m/%Y %H:%M:%S")
                c1.markdown(f"🕐 `{ts}`")
                c2.markdown(f"**{row['tipo']}** — {str(row['descripcion'])[:80]}")
                c3.markdown(f"📟 {row['dispositivo']}")
                c4.markdown(badge(row["severidad"]), unsafe_allow_html=True)
                score_val = row["score_anomalia"]
                score_str = f"{float(score_val):.2f}" if score_val is not None else "—"
                c5.markdown(f"score: `{score_str}`")
            st.divider()

        # Descarga CSV
        csv_data = df_inc.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Descargar incidencias como CSV",
            data=csv_data,
            file_name=f"incidencias_{datetime.utcnow().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )


# ══════════════════════════════════════════════════════════════════════════════
# PÁGINA 4: SISTEMA
# ══════════════════════════════════════════════════════════════════════════════

elif pagina == "Sistema":
    st.title("Estado del Sistema")

    col1, col2 = st.columns(2)

    # Estado del backend
    with col1:
        st.markdown('<div class="section-header">Backend FastAPI</div>', unsafe_allow_html=True)
        health = api_get("/health")
        if health:
            st.success("Conectado")
            st.json(health)
        else:
            st.error(f"No se puede conectar a {API_BASE}/health")
            st.info("¿Está corriendo el servidor FastAPI?")

    # Estado del motor de IA
    with col2:
        st.markdown('<div class="section-header">Motor de IA</div>', unsafe_allow_html=True)
        ia_status = api_get("/ia/status")
        if ia_status:
            modo = ia_status.get("mode", "—")
            listo = ia_status.get("ready", False)
            if listo:
                st.success(f"Modo: **{modo.upper()}** — Listo para inferencia")
            else:
                st.warning(f"Modo: **{modo}** — No listo")
            st.json(ia_status)
        else:
            st.error("No se puede obtener el estado del motor de IA.")

    st.divider()

    # Prueba manual de inferencia
    st.markdown('<div class="section-header">Prueba de inferencia en vivo</div>', unsafe_allow_html=True)
    st.caption("Envía valores manuales al motor de IA para ver el resultado en tiempo real.")

    tc1, tc2, tc3 = st.columns(3)
    test_v = tc1.number_input("Voltaje (V)", value=120.0, min_value=0.0, max_value=1000.0, step=0.5)
    test_i = tc2.number_input("Corriente (A)", value=10.0, min_value=0.0, max_value=500.0, step=0.1)
    test_f = tc3.number_input("Frecuencia (Hz)", value=60.0, min_value=0.0, max_value=200.0, step=0.5)

    if st.button("🔍 Analizar", type="primary"):
        resultado = api_post("/analizar", {
            "voltaje": test_v,
            "corriente": test_i,
            "frecuencia": test_f,
        })
        if resultado:
            if resultado.get("anomalia"):
                st.error(f"**ANOMALÍA** — Tipo: `{resultado.get('tipo')}` — Score: `{resultado.get('score', 0):.3f}`")
            else:
                st.success(f"Normal — Score: `{resultado.get('score', 0):.3f}`")
            with st.expander("Respuesta completa del backend"):
                st.json(resultado)
        else:
            st.error("Error al conectar con el backend.")

    st.divider()

    # Estadísticas generales de la BD
    st.markdown('<div class="section-header">Resumen de base de datos</div>', unsafe_allow_html=True)
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
        s1.metric("Registros telemetría", f"{int(row['total_telemetrias']):,}")
        s2.metric("Incidencias totales", f"{int(row['total_incidencias']):,}")
        s3.metric("Dispositivos", int(row["total_dispositivos"]))
        s4.metric("Usuarios", int(row["total_usuarios"]))