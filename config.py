"""Carga de cuentas y límites. Las contraseñas solo entran por el entorno."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MIN_TOKEN_LENGTH = 16

DEFAULT_ATTACHMENT_TYPES: tuple[str, ...] = (
    "text/plain",
    "text/csv",
    "text/html",
    "application/pdf",
    "application/json",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
)

_ACCOUNT_KEYS = {
    "label",
    "imap_host",
    "imap_port",
    "imap_ssl",
    "smtp_host",
    "smtp_port",
    "username",
    "password_env",
    "drafts_folder",
    "sent_folder",
    "trash_folder",
    "smtp_security",
    "allow_send",
    "allow_mark",
    "allow_delete",
    "allow_drafts",
}

_SERVER_KEYS = {
    "public_host",
    "bind_host",
    "bind_port",
    "max_results",
    "max_chars",
    "max_attachment_bytes",
    "max_message_bytes",
    "imap_timeout",
    "sent_scan_limit",
    "enable_drafts",
    "enable_send",
    "enable_mark",
    "enable_delete",
    "confirm_ttl_seconds",
    "max_recipients",
    "max_sends_per_day",
    "max_delete_per_call",
    "max_mark_per_call",
    "smtp_timeout",
    "smtp_security",
    "allowed_recipient_domains",
    "allowed_attachment_types",
    "allowed_hosts",
    "allowed_origins",
    "audit_log",
}

LOCAL_BIND_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True)
class ServerSettings:
    public_host: str
    bind_host: str
    bind_port: int
    max_results: int
    max_chars: int
    max_attachment_bytes: int
    max_message_bytes: int
    imap_timeout: float
    sent_scan_limit: int
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    allowed_attachment_types: tuple[str, ...]
    audit_log: str
    enable_drafts: bool = False
    enable_send: bool = False
    enable_mark: bool = False
    enable_delete: bool = False
    confirm_ttl_seconds: int = 600
    max_recipients: int = 10
    max_sends_per_day: int = 30
    max_delete_per_call: int = 20
    max_mark_per_call: int = 50
    smtp_timeout: float = 30
    smtp_security: str = "ssl"
    allowed_recipient_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class Account:
    """Cuenta IMAP. `password` no aparece en repr ni en trazas del dataclass."""

    key: str
    label: str
    imap_host: str
    imap_port: int
    username: str
    password: str = field(repr=False, compare=False)
    imap_ssl: bool = True
    smtp_host: str = ""
    smtp_port: int = 465
    drafts_folder: str = "Drafts"
    sent_folder: str = "Sent"
    trash_folder: str = ""
    smtp_security: str = ""
    allow_send: bool = False
    allow_mark: bool = False
    allow_delete: bool = False
    allow_drafts: bool = False


def require_bearer_token() -> str:
    """Detiene el proceso si no hay token. No registra el valor."""
    raw = os.environ.get("MCP_BEARER_TOKEN")
    if raw is None or not raw.strip():
        raise SystemExit("Falta MCP_BEARER_TOKEN. El servidor no arranca sin autenticación Bearer.")
    token = raw.strip()
    if len(token) < MIN_TOKEN_LENGTH:
        raise SystemExit(
            f"MCP_BEARER_TOKEN es demasiado corto (mínimo {MIN_TOKEN_LENGTH} caracteres). "
            "Genera uno con: openssl rand -base64 48"
        )
    return token


def resolve_config_path() -> Path:
    env_path = os.environ.get("MCP_CONFIG")
    if env_path:
        return Path(env_path)
    local = Path("accounts.toml")
    if local.is_file():
        return local
    system = Path("/etc/vyr-mail-mcp/accounts.toml")
    if system.is_file():
        return system
    raise SystemExit(
        "No hay configuración. Define MCP_CONFIG o crea accounts.toml "
        "(puedes partir de accounts.example.toml)."
    )


def load_config(path: Path | None = None) -> tuple[ServerSettings, dict[str, Account]]:
    config_path = path or resolve_config_path()
    if not config_path.is_file():
        raise SystemExit(f"No se encuentra la configuración: {config_path}")
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"TOML inválido en {config_path}: {exc}") from None

    if not isinstance(data, dict):
        raise SystemExit("La configuración debe ser una tabla TOML")

    server_raw = data.get("server") or {}
    accounts_raw = data.get("accounts") or {}
    if not isinstance(server_raw, dict) or not isinstance(accounts_raw, dict):
        raise SystemExit("Las secciones [server] y [accounts] deben ser tablas")
    if not accounts_raw:
        raise SystemExit("No hay cuentas en la configuración")

    _reject_unknown("server", server_raw, _SERVER_KEYS)
    settings = _server_settings(server_raw)
    accounts = {key: _account(str(key), value) for key, value in accounts_raw.items()}
    return settings, accounts


def ensure_local_bind(bind_host: str) -> None:
    if bind_host in LOCAL_BIND_HOSTS:
        return
    if os.environ.get("MCP_ALLOW_NONLOCAL_BIND") == "1":
        return
    raise SystemExit(
        f"bind_host {bind_host!r} no es loopback. v1 escucha solo en 127.0.0.1, "
        "::1 o localhost. Define MCP_ALLOW_NONLOCAL_BIND=1 solo si nginx no es "
        "quien publica el puerto."
    )


def _server_settings(raw: dict) -> ServerSettings:
    public_host = str(raw.get("public_host") or "127.0.0.1")
    bind_host = os.environ.get("MCP_BIND_HOST") or str(raw.get("bind_host") or "127.0.0.1")
    bind_port = _port(_env_int("MCP_BIND_PORT") or raw.get("bind_port") or 8765, "bind_port")
    max_results = _positive_int(raw.get("max_results", 100), "max_results")
    max_chars = _positive_int(raw.get("max_chars", 20_000), "max_chars")
    max_attachment_bytes = _positive_int(
        raw.get("max_attachment_bytes", 5_000_000), "max_attachment_bytes"
    )
    max_message_bytes = _positive_int(raw.get("max_message_bytes", 15_000_000), "max_message_bytes")
    imap_timeout = float(raw.get("imap_timeout", 20))
    if imap_timeout <= 0:
        raise SystemExit("imap_timeout debe ser mayor que 0")
    sent_scan_limit = _positive_int(raw.get("sent_scan_limit", 300), "sent_scan_limit")
    attachment_types = _str_tuple(
        raw.get("allowed_attachment_types"),
        DEFAULT_ATTACHMENT_TYPES,
    )
    hosts = _str_tuple(raw.get("allowed_hosts"), _default_hosts(public_host))
    origins = _str_tuple(raw.get("allowed_origins"), _default_origins(public_host))
    audit_log = os.environ.get("MCP_AUDIT_LOG") or str(raw.get("audit_log") or "audit.jsonl")
    smtp_timeout = float(raw.get("smtp_timeout", 30))
    if smtp_timeout <= 0:
        raise SystemExit("smtp_timeout debe ser mayor que 0")
    return ServerSettings(
        public_host=public_host,
        bind_host=bind_host,
        bind_port=bind_port,
        max_results=max_results,
        max_chars=max_chars,
        max_attachment_bytes=max_attachment_bytes,
        max_message_bytes=max_message_bytes,
        imap_timeout=imap_timeout,
        sent_scan_limit=sent_scan_limit,
        allowed_hosts=hosts,
        allowed_origins=origins,
        allowed_attachment_types=tuple(item.lower() for item in attachment_types),
        audit_log=audit_log,
        enable_drafts=_as_bool(raw.get("enable_drafts"), "enable_drafts"),
        enable_send=_as_bool(raw.get("enable_send"), "enable_send"),
        enable_mark=_as_bool(raw.get("enable_mark"), "enable_mark"),
        enable_delete=_as_bool(raw.get("enable_delete"), "enable_delete"),
        confirm_ttl_seconds=_positive_int(
            raw.get("confirm_ttl_seconds", 600), "confirm_ttl_seconds"
        ),
        max_recipients=_positive_int(raw.get("max_recipients", 10), "max_recipients"),
        max_sends_per_day=_positive_int(raw.get("max_sends_per_day", 30), "max_sends_per_day"),
        max_delete_per_call=_positive_int(
            raw.get("max_delete_per_call", 20), "max_delete_per_call"
        ),
        max_mark_per_call=_positive_int(raw.get("max_mark_per_call", 50), "max_mark_per_call"),
        smtp_timeout=smtp_timeout,
        smtp_security=_smtp_security(raw.get("smtp_security", "ssl"), "smtp_security"),
        allowed_recipient_domains=_domains(raw.get("allowed_recipient_domains")),
    )


def _account(key: str, raw: object) -> Account:
    if not isinstance(raw, dict):
        raise SystemExit(f"La cuenta {key!r} debe ser una tabla")
    if "password" in raw:
        raise SystemExit(
            f"La cuenta {key!r} trae una contraseña en el TOML. "
            "Usa solo password_env con el nombre de la variable de entorno."
        )
    _reject_unknown(f"accounts.{key}", raw, _ACCOUNT_KEYS)
    env_name = raw.get("password_env")
    if not isinstance(env_name, str) or not ENV_NAME.fullmatch(env_name):
        raise SystemExit(f"password_env inválido en la cuenta {key!r}")
    if "PASSWORD" not in env_name.upper() and "PASS" not in env_name.upper():
        raise SystemExit(
            f"password_env de {key!r} debería ser el nombre de una variable "
            "(por ejemplo MAIL_VYRTS_PASSWORD), no un secreto"
        )
    password = os.environ.get(env_name)
    if password is None or password == "":
        raise SystemExit(
            f"Falta la variable de entorno {env_name} para la cuenta {key!r}. "
            "El servidor no arranca con cuentas sin secreto."
        )
    username = _required_str(raw, "username", key)
    imap_host = _required_str(raw, "imap_host", key)
    label = str(raw.get("label") or key)
    return Account(
        key=key,
        label=label,
        imap_host=imap_host,
        imap_port=_port(raw.get("imap_port", 993), f"{key}.imap_port"),
        imap_ssl=bool(raw.get("imap_ssl", True)),
        smtp_host=str(raw.get("smtp_host") or imap_host),
        smtp_port=_port(raw.get("smtp_port", 465), f"{key}.smtp_port"),
        username=username,
        password=password,
        drafts_folder=str(raw.get("drafts_folder") or "Drafts"),
        sent_folder=str(raw.get("sent_folder") or "Sent"),
        trash_folder=_optional_folder(raw.get("trash_folder"), f"{key}.trash_folder"),
        smtp_security=_optional_security(raw.get("smtp_security"), f"{key}.smtp_security"),
        allow_send=_as_bool(raw.get("allow_send"), f"{key}.allow_send"),
        allow_mark=_as_bool(raw.get("allow_mark"), f"{key}.allow_mark"),
        allow_delete=_as_bool(raw.get("allow_delete"), f"{key}.allow_delete"),
        allow_drafts=_as_bool(raw.get("allow_drafts"), f"{key}.allow_drafts"),
    )


def write_capabilities(settings: ServerSettings, accounts: dict[str, Account]) -> dict[str, bool]:
    """Una tool de escritura existe solo si el interruptor global y alguna cuenta lo permiten."""
    return {
        "send": settings.enable_send and any(account.allow_send for account in accounts.values()),
        "mark": settings.enable_mark and any(account.allow_mark for account in accounts.values()),
        "delete": settings.enable_delete
        and any(account.allow_delete for account in accounts.values()),
        "drafts": settings.enable_drafts
        and any(account.allow_drafts for account in accounts.values()),
    }


def _reject_unknown(where: str, raw: dict, allowed: set[str]) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise SystemExit(f"Claves no reconocidas en [{where}]: {', '.join(extra)}")


def _required_str(raw: dict, field_name: str, key: str) -> str:
    value = raw.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"La cuenta {key!r} necesita {field_name}")
    return value.strip()


def _as_bool(value: object, field_name: str) -> bool:
    """Solo un booleano TOML. Un texto no puede encender un interruptor."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise SystemExit(f"{field_name} debe ser true o false, no un texto")


def _smtp_security(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise SystemExit(f"{field_name} debe ser ssl o starttls")
    text = value.strip().lower()
    if text not in {"ssl", "starttls"}:
        raise SystemExit(f"{field_name} debe ser ssl o starttls")
    return text


def _optional_security(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _smtp_security(value, field_name)


def _optional_folder(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or len(value) > 200 or any(char in value for char in "\r\n\x00"):
        raise SystemExit(f"{field_name} no es un nombre de carpeta válido")
    return value


def _domains(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    items = _str_tuple(value, ())
    domains: list[str] = []
    for item in items:
        domain = item.strip().lower().lstrip("@")
        if not domain:
            continue
        if any(char in domain for char in " \t\r\n\x00/@"):
            raise SystemExit(f"Dominio de destinatario no válido: {item!r}")
        domains.append(domain)
    return tuple(domains)


def _positive_int(value: object, field_name: str) -> int:
    number = int(value)  # type: ignore[arg-type]
    if number < 1:
        raise SystemExit(f"{field_name} debe ser mayor o igual que 1")
    return number


def _port(value: object, field_name: str) -> int:
    number = int(value)  # type: ignore[arg-type]
    if not 1 <= number <= 65535:
        raise SystemExit(f"{field_name} fuera de rango: {number}")
    return number


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    return int(raw)


def _str_tuple(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    raise SystemExit("Se esperaba una lista de textos en la configuración")


def _default_hosts(public_host: str) -> tuple[str, ...]:
    return (
        public_host,
        f"{public_host}:*",
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
        "[::1]",
        "[::1]:*",
    )


def _default_origins(public_host: str) -> tuple[str, ...]:
    return (
        f"https://{public_host}",
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
    )
