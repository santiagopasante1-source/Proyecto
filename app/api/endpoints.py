"""
app/api/endpoints.py
────────────────────
Rutas completas y corregidas para la ingestión de telemetría.
Incluye soporte asíncrono para alertas de Telegram y banderas de Streamlit.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.dispositivo import Dispositivo
from app.models.incidencia import Incidencia, SeveridadEnum
from app.models.telemetria import Telemetria
from app.schemas.telemetria import TelemetriaCreate, TelemetriaIAResult, TelemetriaResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Telemetría"])

def _score_to_severidad(score: float) -> SeveridadEnum:
    """Traduce el score de la IA a niveles de severidad de negocio."""
    if score >= 0.90: 
        return SeveridadEnum.critica
    elif score >= 0.75: 
        return SeveridadEnum.alta
    elif score >= 0.50: 
        return SeveridadEnum.media
    else: 
        return SeveridadEnum.baja

@router.post(
    "/telemetry",
    response_model=TelemetriaIAResult,
    status_code=status.HTTP_201_CREATED,
    summary="Ingesta un registro de telemetría y ejecuta análisis IA",
)
def ingest_telemetry(
    payload: TelemetriaCreate,
    db: Session = Depends(get_db),
    request: Request = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> TelemetriaIAResult:
    
    # 1. Acceder al motor de IA inyectado en el estado de FastAPI
    detector = request.app.state.detector
    if not detector:
        raise HTTPException(status_code=503, detail="Motor de IA no inicializado.")

    # 2. Verificar existencia del dispositivo
    dispositivo = db.query(Dispositivo).filter(Dispositivo.id == payload.dispositivo_id).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail=f"Dispositivo {payload.dispositivo_id} no encontrado.")

    # 3. Persistir telemetría inicial (por defecto entra como normal)
    telemetria = Telemetria(
        dispositivo_id=payload.dispositivo_id,
        voltaje=payload.voltaje,
        corriente=payload.corriente,
        potencia=round(payload.voltaje * payload.corriente, 2),
        frecuencia=payload.frecuencia or 60.0,
        procesado_ia=True
    )
    db.add(telemetria)
    db.commit()
    db.refresh(telemetria)

    # 4. Inferencia IA
    datos_analisis = {
        "voltaje": payload.voltaje, 
        "corriente": payload.corriente, 
        "frecuencia": payload.frecuencia or 60.0
    }
    ia_resultado = detector.procesar(datos_analisis)

    # 5. Registrar incidencia e hilos de notificación si es anomalía
    if ia_resultado.get("anomalia"):
        score = ia_resultado.get("score", 0.0)
        
        # 🌟 CORRECCIÓN: Actualizamos el flag de la telemetría para que Streamlit pinte el marcador rojo
        telemetria.anomalia_detectada = True
        db.add(telemetria)

        # Creamos el reporte de la falla en la base de datos
        incidencia = Incidencia(
            dispositivo_id=dispositivo.id,
            telemetria_id=telemetria.id,
            tipo=ia_resultado.get("tipo", "ANOMALIA_DETECTADA"),
            descripcion=ia_resultado.get("mensaje", "Patrón eléctrico irregular"),
            severidad=_score_to_severidad(score),
            score_anomalia=score,
        )
        db.add(incidencia)
        db.commit()  # Guarda tanto la actualización de la telemetría como la incidencia en Neon

        # 🚀 DISPARO DE TELEGRAM EN SEGUNDO PLANO
        try:
            from app.services.telegram import telegram_service
            
            dispositivo_nombre = dispositivo.nombre or f"ID {dispositivo.id}"
            ubicacion_disp = dispositivo.ubicacion or "No especificada"
            
            mensaje = (
                f"⚠️ *¡ANOMALÍA ELÉCTRICA DETECTADA!*\n\n"
                f"🔌 *Dispositivo:* {dispositivo_nombre}\n"
                f"📍 *Ubicación:* {ubicacion_disp}\n"
                f"🚨 *Tipo:* {incidencia.tipo}\n"
                f"📊 *Severidad:* {incidencia.severidad.value.upper()}\n"
                f"📈 *Score IA:* {score:.4f}\n\n"
                f"⚡ *Lectura:* {telemetria.voltaje}V | {telemetria.corriente}A | {telemetria.frecuencia}Hz"
            )
            # Agendamos la tarea para que FastAPI la envíe sin retrasar el flujo principal
            background_tasks.add_task(telegram_service.send_notification, mensaje)
            
        except Exception as telegram_err:
            logger.error(f"Error al programar la alerta de Telegram: {telegram_err}")

    # 6. Retorno final estructurado al cliente (Simulador / ESP32)
    return TelemetriaIAResult(
        telemetria=TelemetriaResponse.model_validate(telemetria),
        ia_resultado=ia_resultado,
    )