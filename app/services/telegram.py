import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    def __init__(self) -> None:
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self._enabled = bool(self.token and self.chat_id)

    async def send_notification(self, mensaje: str) -> None:
        if not self._enabled:
            logger.warning(
                "Telegram no configurado — TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID vacíos"
            )
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


telegram_service = TelegramService()
