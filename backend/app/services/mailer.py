"""Outgoing email.

EMAIL_MODE=log (the default until the corporate mailbox is connected) writes the
message to the server log instead of sending it, so codes can be read from the
uvicorn console. EMAIL_MODE=smtp sends through SMTP; for Yandex 360 use
smtp.yandex.ru:465 (SSL), a mailbox of the corporate domain and an app password.
"""
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
import logging
import smtplib
import ssl

from ..config import settings

logger = logging.getLogger("room_booking.mail")
SENDER_NAME = "Бронирование аудиторий"


class EmailDeliveryError(RuntimeError):
    pass


def build_message(to: str, subject: str, text: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((SENDER_NAME, settings.smtp_from))
    message["To"] = to
    message["Subject"] = subject
    domain = settings.smtp_from.rsplit("@", 1)[-1] if "@" in settings.smtp_from else None
    message["Message-ID"] = make_msgid(domain=domain)
    message.set_content(text)
    return message


def send_email(to: str, subject: str, text: str) -> None:
    if settings.email_mode != "smtp":
        logger.warning("EMAIL_MODE=log, письмо не отправлено.\nКому: %s\nТема: %s\n%s", to, subject, text)
        return
    message = build_message(to, subject, text)
    try:
        if settings.smtp_security == "ssl":
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds,
                                      context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)
        with server:
            if settings.smtp_security == "starttls":
                server.starttls(context=ssl.create_default_context())
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.exception("Не удалось отправить письмо на %s", to)
        raise EmailDeliveryError(str(exc)) from exc
