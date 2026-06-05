import logging
import threading
import time
from datetime import datetime, timezone, timedelta

from app.core.database import SessionLocal
from app.models.dispositivo import Dispositivo
from app.models.incidencia import Incidencia, SeveridadEnum, EstadoEnum

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
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
                existing = db.query(Incidencia).filter(
                    Incidencia.dispositivo_id == device.id,
                    Incidencia.tipo == "DESCONEXION",
                    Incidencia.estado == EstadoEnum.abierta,
                ).first()

                if not existing:
                    incidencia = Incidencia(
                        dispositivo_id=device.id,
                        tipo="DESCONEXION",
                        descripcion=(
                            f"El dispositivo '{device.nombre or device.id}' dejó de enviar datos. "
                            f"Último ping: {device.ultimo_ping.isoformat()}. "
                            "Posible corte de energía o falla de conectividad."
                        ),
                        severidad=SeveridadEnum.critica,
                        estado=EstadoEnum.abierta,
                    )
                    db.add(incidencia)
                    db.commit()
                    logger.warning("DESCONEXION creada para dispositivo %s", device.id)
        finally:
            db.close()
