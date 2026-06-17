"""
app/api/endpoints.py
────────────────────
Rutas completas y corregidas para la ingestión de telemetría.
Incluye soporte asíncrono para alertas de Telegram y banderas de Streamlit.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.dispositivo import Dispositivo
from app.models.incidencia import Incidencia, SeveridadEnum, EstadoEnum
from app.models.telemetria import Telemetria
from app.models.usuario import Usuario
from app.schemas.telemetria import TelemetriaCreate, TelemetriaIAResult, TelemetriaResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Telemetría"])

TIPOS_TELEGRAM = {"APAGON", "SOBREVOLTAJE", "BAJO_VOLTAJE", "FRECUENCIA_ANOMALA"}

# Debounce buffer for APAGÓN detection (device_id → list of last N voltage readings)
_voltage_debounce: dict[int, list[float]] = {}
DEBOUNCE_COUNT = 20      # consecutive V<70 readings (~60s) to confirm APAGÓN
DIAG_BUFFER_SIZE = 5     # keep this many readings for diagnostic logging

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

def _clasificar_tipo_anomalia(voltaje: float, frecuencia: float) -> str | None:
    """Clasifica el tipo de anomalía según reglas de ingeniería.
    
    Orden de precedencia:
    1. APAGON (V < 70)
    2. SOBREVOLTAJE (V > 134)
    3. BAJO_VOLTAJE (V < 110)
    4. FRECUENCIA_ANOMALA (F < 59 o F > 61)
    """
    if voltaje < 70:
        return "APAGON"
    if voltaje > 134:
        return "SOBREVOLTAJE"
    if voltaje < 114:
        return "BAJO_VOLTAJE"
    if frecuencia < 59 or frecuencia > 61:
        return "FRECUENCIA_ANOMALA"
    return None

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

    # 3. Detectar reconexión: cerrar DESCONEXION abierta y crear RECONEXION
    ahora = datetime.now(timezone.utc)
    reconexion_detectada = False

    desconexion_abierta = db.query(Incidencia).filter(
        Incidencia.dispositivo_id == dispositivo.id,
        Incidencia.tipo == "DESCONEXION",
        Incidencia.estado == EstadoEnum.abierta,
    ).first()

    if desconexion_abierta:
        desconexion_abierta.estado = EstadoEnum.resuelta
        desconexion_abierta.resolved_at = ahora
        desconexion_abierta.notas = (
            f"Reconexión automática detectada — "
            f"V={payload.voltaje}V I={payload.corriente}A F={payload.frecuencia or 60.0}Hz"
        )
        db.add(desconexion_abierta)

        incidencia_recon = Incidencia(
            dispositivo_id=dispositivo.id,
            tipo="RECONEXION",
            descripcion=(
                f"El dispositivo '{dispositivo.nombre or dispositivo.id}' se reconectó "
                f"tras una desconexión. Voltaje: {payload.voltaje}V, Corriente: {payload.corriente}A"
            ),
            severidad=SeveridadEnum.media,
            estado=EstadoEnum.resuelta,
            resolved_at=ahora,
        )
        db.add(incidencia_recon)
        reconexion_detectada = True

    # Actualizar último ping del dispositivo
    dispositivo.ultimo_ping = ahora
    db.add(dispositivo)
    db.commit()

    if reconexion_detectada:
        logger.info("RECONEXION registrada para dispositivo %s", dispositivo.id)

    # 4. Persistir telemetría inicial (por defecto entra como normal)
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

    # 5. Clasificar anomalía por reglas de ingeniería
    tipo_anomalia = _clasificar_tipo_anomalia(payload.voltaje, payload.frecuencia)

    # 5b. APAGÓN debounce: requiere lecturas consecutivas para evitar falsos por ruido ADC/WiFi
    _voltage_buf = _voltage_debounce.setdefault(dispositivo.id, [])
    _voltage_buf.append(payload.voltaje)
    if len(_voltage_buf) > DIAG_BUFFER_SIZE:
        _voltage_buf.pop(0)

    if tipo_anomalia == "APAGON":
        if len(_voltage_buf) >= DEBOUNCE_COUNT and all(v < 70 for v in _voltage_buf[-DEBOUNCE_COUNT:]):
            apagon_ultimos = ", ".join(f"{v:.1f}V" for v in _voltage_buf[-DIAG_BUFFER_SIZE:])
        else:
            tipo_anomalia = None  # debounce no confirmado

    if tipo_anomalia == "APAGON":
        telemetria.anomalia_detectada = True
        db.add(telemetria)

        apagon_abierto = db.query(Incidencia).filter(
            Incidencia.dispositivo_id == dispositivo.id,
            Incidencia.tipo == "APAGON",
            Incidencia.estado == EstadoEnum.abierta,
        ).first()

        if not apagon_abierto:
            incidencia_apagon = Incidencia(
                dispositivo_id=dispositivo.id,
                telemetria_id=telemetria.id,
                tipo="APAGON",
                descripcion=(
                    f"Corte de energía — V={payload.voltaje}V "
                    f"(historial: {apagon_ultimos}), I={payload.corriente}A, "
                    f"F={payload.frecuencia or 60.0}Hz"
                ),
                severidad=SeveridadEnum.critica,
                estado=EstadoEnum.abierta,
                score_anomalia=1.0,
            )
            db.add(incidencia_apagon)

            from app.services.telegram import telegram_service
            dispositivo_nombre = dispositivo.nombre or f"ID {dispositivo.id}"

            chat_id_apagon = None
            if dispositivo.usuario_id:
                dueño = db.query(Usuario).filter(Usuario.id == dispositivo.usuario_id).first()
                chat_id_apagon = dueño.telegram_id if dueño and dueño.telegram_id else None

            background_tasks.add_task(
                telegram_service.send_notification,
                (
                    f"🚨 *APAGON (CONFIRMADO)*\n\n"
                    f"🔌 *Dispositivo:* {dispositivo_nombre}\n"
                    f"📍 *Ubicacion:* {dispositivo.ubicacion or 'No especificada'}\n"
                    f"📊 *Severidad:* CRITICA\n"
                    f"⚡ *Lectura:* {payload.voltaje}V | {payload.corriente}A | {payload.frecuencia}Hz"
                ),
                dispositivo.id,
                "APAGON",
                chat_id_apagon,
            )
            logger.warning("APAGON confirmado para dispositivo %s (V=%s)", dispositivo.id, payload.voltaje)
    elif tipo_anomalia:
        telemetria.anomalia_detectada = True
        db.add(telemetria)

        severidad = SeveridadEnum.critica if tipo_anomalia in ("SOBREVOLTAJE", "BAJO_VOLTAJE") else SeveridadEnum.alta
        incidencia = Incidencia(
            dispositivo_id=dispositivo.id,
            telemetria_id=telemetria.id,
            tipo=tipo_anomalia,
            descripcion=(
                f"{tipo_anomalia} detectado — V={payload.voltaje}V, I={payload.corriente}A, "
                f"F={payload.frecuencia or 60.0}Hz"
            ),
            severidad=severidad,
            estado=EstadoEnum.abierta,
            score_anomalia=1.0,
        )
        db.add(incidencia)

        if tipo_anomalia in TIPOS_TELEGRAM:
            from app.services.telegram import telegram_service
            dispositivo_nombre = dispositivo.nombre or f"ID {dispositivo.id}"
            chat_id = None
            if dispositivo.usuario_id:
                dueño = db.query(Usuario).filter(Usuario.id == dispositivo.usuario_id).first()
                chat_id = dueño.telegram_id if dueño and dueño.telegram_id else None
            background_tasks.add_task(
                telegram_service.send_notification,
                (
                    f"🚨 *{tipo_anomalia} DETECTADO*\n\n"
                    f"🔌 *Dispositivo:* {dispositivo_nombre}\n"
                    f"📍 *Ubicacion:* {dispositivo.ubicacion or 'No especificada'}\n"
                    f"📊 *Severidad:* {severidad.value.upper()}\n"
                    f"⚡ *Lectura:* {telemetria.voltaje}V | {telemetria.corriente}A | {telemetria.frecuencia}Hz"
                ),
                dispositivo.id,
                tipo_anomalia,
                chat_id,
            )

        logger.warning("%s registrado para dispositivo %s", tipo_anomalia, dispositivo.id)
    else:
        # Sin anomalía por reglas — verificar si había APAGON abierto y cerrarlo
        apagon_abierto = db.query(Incidencia).filter(
            Incidencia.dispositivo_id == dispositivo.id,
            Incidencia.tipo == "APAGON",
            Incidencia.estado == EstadoEnum.abierta,
        ).first()

        if apagon_abierto:
            apagon_abierto.estado = EstadoEnum.resuelta
            apagon_abierto.resolved_at = ahora
            apagon_abierto.notas = (
                f"Reestablecimiento detectado — "
                f"V={payload.voltaje}V I={payload.corriente}A F={payload.frecuencia or 60.0}Hz"
            )
            db.add(apagon_abierto)

            incidencia_reest = Incidencia(
                dispositivo_id=dispositivo.id,
                tipo="RESTABLECIMIENTO",
                descripcion=(
                    f"La energia se restablecio en '{dispositivo.nombre or dispositivo.id}'. "
                    f"Voltaje: {payload.voltaje}V, Corriente: {payload.corriente}A"
                ),
                severidad=SeveridadEnum.media,
                estado=EstadoEnum.resuelta,
                resolved_at=ahora,
            )
            db.add(incidencia_reest)

            from app.services.telegram import telegram_service
            telegram_service.clear_debounce(dispositivo.id, "APAGON")

            chat_id_rest = None
            if dispositivo.usuario_id:
                dueño = db.query(Usuario).filter(Usuario.id == dispositivo.usuario_id).first()
                chat_id_rest = dueño.telegram_id if dueño and dueño.telegram_id else None
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    telegram_service.send_notification(
                        (
                            f"⚡ *Servicio Restablecido*\n\n"
                            f"🔌 *Dispositivo:* {dispositivo.nombre or dispositivo.id}\n"
                            f"📍 *Ubicacion:* {dispositivo.ubicacion or 'No especificada'}\n"
                            f"⚡ *Voltaje:* {payload.voltaje}V | {payload.corriente}A | {payload.frecuencia}Hz"
                        ),
                        dispositivo.id, "RESTABLECIMIENTO", chat_id_rest,
                    )
                )
                loop.close()
            except Exception:
                pass

            logger.info("RESTABLECIMIENTO registrado para dispositivo %s", dispositivo.id)

    db.commit()

    # 6. Inferencia IA (LSTM) solo si no hay anomalía por reglas de ingeniería
    if not tipo_anomalia:
        datos_analisis = {
            "voltaje": payload.voltaje, 
            "corriente": payload.corriente, 
            "frecuencia": payload.frecuencia or 60.0
        }
        ia_resultado = detector.procesar(datos_analisis)
    else:
        ia_resultado = {
            "anomalia": True,
            "score": 1.0,
            "tipo": tipo_anomalia,
            "confianza": 1.0,
            "mensaje": f"{tipo_anomalia} detectado por reglas de ingeniería",
        }

    # 7. Retorno final estructurado al cliente (Simulador / ESP32)
    return TelemetriaIAResult(
        telemetria=TelemetriaResponse.model_validate(telemetria),
        ia_resultado=ia_resultado,
    )