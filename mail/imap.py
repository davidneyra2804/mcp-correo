"""Sesiones IMAP. La lectura usa EXAMINE y BODY.PEEK.

Una sesión de escritura solo la abre `mail.mutate` y solo dentro de la
operación que necesita STORE, MOVE o EXPUNGE. APPEND no selecciona carpeta.
"""

from __future__ import annotations

import imaplib
import logging
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, NoReturn

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError

from config import MAX_FOLDER_LENGTH, Account, ServerSettings
from mail.errors import MailError
from mail.mime import (
    decode_header_value,
    extract_attachment,
    format_addresses,
    parse_header_block,
    parse_message,
)
from mail.readonly import ReadOnlyIMAP, WritableIMAP
from mail.threads import group_threads, normalize_message_id, replied_ids_from_header_block
from scope import current_scope

logger = logging.getLogger("mcp_correo.imap")

ClientFactory = Callable[[Account, ServerSettings], Any]

_SUMMARY_ITEMS = ("ENVELOPE", "FLAGS", "RFC822.SIZE")
_HEADER_PEEK = "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID IN-REPLY-TO REFERENCES SUBJECT FROM DATE)]"
_SENT_PEEK = "BODY.PEEK[HEADER.FIELDS (IN-REPLY-TO REFERENCES)]"


def default_client_factory(account: Account, settings: ServerSettings) -> IMAPClient:
    return IMAPClient(
        host=account.imap_host,
        port=account.imap_port,
        ssl=account.imap_ssl,
        timeout=settings.imap_timeout,
    )


class MailService:
    def __init__(
        self,
        settings: ServerSettings,
        accounts: dict[str, Account],
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.settings = settings
        self.accounts = accounts
        self._factory = client_factory or default_client_factory

    def list_accounts(self) -> dict:
        scope = current_scope()
        accounts = [
            account for account in self.accounts.values() if scope is None or account.key in scope
        ]
        return {
            "accounts": [
                {
                    "account": account.key,
                    "label": account.label,
                    "user": account.username,
                    "can_send": self.settings.enable_send and account.allow_send,
                    "can_mark": self.settings.enable_mark and account.allow_mark,
                    "can_delete": self.settings.enable_delete and account.allow_delete,
                    "can_draft": self.settings.enable_drafts and account.allow_drafts,
                }
                for account in accounts
            ]
        }

    def list_folders(self, account: str) -> dict:
        def run(client: ReadOnlyIMAP) -> dict:
            rows = client.list_folders()
            folders = []
            for flags, delimiter, name in rows:
                flag_names = sorted(_flag_set(flags))
                folders.append(
                    {
                        "name": _as_text(name),
                        "delimiter": _as_text(delimiter),
                        "flags": flag_names,
                        "special_use": [flag for flag in flag_names if flag in _SPECIAL_USE],
                    }
                )
            return {"folders": folders}

        return self._with_account(account, run)

    def list_messages(
        self,
        account: str,
        folder: str = "INBOX",
        unseen: bool = False,
        since: str | None = None,
        sender: str | None = None,
        limit: int = 20,
    ) -> dict:
        criteria = _criteria(
            unseen=unseen,
            since=_parse_day(since, "since"),
            sender=_clean_text(sender, "sender"),
        )
        return self._search_summaries(account, folder, criteria, limit)

    def search_messages(
        self,
        account: str,
        folder: str = "INBOX",
        subject: str | None = None,
        text: str | None = None,
        sender: str | None = None,
        recipient: str | None = None,
        since: str | None = None,
        before: str | None = None,
        limit: int = 20,
    ) -> dict:
        criteria = _criteria(
            since=_parse_day(since, "since"),
            before=_parse_day(before, "before"),
            sender=_clean_text(sender, "sender"),
            recipient=_clean_text(recipient, "recipient"),
            subject=_clean_text(subject, "subject"),
            text=_clean_text(text, "text"),
        )
        if criteria == ["ALL"]:
            raise MailError(
                "Indica al menos un criterio: subject, text, sender, recipient, since o before"
            )
        return self._search_summaries(account, folder, criteria, limit)

    def get_message(
        self,
        account: str,
        uid: int,
        folder: str = "INBOX",
        max_chars: int | None = None,
    ) -> dict:
        limit = _clamp_chars(max_chars, self.settings)
        message_uid = _uid(uid)

        def run(client: ReadOnlyIMAP) -> dict:
            _examine(client, folder)
            _ensure_size(client, message_uid, folder, self.settings.max_message_bytes)
            fetched = client.fetch([message_uid], ["BODY.PEEK[]"])
            raw = _body_bytes(fetched.get(message_uid))
            parsed = parse_message(raw, limit)
            parsed.update({"account": account, "folder": folder, "uid": message_uid})
            return parsed

        return self._with_account(account, run)

    def get_attachment(
        self,
        account: str,
        uid: int,
        folder: str = "INBOX",
        index: int = 0,
        filename: str | None = None,
        max_chars: int | None = None,
    ) -> dict:
        limit = _clamp_chars(max_chars, self.settings)
        message_uid = _uid(uid)
        if index < 0:
            raise MailError("index debe ser mayor o igual que 0")

        def run(client: ReadOnlyIMAP) -> dict:
            _examine(client, folder)
            _ensure_size(client, message_uid, folder, self.settings.max_message_bytes)
            fetched = client.fetch([message_uid], ["BODY.PEEK[]"])
            raw = _body_bytes(fetched.get(message_uid))
            extracted = extract_attachment(raw, index, filename, self.settings, limit)
            extracted.update({"account": account, "folder": folder, "uid": message_uid})
            return extracted

        return self._with_account(account, run)

    def find_unanswered(
        self,
        account: str,
        folder: str = "INBOX",
        since: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Sin \\Answered y sin una respuesta en Enviados que cite el Message-ID."""
        bounded = _clamp_limit(limit, self.settings)
        since_day = _parse_day(since, "since")
        account_obj = self._account(account)

        def run(client: ReadOnlyIMAP) -> dict:
            _examine(client, folder)
            criteria = _criteria(unanswered=True, since=since_day)
            uids = _highest_uids(client.search(criteria), self.settings.max_results)
            summaries = _fetch_summaries(client, uids) if uids else []
            replied, crosscheck = _sent_reply_index(
                client, account_obj.sent_folder, self.settings.sent_scan_limit
            )
            pending = []
            for summary in _newest_first(summaries):
                if summary["answered"]:
                    continue
                message_id = normalize_message_id(str(summary.get("message_id") or ""))
                if message_id and message_id in replied:
                    continue
                pending.append(summary)
                if len(pending) >= bounded:
                    break
            if crosscheck:
                criterion = (
                    "sin flag \\Answered y sin In-Reply-To ni References en la carpeta de enviados"
                )
            else:
                # No se pudo abrir la carpeta de enviados: no se puede afirmar
                # el criterio completo. Decirlo, en vez de fingir.
                criterion = (
                    "sin flag \\Answered. La carpeta de enviados no se pudo abrir, "
                    "así que no se ha comprobado si hay respuesta: puede haber mensajes "
                    "que sí tienen respuesta."
                )
            return {
                "messages": pending,
                "sent_folder": account_obj.sent_folder,
                "sent_crosscheck": crosscheck,
                "criterion": criterion,
            }

        return self._with_account(account, run)

    def list_threads(self, account: str, folder: str = "INBOX", limit: int = 20) -> dict:
        """Hilos por References / In-Reply-To sobre los UID más altos de la carpeta.

        v1 agrupa en Python. THREAD=REFERENCES de IMAP devuelve números de
        secuencia, no UID, y mezclarlos con el modo UID de IMAPClient sería
        frágil. El cruce queda acotado a `limit` mensajes.
        """
        bounded = _clamp_limit(limit, self.settings)

        def run(client: ReadOnlyIMAP) -> dict:
            _examine(client, folder)
            uids = _highest_uids(client.search(["ALL"]), bounded)
            if not uids:
                return {"threads": [], "threading": "references", "window": bounded}
            fetched = client.fetch(uids, [_HEADER_PEEK, "FLAGS", "ENVELOPE"])
            records = []
            for uid in uids:
                data = fetched.get(uid) or {}
                headers = parse_header_block(_header_bytes(data))
                envelope = data.get(b"ENVELOPE") or data.get("ENVELOPE")
                flags = _flag_set(data.get(b"FLAGS", data.get("FLAGS")))
                records.append(
                    {
                        "uid": uid,
                        "message_id": headers.get("message-id")
                        or _envelope_text(envelope, "message_id"),
                        "in_reply_to": headers.get("in-reply-to")
                        or _envelope_text(envelope, "in_reply_to"),
                        "references": headers.get("references", ""),
                        "subject": headers.get("subject")
                        or decode_header_value(getattr(envelope, "subject", None)),
                        "from": headers.get("from")
                        or format_addresses(getattr(envelope, "from_", None)),
                        "date": _date_text(envelope) or headers.get("date"),
                        "answered": "\\Answered" in flags,
                    }
                )
            return {
                "threads": group_threads(records),
                "threading": "references",
                "window": bounded,
            }

        return self._with_account(account, run)

    def _search_summaries(
        self,
        account: str,
        folder: str,
        criteria: list[Any],
        limit: int,
    ) -> dict:
        bounded = _clamp_limit(limit, self.settings)

        def run(client: ReadOnlyIMAP) -> dict:
            _examine(client, folder)
            charset = "UTF-8" if _needs_charset(criteria) else None
            uids = _highest_uids(client.search(criteria, charset=charset), bounded)
            messages = _newest_first(_fetch_summaries(client, uids))
            return {"messages": messages}

        return self._with_account(account, run)

    def session(self, account_key: str, *, writable: bool = False) -> Iterator[Any]:
        """Abre IMAP. `writable=False` envuelve el cliente en solo lectura."""
        return self._session(account_key, writable=writable)

    def _with_account(self, account: str, action: Callable[[ReadOnlyIMAP], dict]) -> dict:
        with self._session(account) as client:
            try:
                return action(client)
            except MailError:
                raise
            except (IMAPClientError, imaplib.IMAP4.error, TimeoutError, OSError) as exc:
                self._raise_imap(self._account(account), exc)

    @contextmanager
    def _session(self, account_key: str, *, writable: bool = False) -> Iterator[Any]:
        account = self._account(account_key)
        raw = self._factory(account, self.settings)
        try:
            try:
                raw.login(account.username, account.password)
            except (IMAPClientError, imaplib.IMAP4.error, TimeoutError, OSError) as exc:
                self._raise_imap(account, exc)
            client: Any = WritableIMAP(raw) if writable else ReadOnlyIMAP(raw)
            try:
                yield client
            finally:
                try:
                    raw.logout()
                except (IMAPClientError, imaplib.IMAP4.error, OSError):
                    logger.info("Cierre de sesión IMAP incompleto en %s", account.key)
        finally:
            shutdown = getattr(raw, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except (IMAPClientError, imaplib.IMAP4.error, OSError):
                    logger.info("No se pudo cerrar el socket IMAP de %s", account.key)

    def _account(self, key: str) -> Account:
        account = self.accounts.get(key)
        if account is None:
            known = ", ".join(sorted(self.accounts)) or "(ninguna)"
            raise MailError(f"Cuenta desconocida: {key}. Cuentas configuradas: {known}")
        scope = current_scope()
        if scope is not None and key not in scope:
            raise MailError(
                f"La cuenta {key} no está disponible en esta ruta. "
                "Esta ruta expone: " + (", ".join(sorted(scope)) or "(ninguna)") + "."
            )
        return account

    def _raise_imap(self, account: Account, exc: BaseException) -> NoReturn:
        safe = _scrub(str(exc), account.password)
        logger.warning("IMAP %s (%s): %s", account.key, type(exc).__name__, safe)
        if isinstance(exc, TimeoutError):
            raise MailError(
                f"Tiempo de espera IMAP agotado ({self.settings.imap_timeout}s) "
                f"en la cuenta {account.key}"
            ) from None
        if isinstance(exc, OSError) and not isinstance(exc, imaplib.IMAP4.error):
            raise MailError(f"No se pudo conectar por IMAP con la cuenta {account.key}") from None
        raise MailError(
            f"El servidor IMAP rechazó la operación en la cuenta {account.key}"
        ) from None


_SPECIAL_USE = frozenset(
    {
        "\\All",
        "\\Archive",
        "\\Drafts",
        "\\Flagged",
        "\\Junk",
        "\\Sent",
        "\\Trash",
        "\\Important",
    }
)


def _examine(client: ReadOnlyIMAP, folder: str) -> None:
    name = _folder(folder)
    try:
        client.select_folder(name, readonly=True)
    except (IMAPClientError, imaplib.IMAP4.error) as exc:
        logger.info("EXAMINE falló en %s (%s)", name, type(exc).__name__)
        raise MailError(f"No se pudo abrir la carpeta {name}") from None


def _ensure_size(client: ReadOnlyIMAP, uid: int, folder: str, limit: int) -> None:
    fetched = client.fetch([uid], ["RFC822.SIZE"])
    data = fetched.get(uid)
    if not data:
        raise MailError(f"No existe el UID {uid} en {folder}")
    size = data.get(b"RFC822.SIZE", data.get("RFC822.SIZE"))
    if isinstance(size, int) and size > limit:
        raise MailError(f"El mensaje ocupa {size} bytes y el límite de descarga es {limit}")


def _fetch_summaries(client: ReadOnlyIMAP, uids: list[int]) -> list[dict]:
    if not uids:
        return []
    fetched = client.fetch(uids, list(_SUMMARY_ITEMS))
    summaries = []
    for uid in uids:
        data = fetched.get(uid)
        if not data:
            continue
        envelope = data.get(b"ENVELOPE") or data.get("ENVELOPE")
        flags = _flag_set(data.get(b"FLAGS", data.get("FLAGS")))
        size = data.get(b"RFC822.SIZE", data.get("RFC822.SIZE"))
        summaries.append(
            {
                "uid": uid,
                "date": _date_text(envelope),
                "from": format_addresses(getattr(envelope, "from_", None)),
                "to": format_addresses(getattr(envelope, "to", None)),
                "subject": decode_header_value(getattr(envelope, "subject", None)),
                "seen": "\\Seen" in flags,
                "answered": "\\Answered" in flags,
                "flagged": "\\Flagged" in flags,
                "size": size if isinstance(size, int) else None,
                "message_id": decode_header_value(getattr(envelope, "message_id", None)),
            }
        )
    return summaries


def _sent_reply_index(client: ReadOnlyIMAP, folder: str, scan_limit: int) -> tuple[set[str], bool]:
    try:
        client.select_folder(folder, readonly=True)
    except (IMAPClientError, imaplib.IMAP4.error, OSError):
        return set(), False
    uids = _highest_uids(client.search(["ALL"]), scan_limit)
    if not uids:
        return set(), True
    fetched = client.fetch(uids, [_SENT_PEEK])
    replied: set[str] = set()
    for data in fetched.values():
        raw = _header_bytes(data)
        replied.update(replied_ids_from_header_block(raw))
    return replied, True


def _criteria(
    *,
    unseen: bool = False,
    unanswered: bool = False,
    since: date | None = None,
    before: date | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    subject: str | None = None,
    text: str | None = None,
) -> list[Any]:
    criteria: list[Any] = []
    if unseen:
        criteria.append("UNSEEN")
    if unanswered:
        criteria.append("UNANSWERED")
    if since is not None:
        criteria.extend(["SINCE", since])
    if before is not None:
        criteria.extend(["BEFORE", before])
    if sender:
        criteria.extend(["FROM", sender])
    if recipient:
        criteria.extend(["TO", recipient])
    if subject:
        criteria.extend(["SUBJECT", subject])
    if text:
        criteria.extend(["TEXT", text])
    return criteria or ["ALL"]


def _needs_charset(criteria: list[Any]) -> bool:
    return any(item in {"FROM", "TO", "SUBJECT", "TEXT"} for item in criteria)


def _highest_uids(uids: Iterable[int], limit: int) -> list[int]:
    ordered = sorted(int(uid) for uid in uids)
    return ordered[-limit:]


def _newest_first(messages: list[dict]) -> list[dict]:
    return sorted(messages, key=lambda item: (item.get("date") or "", item["uid"]), reverse=True)


def _body_bytes(data: dict | None) -> bytes:
    if not data:
        raise MailError("El servidor IMAP no devolvió el mensaje")
    for key, value in data.items():
        name = _as_text(key).upper()
        if name in {"BODY[]", "BODY.PEEK[]"} and isinstance(value, bytes | str):
            return value if isinstance(value, bytes) else value.encode()
    raise MailError("El servidor IMAP no devolvió el cuerpo del mensaje")


def _header_bytes(data: dict) -> bytes:
    for key, value in data.items():
        name = _as_text(key).upper()
        if "HEADER.FIELDS" in name and isinstance(value, bytes | str):
            return value if isinstance(value, bytes) else value.encode()
    return b""


def _flag_set(flags: object) -> set[str]:
    found: set[str] = set()
    for flag in flags or ():
        found.add(_as_text(flag))
    return found


def _date_text(envelope: object) -> str | None:
    when = getattr(envelope, "date", None)
    if isinstance(when, datetime):
        return when.isoformat()
    if isinstance(when, date):
        return when.isoformat()
    return None


def _envelope_text(envelope: object, attr: str) -> str:
    if envelope is None:
        return ""
    return decode_header_value(getattr(envelope, attr, None))


def _parse_day(value: str | None, field_name: str) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise MailError(f"{field_name} debe tener formato AAAA-MM-DD") from None


def _clean_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if any(char in value for char in "\r\n\x00"):
        raise MailError(f"{field_name} contiene caracteres no permitidos")
    if len(value) > 500:
        raise MailError(f"{field_name} supera los 500 caracteres")
    return value


def _folder(folder: str) -> str:
    if not isinstance(folder, str) or not folder.strip() or len(folder) > MAX_FOLDER_LENGTH:
        raise MailError("Nombre de carpeta inválido")
    if any(char in folder for char in "\r\n\x00"):
        raise MailError("Nombre de carpeta inválido")
    return folder


def _uid(uid: int) -> int:
    if not isinstance(uid, int) or isinstance(uid, bool) or uid < 1:
        raise MailError("uid debe ser un entero mayor o igual que 1")
    return uid


def _clamp_limit(limit: int, settings: ServerSettings) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise MailError("limit debe ser un entero mayor o igual que 1")
    return min(limit, settings.max_results)


def _clamp_chars(max_chars: int | None, settings: ServerSettings) -> int:
    if max_chars is None:
        return settings.max_chars
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1:
        raise MailError("max_chars debe ser un entero mayor o igual que 1")
    return min(max_chars, settings.max_chars)


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _scrub(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "***")
    return text[:400]
