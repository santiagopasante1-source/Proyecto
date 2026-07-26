import logging
import smtplib
import time
from email.mime.text import MIMEText

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    def __init__(self) -> None:
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self._enabled = bool(self.token)
        self._debounce: dict[tuple[int, str], dict] = {}
        self.DEBOUNCE_SECONDS = 300

    def send_notification(
        self, mensaje: str, dispositivo_id: int = 0, tipo: str = "", chat_id: str | None = None
    ) -> None:
        target_chat = chat_id or self.chat_id

        if not self._enabled or not target_chat:
            logger.warning(
                "Telegram no configurado — TELEGRAM_BOT_TOKEN o chat_id vacíos"
            )
            return

        key = (dispositivo_id, tipo or "ANOMALIA")
        now = time.time()
        entry = self._debounce.get(key)

        if entry is None:
            self._debounce[key] = {"first_seen": now, "notified": True}
            logger.info(
                "Enviando notificación Telegram para (%s, %s)",
                dispositivo_id, tipo,
            )
        elif entry["notified"] and (now - entry["first_seen"]) >= self.DEBOUNCE_SECONDS:
            entry["first_seen"] = now
            logger.info(
                "Reenviando notificación Telegram para (%s, %s) tras %ds de cooldown",
                dispositivo_id, tipo, self.DEBOUNCE_SECONDS,
            )
        else:
            return

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": mensaje,
            "disable_web_page_preview": True,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Notificación enviada a Telegram")
        except Exception as e:
            logger.error("Error enviando notificación a Telegram: %s", e)

    def send_diagnostic(self, chat_id: str) -> dict:
        """Envía mensaje de prueba SIN debounce y devuelve la respuesta de Telegram."""
        if not self._enabled:
            return {"ok": False, "error": "Telegram no habilitado — TELEGRAM_BOT_TOKEN vacío"}
        if not chat_id:
            return {"ok": False, "error": "chat_id vacío"}

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": "🔧 Mensaje de diagnóstico — si ves esto, Telegram funciona correctamente.",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            return {
                "ok": resp.ok,
                "status": resp.status_code,
                "body": resp.text,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def clear_debounce(self, dispositivo_id: int, tipo: str) -> None:
        key = (dispositivo_id, tipo or "ANOMALIA")
        if key in self._debounce:
            del self._debounce[key]
            logger.debug("Debounce limpiado para (%s, %s)", dispositivo_id, tipo)

    # ── Email via Gmail SMTP ─────────────────────────────────────────────

    @property
    def _email_enabled(self) -> bool:
        return bool(settings.GMAIL_USER and settings.GMAIL_APP_PASSWORD)

    def send_email(self, to_email: str, subject: str, body: str) -> bool:
        if not self._email_enabled:
            logger.warning("Gmail no configurado — GMAIL_USER o GMAIL_APP_PASSWORD vacíos")
            return False

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.GMAIL_USER
        msg["To"] = to_email

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
                server.login(settings.GMAIL_USER, settings.GMAIL_APP_PASSWORD)
                server.sendmail(settings.GMAIL_USER, to_email, msg.as_string())
            logger.info("Email enviado a %s", to_email)
            return True
        except Exception as e:
            logger.error("Error enviando email a %s: %s", to_email, e)
            return False

    def notify_contacts(self, mensaje: str, dispositivo_id: int, tipo: str, contacts: list) -> None:
        """Envía notificación a una lista de contactos (Telegram y/o Email)."""
        for c in contacts:
            if c.telegram_id:
                self.send_notification(mensaje, dispositivo_id, tipo, c.telegram_id)
            if c.email and self._email_enabled:
                subject = f"[IoT Alerta] {tipo}"
                self.send_email(c.email, subject, mensaje)


telegram_service = TelegramService()
