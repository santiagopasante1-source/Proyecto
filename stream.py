import streamlit as st
import pandas as pd
import psycopg2
from app.services.ia_deep_learning import DeepAnomalyDetector
from app.core.config import settings

# Configuración de página
st.set_page_config(page_title="Monitoreo Eléctrico IA", layout="wide")

st.title("⚡ Dashboard de Monitoreo Eléctrico con IA")

# 1. Carga de Modelo (Caché para que no se recargue cada vez)
@st.cache_resource
def load_detector():
    # Asumiendo que tu clase DeepAnomalyDetector carga el .h5 internamente
    return DeepAnomalyDetector()

# 2. Conexión a Base de Datos (Uso de Secrets)
@st.cache_resource
def get_db_connection():
    # Recuerda: DATABASE_URL debe estar en Settings -> Secrets de Streamlit
    return psycopg2.connect(st.secrets["DATABASE_URL"])

# Ejecución de componentes
try:
    detector = load_detector()
    conn = get_db_connection()

    # 3. Obtener Datos
    query = "SELECT * FROM telemetria ORDER BY tiempo DESC LIMIT 100"
    df = pd.read_sql(query, conn)

    if not df.empty:
        # 4. Procesamiento con IA
        # Suponiendo que tu modelo predice sobre el dataframe
        predictions = detector.predict(df[['voltaje', 'corriente']])
        df['es_anomalia'] = predictions # 1 si es falla, 0 si es normal

        # 5. Métricas rápidas
        col1, col2 = st.columns(2)
        total_fallas = df['es_anomalia'].sum()
        col1.metric("Lecturas analizadas", len(df))
        col2.metric("Anomalías detectadas", total_fallas, delta_color="inverse")

        # 6. Visualización
        st.subheader("Historial de Voltaje y Corriente")
        st.line_chart(df[['voltaje', 'corriente']])

        # 7. Tabla destacando fallas
        st.subheader("Registros Recientes")
        def resaltar_anomalias(row):
            color = 'background-color: #ffcccc' if row['es_anomalia'] == 1 else ''
            return [color] * len(row)

        st.dataframe(df.style.apply(resaltar_anomalias, axis=1))

    else:
        st.warning("No hay datos en la base de datos todavía.")

except Exception as e:
    st.error(f"Error al conectar o procesar: {e}")