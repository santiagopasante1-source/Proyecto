import logging
import threading
import time
from datetime import datetime, timezone, timedelta

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dispositivo import Dispositivo
from app.models.incidencia import Incidencia, SeveridadEnum, EstadoEnum
from app.models.telemetria import Telemetria
from app.models.usuario import Usuario
from app.models.contacto_notificacion import ContactoNotificacion

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = settings.OFFLINE_TIMEOUT_SECONDS
CHECK_INTERVAL = 10


class DeviceMonitor:
    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("DeviceMonitor iniciado — revisando desconexiones cada %ds", CHECK_INTERVAL)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("DeviceMonitor detenido.")

    def _run(self):
        while self._running:
            try:
                self._check_devices()
            except Exception as e:
                logger.error("DeviceMonitor error: %s", e)
            time.sleep(CHECK_INTERVAL)

    def _check_devices(self):
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            threshold = now - timedelta(seconds=TIMEOUT_SECONDS)

            devices = db.query(Dispositivo).filter(
                Dispositivo.is_active == True,
                Dispositivo.ultimo_ping.isnot(None),
                Dispositivo.ultimo_ping < threshold,
            ).all()

            for device in devices:
                # Buscar APAGON o DESCONEXION abiertos
                apagon_abierto = db.query(Incidencia).filter(
                    Incidencia.dispositivo_id == device.id,
                    Incidencia.tipo == "APAGON",
                    Incidencia.estado == EstadoEnum.abierta,
                ).first()

                desc_abierta = db.query(Incidencia).filter(
                    Incidencia.dispositivo_id == device.id,
                    Incidencia.tipo == "DESCONEXION",
                    Incidencia.estado == EstadoEnum.abierta,
                ).first()

                if desc_abierta:
                    if apagon_abierto and desc_abierta.id != apagon_abierto.id:
                        # DESCONEXION duplicada — cerrarla
                        desc_abierta.estado = EstadoEnum.resuelta
                        desc_abierta.resolved_at = now
                        desc_abierta.notas = f"Migrada a APAGON #{apagon_abierto.id}"
                    else:
                        # Migrar DESCONEXION → APAGON
                        desc_abierta.tipo = "APAGON"
                    db.add(desc_abierta)

                if not apagon_abierto and not desc_abierta:
                    # Insertar telemetría con V=0/I=0 para que el dashboard muestre la caída
                    telemetria_apagon = Telemetria(
                        dispositivo_id=device.id,
                        voltaje=0.0,
                        corriente=0.0,
                        potencia=0.0,
                        frecuencia=0.0,
                        anomalia_detectada=True,
                        procesado_ia=True,
                    )
                    db.add(telemetria_apagon)
                    db.flush()

                    incidencia = Incidencia(
                        dispositivo_id=device.id,
                        telemetria_id=telemetria_apagon.id,
                        tipo="APAGON",
                        descripcion=(
                            f"Falla del servicio — El dispositivo '{device.nombre or device.id}' "
                            f"dejó de enviar datos. Último ping: {device.ultimo_ping.isoformat()}."
                        ),
                        severidad=SeveridadEnum.critica,
                        estado=EstadoEnum.abierta,
                    )
                    db.add(incidencia)

                    from app.services.telegram import telegram_service

                    chat_id = None
                    if device.usuario_id:
                        dueño = db.query(Usuario).filter(Usuario.id == device.usuario_id).first()
                        chat_id = dueño.telegram_id if dueño and dueño.telegram_id else None

                    ping_fmt = device.ultimo_ping.strftime("%d/%m/%Y %H:%M:%S")
                    msg_apagon = (
                        f"🚨 FALLA DEL SERVICIO\n\n"
                        f"Dispositivo: {device.nombre or device.id}\n"
                        f"Ubicacion: {device.ubicacion or 'No especificada'}\n"
                        f"Severidad: CRITICA\n"
                        f"Motivo: Desconexion\n"
                        f"Ultimo ping: {ping_fmt}"
                    )
                    telegram_service.send_notification(
                        msg_apagon, device.id, "APAGON", chat_id,
                    )

                    contactos = (
                        db.query(ContactoNotificacion)
                        .filter(ContactoNotificacion.dispositivo_id == device.id, ContactoNotificacion.is_active == True)
                        .all()
                    )
                    if contactos:
                        telegram_service.notify_contacts(msg_apagon, device.id, "APAGON", contactos)
                    db.commit()
                    logger.warning("APAGON creado para dispositivo %s (V=0/I=0 insertado)", device.id)
                else:
                    db.commit()
        finally:
            db.close()
