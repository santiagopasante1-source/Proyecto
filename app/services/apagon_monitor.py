"""
Monitor de apagones en segundo plano.
Detecta dispositivos que dejaron de enviar telemetría y crea incidencias automáticamente.
"""
import logging
import threading
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 10       # segundos entre cada verificación
UMBRAL_SIN_DATOS = 12     # segundos sin telemetría para considerar apagón


class ApagonMonitor:
    def __init__(self, interval=CHECK_INTERVAL, threshold=UMBRAL_SIN_DATOS):
        self.interval = interval
        self.threshold = timedelta(seconds=threshold)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._stopped = False

    def start(self):
        logger.info("🔌 ApagonMonitor iniciado (intervalo=%ds, umbral=%ds)",
                     self.interval, self.threshold.total_seconds())
        self._thread.start()

    def stop(self):
        self._stopped = True

    def _run(self):
        time.sleep(10)  # esperar a que la app termine de iniciar
        while not self._stopped:
            try:
                self._check()
            except Exception as e:
                logger.error(f"ApagonMonitor error: {e}")
            time.sleep(self.interval)

    def _check(self):
        from app.core.database import SessionLocal
        from app.models.dispositivo import Dispositivo
        from app.models.incidencia import Incidencia, EstadoEnum, SeveridadEnum

        db = SessionLocal()
        try:
            ahora = datetime.now(timezone.utc)
            dispositivos = db.query(Dispositivo).filter(
                Dispositivo.is_active == True
            ).all()

            for d in dispositivos:
                ultimo = d.ultimo_ping
                if ultimo is None or (ahora - ultimo) > self.threshold:
                    # Sin datos recientes — verificar si ya hay APAGON abierto
                    apagon = db.query(Incidencia).filter(
                        Incidencia.dispositivo_id == d.id,
                        Incidencia.tipo == "APAGON",
                        Incidencia.estado == EstadoEnum.abierta,
                    ).first()
                    if not apagon:
                        inc = Incidencia(
                            dispositivo_id=d.id,
                            tipo="APAGON",
                            descripcion=(
                                "Apagón detectado automáticamente por ausencia "
                                f"de telemetría (último ping: {ultimo})"
                            ),
                            severidad=SeveridadEnum.alta,
                            estado=EstadoEnum.abierta,
                        )
                        db.add(inc)
                        db.commit()
                        logger.warning(
                            "🔌 Apagón automático para dispositivo %d "
                            "(sin datos desde %s)", d.id, ultimo
                        )
        finally:
            db.close()
