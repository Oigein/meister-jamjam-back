"""이메일 발송. SMTP_HOST가 있으면 SMTP로 보내고, 없으면 로그만 남긴다.

수신자·제목·내용·첨부 이름은 로그에 남기지 않는다 (자진 신고 등 민감한 알림에 쓰인다).
"""
import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger("app.mail")


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class LogMailer:
    async def send(self, to: str, subject: str, body: str) -> None:
        logger.info("mail skipped: SMTP not configured (subject length=%d)", len(subject))


class SmtpMailer:
    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = settings.smtp_from or settings.smtp_user
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        if settings.smtp_port == 465:
            client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10)
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
        with client:
            if settings.smtp_port != 465 and settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)
        logger.info("mail sent")


_mailer: Mailer | None = None


def get_mailer() -> Mailer:
    if _mailer is not None:
        return _mailer
    return SmtpMailer() if settings.smtp_host else LogMailer()


def set_mailer(mailer: Mailer | None) -> None:
    global _mailer
    _mailer = mailer
