import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    def __init__(self) -> None:
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self._enabled = bool(self.token and self.chat_id)
        self._debounce: dict[tuple[int, str], dict] = {}
        self.DEBOUNCE_SECONDS = 30

    async def send_notification(
        self, mensaje: str, dispositivo_id: int = 0, tipo: str = ""
    ) -> None:
        if not self._enabled:
            logger.warning(
                "Telegram no configurado — TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID vacíos"
            )
            return

        key = (dispositivo_id, tipo or "ANOMALIA")
        now = time.time()
        entry = self._debounce.get(key)

        if entry is None:
            self._debounce[key] = {"first_seen": now, "notified": False}
            return

        if not entry["notified"] and (now - entry["first_seen"]) >= self.DEBOUNCE_SECONDS:
            entry["notified"] = True
            logger.info(
                "Enviando notificación Telegram para (%s, %s) tras %.0fs de persistencia",
                dispositivo_id, tipo, now - entry["first_seen"],
            )
        else:
            return

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": mensaje,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10)
                resp.raise_for_status()
            logger.info("Notificación enviada a Telegram")
        except Exception as e:
            logger.error("Error enviando notificación a Telegram: %s", e)

    def clear_debounce(self, dispositivo_id: int, tipo: str) -> None:
        key = (dispositivo_id, tipo or "ANOMALIA")
        if key in self._debounce:
            del self._debounce[key]
            logger.debug("Debounce limpiado para (%s, %s)", dispositivo_id, tipo)


telegram_service = TelegramService()
