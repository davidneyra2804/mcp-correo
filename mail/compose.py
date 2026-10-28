"""Construye un mensaje saliente. El remitente es siempre la cuenta, nunca el modelo."""

from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import format_datetime, formataddr, make_msgid
from typing import Any

from config import ServerSettings
from mail.errors import MailError

_EMAIL = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_MSGID = re.compile(r"^<?[^<>\s]+@[^<>\s]+>?$")
_MAX_ATTACHMENTS = 10
_PREVIEW_CHARS = 400


def format_sender(name: str, address: str) -> str:
    """La cabecera From, con nombre visible si la cuenta tiene uno.

    `formataddr` se encarga del escapado de la RFC 5322: si el nombre lleva
    coma o comillas, lo entrecomilla y lo escapa.
    """
    if not name:
        return address
    return formataddr((name, address))


def build_outgoing(
    *,
    sender: str,
    to: list[str] | None,
    cc: list[str] | None,
    bcc: list[str] | None,
    subject: str,
    body: str,
    in_reply_to: str | None,
    references: str | None,
    attachments: list[dict[str, str]] | None,
    settings: ServerSettings,
    sender_name: str = "",
) -> tuple[bytes, dict[str, Any], str]:
    """Devuelve bytes, resumen sin cuerpo y una vista previa recortada del texto."""
    if not _EMAIL.fullmatch(sender):
        raise MailError("La cuenta no tiene un remitente con forma de correo.")
    recipients = {
        "to": _addresses(to, "to"),
        "cc": _addresses(cc, "cc"),
        "bcc": _addresses(bcc, "bcc"),
    }
    if not recipients["to"]:
        raise MailError("Indica al menos un destinatario en to.")
    total = sum(len(items) for items in recipients.values())
    if total > settings.max_recipients:
        raise MailError(f"Demasiados destinatarios: el máximo es {settings.max_recipients}.")
    _check_domains(recipients, settings.allowed_recipient_domains)
    subject_text = _header_text(subject, "subject", allow_empty=True)
    reply = _message_ids(in_reply_to, "in_reply_to", many=False)
    refs = _message_ids(references, "references", many=True)
    if not isinstance(body, str):
        raise MailError("body debe ser texto.")
    if any(char in body for char in "\x00"):
        raise MailError("body contiene caracteres no permitidos.")
    if len(body.encode()) > settings.max_message_bytes:
        raise MailError("El cuerpo supera el tamaño máximo del mensaje.")

    message = EmailMessage()
    message["From"] = format_sender(sender_name, sender)
    message["To"] = ", ".join(recipients["to"])
    if recipients["cc"]:
        message["Cc"] = ", ".join(recipients["cc"])
    if recipients["bcc"]:
        message["Bcc"] = ", ".join(recipients["bcc"])
    message["Subject"] = subject_text
    message["Date"] = format_datetime(datetime.now(UTC))
    domain = sender.split("@", 1)[1]
    message_id = make_msgid(domain=domain)
    message["Message-ID"] = message_id
    if reply:
        message["In-Reply-To"] = reply
    if refs:
        message["References"] = refs
    message.set_content(body)
    filenames = _attach(message, attachments, settings)
    raw = message.as_bytes()
    if len(raw) > settings.max_message_bytes:
        raise MailError(
            f"El mensaje ocupa {len(raw)} bytes y el límite es {settings.max_message_bytes}."
        )
    public = {
        "to": recipients["to"],
        "cc": recipients["cc"],
        "bcc": recipients["bcc"],
        "subject": subject_text,
        "filenames": filenames,
        "in_reply_to": reply or "",
        "references": refs or "",
        # El Message-ID identifica el mensaje ante el servidor y ante quien
        # lo busque después. Sin devolverlo, no hay forma de localizar la
        # copia en Enviados salvo adivinar carpeta y criterio de búsqueda.
        "message_id": message_id,
    }
    preview = body[:_PREVIEW_CHARS]
    return raw, public, preview


def without_bcc(raw: bytes) -> bytes:
    """El mismo mensaje sin la cabecera Bcc.

    Lo que sale por SMTP, los destinatarios ocultos ya no aparecen en el
    cuerpo. La copia que se guarda en Enviados tiene que quitarlos también:
    si no, quedan a la vista en el buzón de enviados.
    """
    parsed = message_from_bytes(raw, policy=default_policy)
    if not isinstance(parsed, EmailMessage) or "Bcc" not in parsed:
        return raw
    del parsed["Bcc"]
    return parsed.as_bytes()


def _addresses(value: list[str] | None, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MailError(f"{field_name} debe ser una lista de direcciones.")
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise MailError(f"{field_name} debe ser una lista de textos.")
        text = item.strip()
        if not text:
            continue
        if any(char in text for char in "\r\n\x00"):
            raise MailError(f"{field_name} contiene caracteres no permitidos.")
        mail = text
        if "<" in text or ">" in text:
            if text.count("<") != 1 or text.count(">") != 1 or not text.endswith(">"):
                raise MailError(f"Dirección no válida en {field_name}.")
            mail = text.split("<", 1)[1].split(">", 1)[0].strip()
        if not _EMAIL.fullmatch(mail):
            raise MailError(f"Dirección no válida en {field_name}.")
        cleaned.append(text if "<" in text else mail)
    return cleaned


def _check_domains(recipients: dict[str, list[str]], allowed: tuple[str, ...]) -> None:
    if not allowed:
        return
    permitted = {item.lower() for item in allowed}
    for items in recipients.values():
        for addr in items:
            mail = addr
            if "<" in addr:
                mail = addr.split("<", 1)[1].split(">", 1)[0]
            domain = mail.rsplit("@", 1)[-1].lower()
            if domain not in permitted:
                raise MailError(f"El dominio {domain} no está en la lista de permitidos.")


def _header_text(value: str, field_name: str, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise MailError(f"{field_name} debe ser texto.")
    if any(char in value for char in "\r\n\x00"):
        raise MailError(f"{field_name} contiene caracteres no permitidos.")
    if not allow_empty and not value.strip():
        raise MailError(f"{field_name} no puede estar vacío.")
    if len(value) > 500:
        raise MailError(f"{field_name} supera los 500 caracteres.")
    return value


def _message_ids(value: str | None, field_name: str, *, many: bool) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or any(char in value for char in "\r\n\x00"):
        raise MailError(f"{field_name} contiene caracteres no permitidos.")
    parts = value.split()
    if not parts or (not many and len(parts) != 1):
        raise MailError(f"{field_name} debe ser un Message-ID.")
    normalized: list[str] = []
    for part in parts:
        if not _MSGID.fullmatch(part):
            raise MailError(f"{field_name} no parece un Message-ID.")
        if not part.startswith("<"):
            part = f"<{part.strip('<>')}>"
        normalized.append(part)
    return " ".join(normalized)


def _attach(
    message: EmailMessage,
    attachments: list[dict[str, str]] | None,
    settings: ServerSettings,
) -> list[str]:
    if not attachments:
        return []
    if not isinstance(attachments, list) or len(attachments) > _MAX_ATTACHMENTS:
        raise MailError(f"Como máximo {_MAX_ATTACHMENTS} adjuntos por mensaje.")
    names: list[str] = []
    allowed = set(settings.allowed_attachment_types)
    for item in attachments:
        if not isinstance(item, dict):
            raise MailError("Cada adjunto necesita filename, content_type y content_base64.")
        filename = str(item.get("filename") or "").strip()
        if (
            not filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or any(char in filename for char in "\r\n\x00")
            or len(filename) > 200
        ):
            raise MailError("Nombre de adjunto inválido.")
        content_type = str(item.get("content_type") or "").strip().lower()
        if content_type not in allowed:
            raise MailError(f"Tipo de adjunto no permitido: {content_type or '(vacío)'}.")
        encoded = item.get("content_base64")
        if not isinstance(encoded, str):
            raise MailError(f"El adjunto {filename} no está en base64.")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise MailError(f"El adjunto {filename} no está en base64.") from None
        if len(payload) > settings.max_attachment_bytes:
            raise MailError(
                f"El adjunto {filename} supera el límite de {settings.max_attachment_bytes} bytes."
            )
        maintype, subtype = content_type.split("/", 1)
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
        names.append(filename)
    return names
