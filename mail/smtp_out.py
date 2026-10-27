"""Envío SMTP. SMTPS (465) o STARTTLS, según la configuración. No registra credenciales."""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy
from typing import Any

from config import Account, ServerSettings
from mail.errors import MailError

logger = logging.getLogger("mcp_correo.smtp")

SmtpFactory = Callable[[Account, ServerSettings], Any]


def open_smtp(account: Account, settings: ServerSettings) -> Any:
    """Abre la conexión. El login lo hace `transmit`, para no dejar la clave en este módulo."""
    security = (account.smtp_security or settings.smtp_security).lower()
    timeout = settings.smtp_timeout
    if security == "ssl":
        return smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=timeout)
    if security == "starttls":
        client = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=timeout)
        client.ehlo()
        client.starttls()
        client.ehlo()
        return client
    raise MailError("smtp_security debe ser ssl o starttls.")


def transmit(
    account: Account,
    settings: ServerSettings,
    raw: bytes,
    factory: SmtpFactory,
) -> None:
    parsed = message_from_bytes(raw, policy=default_policy)
    if not isinstance(parsed, EmailMessage):
        raise MailError("No se pudo reconstruir el mensaje a enviar.")
    try:
        client = factory(account, settings)
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        _fail(account, exc)
    try:
        try:
            client.login(account.username, account.password)
            client.send_message(parsed)
        except (smtplib.SMTPException, OSError, TimeoutError) as exc:
            _fail(account, exc)
    finally:
        try:
            client.quit()
        except (smtplib.SMTPException, OSError):
            logger.info("Cierre SMTP incompleto en %s", account.key)


def _fail(account: Account, exc: BaseException) -> None:
    safe = str(exc).replace(account.password, "***")[:400] if account.password else str(exc)[:400]
    logger.warning("SMTP %s (%s): %s", account.key, type(exc).__name__, safe)
    raise MailError(f"El servidor SMTP rechazó el envío en la cuenta {account.key}.") from None


def probar_smtp(
    account: Account, settings: ServerSettings, factory: SmtpFactory | None = None
) -> dict:
    """Comprueba que las credenciales del SMTP sirven. No envía nada.

    Es lo que usa el botón de "probar" del panel: conectar, entrar y
    cerrar. Si algo está mal en el host, el puerto, el modo o la
    contraseña, se ve aquí y no cuando el agente intenta enviar.
    """
    abrir = factory or open_smtp
    try:
        client = abrir(account, settings)
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        _fail(account, exc)
    try:
        try:
            client.login(account.username, account.password)
        except (smtplib.SMTPException, OSError, TimeoutError) as exc:
            _fail(account, exc)
    finally:
        try:
            client.quit()
        except (smtplib.SMTPException, OSError):
            logger.info("Cierre SMTP incompleto en %s", account.key)
    return {
        "ok": True,
        "detail": f"Conectado a {account.smtp_host}:{account.smtp_port} y el login ha funcionado.",
    }
