"""Proxies IMAP. La lectura siempre es EXAMINE y BODY.PEEK.

`ReadOnlyIMAP` bloquea STORE, APPEND, MOVE y EXPUNGE.
`WritableIMAP` solo lo usa la operación de escritura que necesita mutar el buzón:
el FETCH sigue siendo PEEK y no abre carpetas, buzones ni IDLE.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mail.errors import MailError

# Nombres de métodos de IMAPClient (y atajos) que modifican el buzón o las flags.
FORBIDDEN_METHODS = frozenset(
    {
        "append",
        "copy",
        "move",
        "expunge",
        "delete_messages",
        "delete_folder",
        "set_flags",
        "add_flags",
        "remove_flags",
        "set_gmail_labels",
        "add_gmail_labels",
        "remove_gmail_labels",
        "create_folder",
        "rename_folder",
        "subscribe_folder",
        "unsubscribe_folder",
        "idle",
        "store",
        "_store",
    }
)

_SAFE_FETCH = frozenset(
    {
        "FLAGS",
        "ENVELOPE",
        "RFC822.SIZE",
        "INTERNALDATE",
        "UID",
        "BODYSTRUCTURE",
        "MODSEQ",
    }
)


def force_peek(item: str | bytes) -> str:
    """Convierte un ítem FETCH que marcaría \\Seen en su equivalente PEEK."""
    text = item.decode() if isinstance(item, bytes) else str(item)
    upper = text.upper()
    if upper in _SAFE_FETCH:
        return text
    if upper in {"RFC822", "BODY[]"}:
        return "BODY.PEEK[]"
    if upper == "RFC822.HEADER":
        return "BODY.PEEK[HEADER]"
    if upper.startswith("RFC822.TEXT"):
        return "BODY.PEEK[TEXT]"
    if upper.startswith("BODY.PEEK"):
        return text
    if upper.startswith("BODY["):
        return "BODY.PEEK" + text[4:]
    return text


# Métodos de escritura que WritableIMAP deja pasar. El resto de FORBIDDEN_METHODS sigue bloqueado.
_WRITABLE_METHODS = frozenset(
    {
        "append",
        "copy",
        "move",
        "expunge",
        "delete_messages",
        "set_flags",
        "add_flags",
        "remove_flags",
    }
)


class ReadOnlyIMAP:
    """Proxy: `select_folder` siempre es EXAMINE y `fetch` siempre usa PEEK."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def select_folder(self, folder: str, readonly: bool = True) -> Any:
        # readonly=True hace que imaplib envíe EXAMINE, no SELECT.
        return self._raw.select_folder(folder, readonly=True)

    def fetch(
        self,
        messages: Iterable[int],
        data: Iterable[str | bytes],
        modifiers: Iterable[str] | None = None,
    ) -> Any:
        safe = [force_peek(item) for item in data]
        if modifiers is None:
            return self._raw.fetch(messages, safe)
        return self._raw.fetch(messages, safe, modifiers)

    def __getattr__(self, name: str) -> Any:
        if name in FORBIDDEN_METHODS or name.startswith("_"):
            raise MailError(f"Operación prohibida en solo lectura: {name}")
        return getattr(self._raw, name)


class WritableIMAP:
    """Proxy de una operación de escritura. El FETCH no marca \\Seen.

    `select_folder` respeta el argumento `readonly`. Quien escribe pasa
    lectura-escritura solo en el SELECT de esa operación. El literal de
    ese argumento vive en `mail/mutate.py`, no aquí.
    """

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def select_folder(self, folder: str, readonly: bool = True) -> Any:
        return self._raw.select_folder(folder, readonly=readonly)

    def fetch(
        self,
        messages: Iterable[int],
        data: Iterable[str | bytes],
        modifiers: Iterable[str] | None = None,
    ) -> Any:
        safe = [force_peek(item) for item in data]
        if modifiers is None:
            return self._raw.fetch(messages, safe)
        return self._raw.fetch(messages, safe, modifiers)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or (name in FORBIDDEN_METHODS and name not in _WRITABLE_METHODS):
            raise MailError(f"Operación no permitida: {name}")
        return getattr(self._raw, name)
