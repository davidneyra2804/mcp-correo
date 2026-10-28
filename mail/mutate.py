"""Escritura IMAP y envío SMTP. Cada operación abre solo lo que necesita.

La lectura sigue en `mail.imap` con EXAMINE. Aquí el SELECT de lectura-escritura
ocurre solo en marcar, mover y borrar. APPEND (Enviados y Borradores) no selecciona.
"""

from __future__ import annotations

import imaplib
import logging
import re
from dataclasses import replace
from typing import Any

from imapclient.exceptions import CapabilityError, IMAPClientError

from config import WRITE_GATES, Account, account_allows
from mail.compose import build_outgoing, format_sender, without_bcc
from mail.confirm import ConfirmationStore, SendQuota
from mail.errors import MailError
from mail.imap import MailService, examine_folder, folder_name
from mail.mime import decode_header_value, format_addresses
from mail.smtp_out import SmtpFactory, open_smtp, transmit

logger = logging.getLogger("mcp_correo.mutate")

_TRASH_NAMES = ("Trash", "Papelera", "Deleted Items", "Deleted", "INBOX.Trash", "INBOX/Trash")

NOTICE_SEND = (
    "Preparado, NO enviado. Este mensaje todavía no ha salido. "
    "Siguiente paso: muestra esta vista previa a quien opera el asistente y "
    "espera su orden explícita de envío. Con esa orden, llama a send_message "
    "con el confirmation_id devuelto aquí y la misma cuenta. No digas que el "
    "correo se envió hasta que send_message lo confirme."
)
NOTICE_DELETE = (
    "Preparado, NO borrado. Ningún mensaje se ha borrado todavía. "
    "Siguiente paso: muestra esta vista previa a quien opera el asistente y "
    "espera su orden explícita de borrado. Con esa orden, llama a "
    "delete_message con el confirmation_id devuelto aquí y la misma cuenta. "
    "El modo (Papelera o definitivo) queda fijado en este confirmation_id. "
    "No digas que se borró hasta que delete_message lo confirme."
)


def _uid_de_append(response: Any) -> int | None:
    """El UID que le dio el servidor al mensaje guardado, si lo dio.

    Muchos servidores contestan al APPEND con un APPENDUID, que es el UID
    exacto del mensaje guardado. Con ese UID, el mensaje se puede leer
    directamente, sin buscar por asunto ni adivinar la carpeta. Los que no
    lo contestan devuelven None: no es un fallo, solo hay menos información.
    """
    if response is None:
        return None
    if isinstance(response, int) and not isinstance(response, bool):
        return response
    texto = " ".join(
        item.decode(errors="replace") if isinstance(item, bytes) else str(item)
        for item in (response if isinstance(response, list | tuple) else [response])
    )
    if "APPENDUID" not in texto.upper():
        return None
    numeros = re.findall(r"\d+", texto)
    if not numeros:
        return None
    return int(numeros[-1])


class MailboxWriter:
    def __init__(
        self,
        service: MailService,
        confirm: ConfirmationStore,
        quota: SendQuota,
        smtp_factory: SmtpFactory | None = None,
    ) -> None:
        self.service = service
        self.confirm = confirm
        self.quota = quota
        self.smtp_factory = smtp_factory or open_smtp

    def plan_send(
        self,
        account_key: str,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        account = self._gated(account_key, "send")
        if self.quota.remaining(account.key) < 1:
            raise MailError(f"Tope diario de envíos alcanzado ({self.quota.daily_cap}).")
        raw, public, preview_body = build_outgoing(
            sender=account.username,
            sender_name=account.sender,
            to=to,
            cc=cc,
            bcc=bcc,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
            references=references,
            attachments=attachments,
            settings=self.service.settings,
        )
        public["sent_folder"] = account.sent_folder
        preview = {
            "account": account.key,
            "from": format_sender(account.sender, account.username),
            "to": public["to"],
            "cc": public["cc"],
            "bcc": public["bcc"],
            "subject": public["subject"],
            "body_preview": preview_body,
            "attachments": public["filenames"],
            "in_reply_to": public["in_reply_to"],
            "references": public["references"],
            "expires_in_seconds": self.confirm.ttl_seconds,
            "sends_remaining_today": self.quota.remaining(account.key),
            # Estado explícito: preparar no envía. El agente no debe
            # deducirlo del nombre de la herramienta ni de la prosa.
            "status": "prepared",
            "sent": False,
            "next_tool": "send_message",
            "notice": NOTICE_SEND,
        }
        return preview, public, {"raw": raw}

    def plan_delete(
        self,
        account_key: str,
        uids: list[int],
        folder: str = "INBOX",
        permanent: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        account = self._gated(account_key, "delete")
        if not isinstance(permanent, bool):
            raise MailError("permanent debe ser true o false.")
        carpeta = folder_name(folder)
        chosen = _uid_list(uids, self.service.settings.max_delete_per_call)
        with self.service.session(account.key) as client:
            trash = None if permanent else self._resolve_trash(client, account)
            if not permanent and not trash:
                raise MailError(
                    "No hay carpeta Papelera. Sin ella solo se puede borrar "
                    "si prepare_delete recibe permanent=true."
                )
            examine_folder(client, carpeta)
            messages = self._summaries(client, carpeta, chosen)
        public = {
            "folder": carpeta,
            "uids": chosen,
            "permanent": permanent,
            "trash_folder": trash or "",
            "subjects": [item["subject"] for item in messages],
            "messages": messages,
        }
        preview = {
            "account": account.key,
            **public,
            "expires_in_seconds": self.confirm.ttl_seconds,
            # Estado explícito: preparar no borra. El modo ya viene fijado.
            "status": "prepared",
            "deleted": False,
            "next_tool": "delete_message",
            "notice": NOTICE_DELETE,
        }
        return preview, public

    def issue(
        self,
        kind: str,
        account_key: str,
        public: dict[str, Any],
        secret: dict[str, Any] | None = None,
    ) -> str:
        account = self._gated(account_key, kind)
        return self.confirm.issue(kind, account.key, public, secret or {})

    def describe(self, kind: str, account_key: str, token: str) -> dict[str, Any]:
        account = self._gated(account_key, kind)
        pending = self.confirm.peek(token, kind, account.key)
        return dict(pending.public)

    def commit_send(self, account_key: str, token: str) -> dict[str, Any]:
        account = self._gated(account_key, "send")
        pending = self.confirm.consume(token, "send", account.key)
        self.quota.reserve(account.key)
        try:
            transmit(
                account,
                self.service.settings,
                pending.secret["raw"],
                self.smtp_factory,
            )
        except MailError:
            self.quota.release(account.key)
            raise
        folder = str(pending.public.get("sent_folder") or account.sent_folder)
        copied, sent_uid = self._copy_to_sent(account, folder, pending.secret["raw"])
        return {
            "account": account.key,
            "status": "sent",
            "sent": True,
            "copy_in_sent": copied,
            "sent_folder": folder if copied else None,
            # El UID y el Message-ID localizan la copia sin adivinar la
            # carpeta ni el criterio de búsqueda. Con ellos, el mensaje se
            # puede leer directo con get_message.
            "sent_uid": sent_uid,
            "message_id": pending.public.get("message_id", ""),
            "to": pending.public["to"],
            "cc": pending.public["cc"],
            "bcc": pending.public["bcc"],
            "subject": pending.public["subject"],
            "notice": "Enviado tras confirmación. El servidor SMTP aceptó el mensaje.",
        }

    def commit_delete(self, account_key: str, token: str) -> dict[str, Any]:
        account = self._gated(account_key, "delete")
        pending = self.confirm.consume(token, "delete", account.key)
        public = pending.public
        folder = str(public["folder"])
        uids = [int(uid) for uid in public["uids"]]
        permanent = bool(public["permanent"])
        trash = str(public.get("trash_folder") or "")
        with self.service.session(account.key, writable=True) as client:
            try:
                if permanent:
                    self._expunge(client, folder, uids)
                else:
                    if not trash:
                        raise MailError("El token de borrado no tiene carpeta Papelera.")
                    self._move_to_trash(client, folder, uids, trash)
            except MailError:
                raise
            except (IMAPClientError, imaplib.IMAP4.error, TimeoutError, OSError) as exc:
                self.service._raise_imap(account, exc)
        return {
            "account": account.key,
            "status": "deleted",
            "folder": folder,
            "uids": uids,
            "permanent": permanent,
            "trash_folder": trash or None,
            "deleted": True,
            "notice": "Borrado tras confirmación.",
        }

    def mark(self, account_key: str, uids: list[int], folder: str = "INBOX", *, seen: bool) -> dict:
        account = self._gated(account_key, "mark")
        carpeta = folder_name(folder)
        chosen = _uid_list(uids, self.service.settings.max_mark_per_call)
        with self.service.session(account.key, writable=True) as client:
            try:
                client.select_folder(carpeta, readonly=False)
                self._ensure_present(client, carpeta, chosen)
                if seen:
                    client.add_flags(chosen, ["\\Seen"])
                else:
                    client.remove_flags(chosen, ["\\Seen"])
            except MailError:
                raise
            except (IMAPClientError, imaplib.IMAP4.error, TimeoutError, OSError) as exc:
                self.service._raise_imap(account, exc)
        return {
            "account": account.key,
            "folder": carpeta,
            "uids": chosen,
            "flag": "\\Seen",
            "action": "add" if seen else "remove",
        }

    def create_draft(
        self,
        account_key: str,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        account = self._gated(account_key, "drafts")
        draft_settings = self.service.settings
        if draft_settings.allowed_recipient_domains:
            draft_settings = replace(draft_settings, allowed_recipient_domains=())
        raw, public, _preview = build_outgoing(
            sender=account.username,
            sender_name=account.sender,
            to=to,
            cc=cc,
            bcc=None,
            subject=subject,
            body=body,
            in_reply_to=None,
            references=None,
            attachments=attachments,
            settings=draft_settings,
        )
        response = self._append(account, account.drafts_folder, raw, ["\\Draft"])
        return {
            "account": account.key,
            "status": "draft",
            "folder": account.drafts_folder,
            "draft_uid": _uid_de_append(response),
            "message_id": public.get("message_id", ""),
            "to": public["to"],
            "cc": public["cc"],
            "subject": public["subject"],
            "filenames": public["filenames"],
            "saved": True,
            "notice": "Borrador guardado. No se ha enviado nada.",
        }

    def _copy_to_sent(self, account: Account, folder: str, raw: bytes) -> tuple[bool, int | None]:
        """Guarda la copia en Enviados. Devuelve (copia hecha, uid)."""
        try:
            # Sin Bcc: los destinatarios ocultos no se guardan en Enviados.
            response = self._append(account, folder, without_bcc(raw), ["\\Seen"])
        except MailError as exc:
            logger.warning("Copia en Enviados no realizada (%s): %s", account.key, exc)
            return False, None
        return True, _uid_de_append(response)

    def _append(self, account: Account, folder: str, raw: bytes, flags: list[str]) -> Any:
        with self.service.session(account.key, writable=True) as client:
            try:
                return client.append(folder, raw, flags=flags)
            except (IMAPClientError, imaplib.IMAP4.error, TimeoutError, OSError) as exc:
                self.service._raise_imap(account, exc)

    def _move_to_trash(self, client: Any, folder: str, uids: list[int], trash: str) -> None:
        client.select_folder(folder, readonly=False)
        self._ensure_present(client, folder, uids)
        try:
            client.move(uids, trash)
        except (CapabilityError, AttributeError):
            client.copy(uids, trash)
            client.delete_messages(uids)
            client.expunge(uids)

    def _expunge(self, client: Any, folder: str, uids: list[int]) -> None:
        client.select_folder(folder, readonly=False)
        self._ensure_present(client, folder, uids)
        client.delete_messages(uids)
        client.expunge(uids)

    def _resolve_trash(self, client: Any, account: Account) -> str | None:
        try:
            rows = client.list_folders()
        except (IMAPClientError, imaplib.IMAP4.error, TimeoutError, OSError) as exc:
            self.service._raise_imap(account, exc)
        found: dict[str, set[str]] = {}
        for flags, _delimiter, name in rows:
            text = name.decode(errors="replace") if isinstance(name, bytes) else str(name)
            flag_names = {
                flag.decode(errors="replace") if isinstance(flag, bytes) else str(flag)
                for flag in flags or ()
            }
            found[text] = flag_names
        if account.trash_folder:
            if account.trash_folder not in found:
                raise MailError(
                    f"La carpeta {account.trash_folder} no existe. "
                    "Corrige trash_folder o quítala para usar la Papelera."
                )
            return account.trash_folder
        for name, flags in found.items():
            if "\\Trash" in flags:
                return name
        for candidate in _TRASH_NAMES:
            if candidate in found:
                return candidate
        return None

    def _summaries(self, client: Any, folder: str, uids: list[int]) -> list[dict[str, Any]]:
        fetched = client.fetch(uids, ["ENVELOPE"])
        rows: list[dict[str, Any]] = []
        missing: list[int] = []
        for uid in uids:
            data = fetched.get(uid)
            if not data:
                missing.append(uid)
                continue
            envelope = data.get(b"ENVELOPE") or data.get("ENVELOPE")
            rows.append(
                {
                    "uid": uid,
                    "subject": decode_header_value(getattr(envelope, "subject", None)),
                    "from": format_addresses(getattr(envelope, "from_", None)),
                }
            )
        if missing:
            joined = ", ".join(str(uid) for uid in missing)
            raise MailError(f"No existen estos UID en {folder}: {joined}.")
        return rows

    def _ensure_present(self, client: Any, folder: str, uids: list[int]) -> None:
        fetched = client.fetch(uids, ["FLAGS"])
        missing = [uid for uid in uids if uid not in fetched]
        if missing:
            joined = ", ".join(str(uid) for uid in missing)
            raise MailError(f"No existen estos UID en {folder}: {joined}.")

    def _gated(self, account_key: str, kind: str) -> Account:
        account = self.service._account(account_key)
        global_name, _account_name, _corta, label = WRITE_GATES[kind]
        if not getattr(self.service.settings, global_name):
            raise MailError(f"{label} está desactivado en el servidor.")
        if not account_allows(account, kind, self.service.settings):
            raise MailError(f"{label} está desactivado para la cuenta {account.key}.")
        return account


def _uid_list(values: list[int], limit: int) -> list[int]:
    if not isinstance(values, list) or not values:
        raise MailError("Indica al menos un uid.")
    if len(values) > limit:
        raise MailError(f"Demasiados mensajes en una sola llamada: el máximo es {limit}.")
    cleaned: list[int] = []
    for uid in values:
        if isinstance(uid, bool) or not isinstance(uid, int) or uid < 1:
            raise MailError("uid debe ser un entero mayor o igual que 1.")
        if uid not in cleaned:
            cleaned.append(uid)
    return cleaned
