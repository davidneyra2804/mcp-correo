"""Las filas de la base de datos y cómo se convierten en cuentas.

La base guarda los valores tal cual: un permiso que no se ha decidido es
``NULL``, no ``False``. La conversión a ``config.Account`` es donde se
resuelven los defaults (el dominio, y detrás el servidor) y la cadena de
permisos.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from config import Account, ServerSettings, resolve_permission


def _tri(value: object) -> bool | None:
    """El tri-estado de la base: NULL = sin definir."""
    if value is None:
        return None
    return bool(value)


@dataclass(frozen=True)
class DomainRecord:
    """Un dominio: un grupo de cuentas con su credencial y sus defaults."""

    id: int
    name: str
    label: str = ""
    is_default: bool = False
    bearer: str = ""
    allow_send: bool | None = None
    allow_mark: bool | None = None
    allow_delete: bool | None = None
    allow_drafts: bool | None = None
    allow_direct_send: bool | None = None
    imap_host: str = ""
    imap_port: int | None = None
    imap_ssl: bool | None = None
    smtp_host: str = ""
    smtp_port: int | None = None
    smtp_security: str = ""
    created_at: str = ""

    @classmethod
    def from_row(cls, fila: sqlite3.Row) -> DomainRecord:
        return cls(
            id=int(fila["id"]),
            name=str(fila["name"]),
            label=str(fila["label"] or ""),
            is_default=bool(fila["is_default"]),
            bearer=str(fila["bearer"] or ""),
            allow_send=_tri(fila["allow_send"]),
            allow_mark=_tri(fila["allow_mark"]),
            allow_delete=_tri(fila["allow_delete"]),
            allow_drafts=_tri(fila["allow_drafts"]),
            allow_direct_send=_tri(fila["allow_direct_send"]),
            imap_host=str(fila["imap_host"] or ""),
            imap_port=fila["imap_port"],
            imap_ssl=_tri(fila["imap_ssl"]),
            smtp_host=str(fila["smtp_host"] or ""),
            smtp_port=fila["smtp_port"],
            smtp_security=str(fila["smtp_security"] or ""),
            created_at=str(fila["created_at"] or ""),
        )


@dataclass(frozen=True)
class AccountRecord:
    """Una cuenta. La contraseña va cifrada."""

    id: int
    domain_id: int
    name: str
    label: str = ""
    sender: str = ""
    username: str = ""
    password: bytes = b""
    imap_host: str = ""
    imap_port: int | None = None
    imap_ssl: bool | None = None
    smtp_host: str = ""
    smtp_port: int | None = None
    smtp_security: str = ""
    drafts_folder: str = ""
    sent_folder: str = ""
    trash_folder: str = ""
    allow_send: bool | None = None
    allow_mark: bool | None = None
    allow_delete: bool | None = None
    allow_drafts: bool | None = None
    allow_direct_send: bool | None = None
    bearer: str = ""
    enabled: bool = True
    created_at: str = ""

    @classmethod
    def from_row(cls, fila: sqlite3.Row) -> AccountRecord:
        return cls(
            id=int(fila["id"]),
            domain_id=int(fila["domain_id"]),
            name=str(fila["name"]),
            label=str(fila["label"] or ""),
            sender=str(fila["sender"] or ""),
            username=str(fila["username"]),
            password=bytes(fila["password"] or b""),
            imap_host=str(fila["imap_host"] or ""),
            imap_port=fila["imap_port"],
            imap_ssl=_tri(fila["imap_ssl"]),
            smtp_host=str(fila["smtp_host"] or ""),
            smtp_port=fila["smtp_port"],
            smtp_security=str(fila["smtp_security"] or ""),
            drafts_folder=str(fila["drafts_folder"] or ""),
            sent_folder=str(fila["sent_folder"] or ""),
            trash_folder=str(fila["trash_folder"] or ""),
            allow_send=_tri(fila["allow_send"]),
            allow_mark=_tri(fila["allow_mark"]),
            allow_delete=_tri(fila["allow_delete"]),
            allow_drafts=_tri(fila["allow_drafts"]),
            allow_direct_send=_tri(fila["allow_direct_send"]),
            bearer=str(fila["bearer"] or ""),
            enabled=bool(fila["enabled"]),
            created_at=str(fila["created_at"] or ""),
        )


def to_account(
    record: AccountRecord,
    domain: DomainRecord,
    password: str,
    settings: ServerSettings,
) -> Account:
    """La cuenta que el servidor usa, con los defaults ya resueltos.

    El orden es: la cuenta, luego el dominio, luego el servidor. Lo mismo
    que en la cadena de permisos, y por el mismo motivo: el más
    específico manda y el que no dice nada hereda.
    """
    imap_host = record.imap_host or domain.imap_host
    imap_port = record.imap_port
    if imap_port is None:
        imap_port = domain.imap_port if domain.imap_port is not None else 993
    imap_ssl = record.imap_ssl
    if imap_ssl is None:
        imap_ssl = domain.imap_ssl if domain.imap_ssl is not None else True
    smtp_security = record.smtp_security or domain.smtp_security
    smtp_host = record.smtp_host or domain.smtp_host or imap_host
    smtp_port = record.smtp_port
    if smtp_port is None:
        smtp_port = domain.smtp_port
    if smtp_port is None:
        modo = smtp_security or settings.smtp_security
        smtp_port = 465 if modo == "ssl" else 587
    return Account(
        key=record.name,
        label=record.label or record.name,
        sender=record.sender,
        imap_host=imap_host,
        imap_port=imap_port,
        imap_ssl=imap_ssl,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_security=smtp_security,
        username=record.username,
        password=password,
        bearer=record.bearer,
        drafts_folder=record.drafts_folder or "Drafts",
        sent_folder=record.sent_folder or "Sent",
        trash_folder=record.trash_folder,
        allow_send=resolve_permission(record.allow_send, domain.allow_send),
        allow_mark=resolve_permission(record.allow_mark, domain.allow_mark),
        allow_delete=resolve_permission(record.allow_delete, domain.allow_delete),
        allow_drafts=resolve_permission(record.allow_drafts, domain.allow_drafts),
        allow_direct_send=resolve_permission(record.allow_direct_send, domain.allow_direct_send),
        index=record.id,
        domain=domain.name,
    )
