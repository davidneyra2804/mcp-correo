"""Carga de configuración. Las contraseñas solo entran por el entorno.

Dos fuentes, con precedencia clara:

1. **Variables de entorno** (fuente primaria). Cada clave de ``[server]``
   tiene su variable ``MCP_*``. Las cuentas se declaran con una variable por
   campo: ``MCP_ACCOUNT_<CAMPO>_<N>``, con el índice al final.
2. **``accounts.toml``** (fuente alternativa, para lo que ya lo use, como el
   despliegue con systemd).

La precedencia es entorno > TOML > default. Las cuentas vienen de una sola
fuente: si hay variables ``MCP_ACCOUNT_<CAMPO>_<N>`` en el entorno, de ahí;
si no, del TOML. Nunca se mezclan, porque una cuenta a medio configurar es
peor que no tenerla.

``MCP_ACCOUNTS`` es opcional: solo sirve como comprobación cruzada de que
la lista cuadra con las cuentas que existen.

Todo valor mal escrito aborta el arranque. Un interruptor de escritura que
no se puede interpretar no puede quedarse en "apagado" sin que nadie se
entere.
"""

from __future__ import annotations

import logging
import os
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

logger = logging.getLogger("mcp_correo.config")

ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MIN_TOKEN_LENGTH = 16

#: Variable que enumera las cuentas configuradas por entorno. Opcional:
#: solo sirve como comprobación cruzada.
ACCOUNTS_LIST = "MCP_ACCOUNTS"
#: Prefijo de las variables de una cuenta: MCP_ACCOUNT_<CAMPO>_<N>
ACCOUNT_PREFIX = "MCP_ACCOUNT_"

#: Dónde se busca el accounts.toml, por orden. El entrypoint del contenedor
#: usa las dos primeras; la última es la del despliegue con systemd.
_TOML_PATHS = ("accounts.toml", "/etc/mcp-correo/accounts.toml", "/config/accounts.toml")

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

#: Campos que admite una cuenta en el TOML.
_ACCOUNT_FIELDS: tuple[str, ...] = (
    "label",
    "imap_host",
    "imap_port",
    "imap_ssl",
    "smtp_host",
    "smtp_port",
    "smtp_security",
    "username",
    "password",
    "password_env",
    "drafts_folder",
    "sent_folder",
    "trash_folder",
    "allow_send",
    "allow_mark",
    "allow_delete",
    "allow_drafts",
)

_ACCOUNT_KEYS = frozenset(_ACCOUNT_FIELDS)

#: Campo de cuenta -> base del nombre de su variable. El índice va al final:
#: MCP_ACCOUNT_<BASE>_<N>. El 1 es la primera cuenta, el 2 la segunda.
_ACCOUNT_ENV_FIELDS: dict[str, str] = {
    "name": "NAME",
    "label": "LABEL",
    "inbox_type": "INBOX_TYPE",
    "inbox_host": "INBOX_HOST",
    "inbox_port": "INBOX_PORT",
    "inbox_use_ssl": "INBOX_USE_SSL",
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_use_ssl": "SMTP_USE_SSL",
    "username": "USERNAME",
    "password": "PASSWORD",
    "password_env": "PASSWORD_ENV",
    "drafts_folder": "DRAFTS_FOLDER",
    "sent_folder": "SENT_FOLDER",
    "trash_folder": "TRASH_FOLDER",
    "allow_send": "ALLOW_SEND",
    "allow_mark": "ALLOW_MARK",
    "allow_delete": "ALLOW_DELETE",
    "allow_drafts": "ALLOW_DRAFTS",
    "bearer": "BEARER",
}

_ACCOUNT_ENV_BASES = frozenset(_ACCOUNT_ENV_FIELDS.values())

#: MCP_ACCOUNT_<BASE>_<N>. La base puede llevar guion bajo, así que el
#: índice es lo que va al final.
_ACCOUNT_VAR = re.compile(r"^MCP_ACCOUNT_(?P<base>[A-Z_]+)_(?P<index>\d+)$")

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

#: Clave de ``[server]`` -> variable de entorno que la sobrescribe.
_SERVER_ENV: dict[str, str] = {
    "public_host": "MCP_PUBLIC_HOST",
    "bind_host": "MCP_BIND_HOST",
    "bind_port": "MCP_BIND_PORT",
    "max_results": "MCP_MAX_RESULTS",
    "max_chars": "MCP_MAX_CHARS",
    "max_attachment_bytes": "MCP_MAX_ATTACHMENT_BYTES",
    "max_message_bytes": "MCP_MAX_MESSAGE_BYTES",
    "imap_timeout": "MCP_IMAP_TIMEOUT",
    "sent_scan_limit": "MCP_SENT_SCAN_LIMIT",
    "enable_drafts": "MCP_ENABLE_DRAFTS",
    "enable_send": "MCP_ENABLE_SEND",
    "enable_mark": "MCP_ENABLE_MARK",
    "enable_delete": "MCP_ENABLE_DELETE",
    "confirm_ttl_seconds": "MCP_CONFIRM_TTL_SECONDS",
    "max_recipients": "MCP_MAX_RECIPIENTS",
    "max_sends_per_day": "MCP_MAX_SENDS_PER_DAY",
    "max_delete_per_call": "MCP_MAX_DELETE_PER_CALL",
    "max_mark_per_call": "MCP_MAX_MARK_PER_CALL",
    "smtp_timeout": "MCP_SMTP_TIMEOUT",
    "smtp_security": "MCP_SMTP_SECURITY",
    "allowed_recipient_domains": "MCP_ALLOWED_RECIPIENT_DOMAINS",
    "allowed_attachment_types": "MCP_ALLOWED_ATTACHMENT_TYPES",
    "allowed_hosts": "MCP_ALLOWED_HOSTS",
    "allowed_origins": "MCP_ALLOWED_ORIGINS",
    "audit_log": "MCP_AUDIT_LOG",
}

LOCAL_BIND_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

_BOOL_TRUE = ("true", "1")
_BOOL_FALSE = ("false", "0")


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
    #: "env" o "toml": de dónde salieron las cuentas.
    config_source: str = "toml"


@dataclass(frozen=True)
class Account:
    """Cuenta IMAP. `password` y `bearer` no aparecen en repr ni en trazas."""

    key: str
    label: str
    imap_host: str
    imap_port: int
    username: str
    password: str = field(repr=False, compare=False)
    bearer: str = field(repr=False, compare=False, default="")
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
    #: Número de cuenta en las variables de entorno. 0 si viene del TOML.
    index: int = 0


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


def resolve_config_path() -> Path | None:
    """Ruta del TOML, o None si la configuración va solo por entorno."""
    env_path = os.environ.get("MCP_CONFIG")
    if env_path:
        path = Path(env_path)
        if path.is_file():
            return path
        if _env_account_indexes():
            logger.warning(
                "MCP_CONFIG apunta a %s, que no existe. La configuración va por entorno.", path
            )
            return None
        raise SystemExit(
            f"No se encuentra la configuración: {path}. "
            "Si las cuentas van por entorno, no hace falta ese fichero."
        )
    for candidate in _TOML_PATHS:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def load_config(path: Path | None = None) -> tuple[ServerSettings, dict[str, Account]]:
    """Carga servidor y cuentas. Entorno primero, TOML como alternativa."""
    config_path = path if path is not None else resolve_config_path()
    server_raw, accounts_raw = _read_toml(config_path)
    settings = _server_settings(server_raw)
    env_accounts = _accounts_from_env(settings)
    if env_accounts:
        accounts = env_accounts
        settings = replace(settings, config_source="env")
        if accounts_raw:
            logger.warning(
                "Hay cuentas en el accounts.toml y en el entorno. Mandan las del entorno."
            )
    else:
        accounts = {key: _account(str(key), value) for key, value in accounts_raw.items()}
        settings = replace(settings, config_source="toml")
    if not accounts:
        raise SystemExit(
            "No hay cuentas. Define las variables de cada cuenta "
            "(MCP_ACCOUNT_<CAMPO>_<N>), o añade una sección [accounts.<clave>] "
            "al accounts.toml."
        )
    return settings, accounts


def ensure_local_bind(bind_host: str) -> None:
    if bind_host in LOCAL_BIND_HOSTS:
        return
    if os.environ.get("MCP_ALLOW_NONLOCAL_BIND") == "1":
        return
    raise SystemExit(
        f"bind_host {bind_host!r} no es loopback. El proceso escucha en 127.0.0.1, "
        "::1 o localhost. Dentro del contenedor define MCP_ALLOW_NONLOCAL_BIND=1 "
        "para oír en 0.0.0.0 y publica el puerto solo en 127.0.0.1, con TLS en el proxy."
    )


# --- Lectura del TOML -------------------------------------------------------


def _read_toml(path: Path | None) -> tuple[dict, dict]:
    """Lee el TOML si lo hay. Sin TOML, la configuración puede venir del entorno."""
    if path is None:
        return {}, {}
    if not path.is_file():
        raise SystemExit(f"No se encuentra la configuración: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"TOML inválido en {path}: {exc}") from None

    if not isinstance(data, dict):
        raise SystemExit("La configuración debe ser una tabla TOML")

    server_raw = data.get("server") or {}
    accounts_raw = data.get("accounts") or {}
    if not isinstance(server_raw, dict) or not isinstance(accounts_raw, dict):
        raise SystemExit("Las secciones [server] y [accounts] deben ser tablas")

    _reject_unknown("server", server_raw, _SERVER_KEYS)
    return server_raw, accounts_raw


# --- Lectura del entorno -----------------------------------------------------


def _env_text(name: str) -> str | None:
    """Valor recortado de una variable, o None si no existe o está vacía."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    text = raw.strip()
    return text or None


def _env_bool(name: str) -> bool | None:
    value = _env_text(name)
    if value is None:
        return None
    return _parse_bool(value, name)


def _env_int(name: str) -> int | None:
    value = _env_text(name)
    if value is None:
        return None
    return _parse_int(value, name)


def _env_float(name: str) -> float | None:
    value = _env_text(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        raise SystemExit(f"{name} debe ser un número (no {value!r})") from None


def _env_csv(name: str) -> tuple[str, ...] | None:
    value = _env_text(name)
    if value is None:
        return None
    items = tuple(part.strip() for part in value.split(",") if part.strip())
    return items or None


def _parse_bool(value: str, name: str) -> bool:
    """Solo true, false, 1 y 0. Nada más puede encender un interruptor."""
    low = value.strip().lower()
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False
    raise SystemExit(
        f"{name} debe ser true, false, 1 o 0 (no {value!r}). "
        "Un interruptor mal escrito no puede quedar ambiguo."
    )


def _parse_int(value: str, name: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        raise SystemExit(f"{name} debe ser un entero (no {value!r})") from None


def _pick(env_value, toml_value, default):  # type: ignore[no-untyped-def]
    """Entorno > TOML > default."""
    if env_value is not None:
        return env_value
    if toml_value is not None:
        return toml_value
    return default


# --- Servidor ----------------------------------------------------------------


def _server_settings(raw: dict) -> ServerSettings:
    env_public = _env_text("MCP_PUBLIC_HOST") or ""
    public_host = env_public or str(raw.get("public_host") or "127.0.0.1")
    bind_host = str(_pick(_env_text("MCP_BIND_HOST"), raw.get("bind_host"), "127.0.0.1"))
    bind_port = _port(_pick(_env_int("MCP_BIND_PORT"), raw.get("bind_port"), 8765), "bind_port")
    max_results = _positive_int(
        _pick(_env_int("MCP_MAX_RESULTS"), raw.get("max_results"), 100), "max_results"
    )
    max_chars = _positive_int(
        _pick(_env_int("MCP_MAX_CHARS"), raw.get("max_chars"), 20_000), "max_chars"
    )
    max_attachment_bytes = _positive_int(
        _pick(_env_int("MCP_MAX_ATTACHMENT_BYTES"), raw.get("max_attachment_bytes"), 5_000_000),
        "max_attachment_bytes",
    )
    max_message_bytes = _positive_int(
        _pick(_env_int("MCP_MAX_MESSAGE_BYTES"), raw.get("max_message_bytes"), 15_000_000),
        "max_message_bytes",
    )
    imap_timeout = float(_pick(_env_float("MCP_IMAP_TIMEOUT"), raw.get("imap_timeout"), 20))
    if imap_timeout <= 0:
        raise SystemExit("imap_timeout debe ser mayor que 0")
    sent_scan_limit = _positive_int(
        _pick(_env_int("MCP_SENT_SCAN_LIMIT"), raw.get("sent_scan_limit"), 300), "sent_scan_limit"
    )
    attachment_types = _str_tuple(
        _pick(_env_csv("MCP_ALLOWED_ATTACHMENT_TYPES"), raw.get("allowed_attachment_types"), None),
        DEFAULT_ATTACHMENT_TYPES,
    )
    hosts = _hosts_from_env(env_public, public_host, raw)
    if env_public and env_public not in hosts:
        # La lista explícita ha dejado fuera al host público. Con un túnel,
        # el Host que llega es el hostname público: esas peticiones reciben
        # un 421 y parece un problema del túnel o del proxy.
        logger.warning(
            "MCP_PUBLIC_HOST (%s) no está en allowed_hosts (%s). Las peticiones con "
            "esa cabecera Host recibirán un 421. MCP_ALLOWED_HOSTS sustituye a la lista "
            "derivada de MCP_PUBLIC_HOST: incluye el dominio o quita la variable.",
            env_public,
            ", ".join(hosts),
        )
    origins = _origins_from_env(env_public, public_host, raw)
    audit_log = str(_pick(_env_text("MCP_AUDIT_LOG"), raw.get("audit_log"), "audit.jsonl"))
    smtp_timeout = float(_pick(_env_float("MCP_SMTP_TIMEOUT"), raw.get("smtp_timeout"), 30))
    if smtp_timeout <= 0:
        raise SystemExit("smtp_timeout debe ser mayor que 0")
    smtp_security = _smtp_security(
        _pick(_env_text("MCP_SMTP_SECURITY"), raw.get("smtp_security"), "ssl"), "smtp_security"
    )
    domains = _domains(
        _pick(
            _env_csv("MCP_ALLOWED_RECIPIENT_DOMAINS"),
            raw.get("allowed_recipient_domains"),
            None,
        )
    )
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
        enable_drafts=_switch("MCP_ENABLE_DRAFTS", raw, "enable_drafts"),
        enable_send=_switch("MCP_ENABLE_SEND", raw, "enable_send"),
        enable_mark=_switch("MCP_ENABLE_MARK", raw, "enable_mark"),
        enable_delete=_switch("MCP_ENABLE_DELETE", raw, "enable_delete"),
        confirm_ttl_seconds=_positive_int(
            _pick(_env_int("MCP_CONFIRM_TTL_SECONDS"), raw.get("confirm_ttl_seconds"), 600),
            "confirm_ttl_seconds",
        ),
        max_recipients=_positive_int(
            _pick(_env_int("MCP_MAX_RECIPIENTS"), raw.get("max_recipients"), 10), "max_recipients"
        ),
        max_sends_per_day=_positive_int(
            _pick(_env_int("MCP_MAX_SENDS_PER_DAY"), raw.get("max_sends_per_day"), 30),
            "max_sends_per_day",
        ),
        max_delete_per_call=_positive_int(
            _pick(_env_int("MCP_MAX_DELETE_PER_CALL"), raw.get("max_delete_per_call"), 20),
            "max_delete_per_call",
        ),
        max_mark_per_call=_positive_int(
            _pick(_env_int("MCP_MAX_MARK_PER_CALL"), raw.get("max_mark_per_call"), 50),
            "max_mark_per_call",
        ),
        smtp_timeout=smtp_timeout,
        smtp_security=smtp_security,
        allowed_recipient_domains=domains,
    )


def _switch(env_name: str, raw: dict, toml_key: str) -> bool:
    """Interruptor: entorno > TOML > apagado. Un texto no lo enciende."""
    from_toml = _as_bool(raw.get(toml_key), toml_key)
    return bool(_pick(_env_bool(env_name), from_toml, False))


def _hosts_from_env(env_public: str, public_host: str, raw: dict) -> tuple[str, ...]:
    explicit = _env_csv("MCP_ALLOWED_HOSTS")
    if explicit is not None:
        return explicit
    if env_public:
        return _default_hosts(public_host)
    return _str_tuple(raw.get("allowed_hosts"), _default_hosts(public_host))


def _origins_from_env(env_public: str, public_host: str, raw: dict) -> tuple[str, ...]:
    explicit = _env_csv("MCP_ALLOWED_ORIGINS")
    if explicit is not None:
        return explicit
    if env_public:
        return _default_origins(public_host)
    return _str_tuple(raw.get("allowed_origins"), _default_origins(public_host))


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


# --- Cuentas por entorno -----------------------------------------------------
#
# Las cuentas se declaran por índice: MCP_ACCOUNT_<CAMPO>_<N>. La 1 es la
# primera, la 2 la segunda. El índice va al final para que el prefijo de los
# campos sea el mismo en todas las cuentas y una variable por campo.


def _accounts_from_env(settings: ServerSettings) -> dict[str, Account]:
    """Cuentas declaradas con MCP_ACCOUNT_<CAMPO>_<N>."""
    indexes = _account_indexes()
    if not indexes:
        return {}
    accounts: dict[str, Account] = {}
    for index in indexes:
        account = _account_from_env(index, settings)
        if account.key in accounts:
            raise SystemExit(
                f"Dos cuentas comparten el nombre {account.key!r}. "
                "Distingue una con MCP_ACCOUNT_NAME_<N>."
            )
        accounts[account.key] = account
    _check_bearers(accounts)
    return accounts


def _env_account_indexes() -> list[int]:
    """Índices de cuenta hallados en el entorno, sin validarlos.

    Sirve para saber si hay configuración por entorno sin abortar: es
    la pregunta que hace `resolve_config_path` antes de load_config.
    """
    found: set[int] = set()
    for name in os.environ:
        if not name.startswith(ACCOUNT_PREFIX):
            continue
        match = _ACCOUNT_VAR.match(name)
        if match is not None:
            found.add(int(match.group("index")))
    return sorted(found)


def _account_indexes() -> list[int]:
    """Índices declarados en el entorno, y los que MCP_ACCOUNTS impone."""
    declared: dict[int, set[str]] = {}
    for name in os.environ:
        if not name.startswith(ACCOUNT_PREFIX):
            continue
        match = _ACCOUNT_VAR.match(name)
        if match is None:
            raise SystemExit(
                f"Variable de cuenta desconocida: {name}. "
                f"El formato es {ACCOUNT_PREFIX}<CAMPO>_<N>, con N el número de cuenta. "
                "Campos: " + ", ".join(sorted(_ACCOUNT_ENV_BASES)) + "."
            )
        base = match.group("base")
        if base not in _ACCOUNT_ENV_BASES:
            raise SystemExit(
                f"Variable de cuenta desconocida: {name}. "
                f"Campos: {', '.join(sorted(_ACCOUNT_ENV_BASES))}."
            )
        declared.setdefault(int(match.group("index")), set()).add(base)

    listed = _listed_account_indexes()
    if listed is None:
        return sorted(declared)

    unknown = sorted(set(declared) - set(listed))
    if unknown:
        raise SystemExit(
            f"{ACCOUNTS_LIST} no lista la cuenta {', '.join(str(i) for i in unknown)}, "
            "que sí tiene variables en el entorno. Añádela a la lista o borra sus variables."
        )
    missing = [index for index in listed if index not in declared]
    if missing:
        raise SystemExit(
            f"{ACCOUNTS_LIST} lista la cuenta {', '.join(str(i) for i in missing)}, "
            "que no tiene ninguna variable."
        )
    return listed


def _listed_account_indexes() -> list[int] | None:
    """Los índices que MCP_ACCOUNTS impone, o None si no está definida."""
    raw = _env_text(ACCOUNTS_LIST)
    if raw is None:
        return None
    indexes: list[int] = []
    for part in raw.split(","):
        text = part.strip()
        if not text:
            continue
        if not text.isdigit() or int(text) < 1:
            raise SystemExit(
                f"{ACCOUNTS_LIST} tiene un índice de cuenta inválido: {text!r}. "
                "Son números, empezando por 1."
            )
        index = int(text)
        if index in indexes:
            raise SystemExit(f"{ACCOUNTS_LIST} repite la cuenta {index}.")
        indexes.append(index)
    if not indexes:
        raise SystemExit(f"{ACCOUNTS_LIST} está definida pero no lista ninguna cuenta.")
    return indexes


def _account_from_env(index: int, settings: ServerSettings) -> Account:
    def var(field: str) -> str:
        return f"{ACCOUNT_PREFIX}{_ACCOUNT_ENV_FIELDS[field]}_{index}"

    def raw(field: str) -> str | None:
        return os.environ.get(var(field))

    def text(field: str) -> str | None:
        value = raw(field)
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def flag(field: str, default: bool) -> bool:
        value = text(field)
        if value is None:
            return default
        return _parse_bool(value, var(field))

    def number(field: str, default: int) -> int:
        value = text(field)
        if value is None:
            return default
        return _parse_int(value, var(field))

    inbox_type = (text("inbox_type") or "imap").lower()
    if inbox_type != "imap":
        raise SystemExit(f"{var('inbox_type')} debe ser imap. Este servidor solo habla IMAP.")
    username = text("username")
    if not username:
        raise SystemExit(f"La cuenta {index} necesita {var('username')}.")
    inbox_host = text("inbox_host")
    if not inbox_host:
        raise SystemExit(f"La cuenta {index} necesita {var('inbox_host')}.")

    # El modo SMTP de la cuenta solo se fija si la cuenta lo dice. Si no, manda
    # el global MCP_SMTP_SECURITY, y el puerto por defecto acompaña al modo.
    if text("smtp_use_ssl") is None:
        smtp_security = ""
    else:
        smtp_security = "ssl" if flag("smtp_use_ssl", True) else "starttls"
    effective_smtp = smtp_security or settings.smtp_security
    default_smtp_port = 465 if effective_smtp == "ssl" else 587

    key = text("name") or username
    bearer = text("bearer") or ""
    if bearer and len(bearer) < MIN_TOKEN_LENGTH:
        raise SystemExit(
            f"{var('bearer')} es demasiado corto (mínimo {MIN_TOKEN_LENGTH} caracteres). "
            "Genera uno con: openssl rand -base64 48"
        )

    return Account(
        key=key,
        label=text("label") or key,
        imap_host=inbox_host,
        imap_port=_port(number("inbox_port", 993), f"{var('inbox_port')}"),
        imap_ssl=flag("inbox_use_ssl", True),
        smtp_host=text("smtp_host") or inbox_host,
        smtp_port=_port(number("smtp_port", default_smtp_port), f"{var('smtp_port')}"),
        username=username,
        password=_account_password(index),
        bearer=bearer,
        drafts_folder=text("drafts_folder") or "Drafts",
        sent_folder=text("sent_folder") or "Sent",
        trash_folder=_optional_folder(text("trash_folder"), f"{var('trash_folder')}"),
        smtp_security=smtp_security,
        allow_send=flag("allow_send", False),
        allow_mark=flag("allow_mark", False),
        allow_delete=flag("allow_delete", False),
        allow_drafts=flag("allow_drafts", False),
        index=index,
    )


def _account_password(index: int) -> str:
    """La contraseña de una cuenta: directa, o el nombre de otra variable."""
    direct_name = f"{ACCOUNT_PREFIX}{_ACCOUNT_ENV_FIELDS['password']}_{index}"
    indirect_name = f"{ACCOUNT_PREFIX}{_ACCOUNT_ENV_FIELDS['password_env']}_{index}"
    direct = os.environ.get(direct_name)
    indirect = os.environ.get(indirect_name)
    if indirect is not None:
        indirect = indirect.strip() or None
    if direct is not None and not direct.strip():
        direct = None
    if direct and indirect:
        raise SystemExit(
            f"La cuenta {index} define {direct_name} y {indirect_name}. Usa solo una de las dos."
        )
    if indirect:
        if not ENV_NAME.fullmatch(indirect):
            raise SystemExit(f"{indirect_name} no es un nombre de variable válido.")
        if "PASSWORD" not in indirect.upper() and "PASS" not in indirect.upper():
            raise SystemExit(
                f"{indirect_name} debería ser el nombre de una variable "
                "(por ejemplo MAIL_PRINCIPAL_PASSWORD), no un secreto"
            )
        password = os.environ.get(indirect)
        if password is None or password == "":
            raise SystemExit(
                f"Falta la variable de entorno {indirect} para la cuenta {index}. "
                "El servidor no arranca con cuentas sin secreto."
            )
        return password
    if direct:
        return direct
    raise SystemExit(
        f"La cuenta {index} no tiene contraseña. Define {direct_name} "
        f"o {indirect_name} con el nombre de otra variable."
    )


def _check_bearers(accounts: dict[str, Account]) -> None:
    """Los Bearer por cuenta tienen que ser distintos entre sí y del global."""
    global_token = os.environ.get("MCP_BEARER_TOKEN", "").strip()
    seen: dict[str, str] = {}
    for key, account in accounts.items():
        if not account.bearer:
            continue
        if global_token and account.bearer == global_token:
            raise SystemExit(
                f"El bearer de la cuenta {key} es el mismo que MCP_BEARER_TOKEN. "
                "Si son iguales, la ruta por cuenta no aísla nada. Usa otro."
            )
        if account.bearer in seen:
            raise SystemExit(
                f"Las cuentas {seen[account.bearer]} y {key} comparten el mismo bearer. "
                "Cada cuenta necesita el suyo."
            )
        seen[account.bearer] = key


# --- Cuentas por TOML --------------------------------------------------------


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
            "(por ejemplo MAIL_PRINCIPAL_PASSWORD), no un secreto"
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


#: Capacidad de escritura -> (interruptor global, permiso de cuenta, etiqueta).
#: La usa `write_capabilities` para saber qué tools registrar, y `mail.mutate`
#: para comprobar cada operación. Vive aquí para que no puedan discrepar.
WRITE_GATES: dict[str, tuple[str, str, str]] = {
    "send": ("enable_send", "allow_send", "El envío"),
    "mark": ("enable_mark", "allow_mark", "Marcar mensajes"),
    "delete": ("enable_delete", "allow_delete", "La eliminación"),
    "drafts": ("enable_drafts", "allow_drafts", "Los borradores"),
}

#: Longitud máxima de un nombre de carpeta. La comparten la validación del
#: TOML y la del IMAP.
MAX_FOLDER_LENGTH = 200


def write_capabilities(settings: ServerSettings, accounts: dict[str, Account]) -> dict[str, bool]:
    """Una tool de escritura existe solo si el interruptor global y alguna cuenta lo permiten."""
    return {
        name: getattr(settings, global_name)
        and any(getattr(account, account_name) for account in accounts.values())
        for name, (global_name, account_name, _label) in WRITE_GATES.items()
    }


# --- Validadores -------------------------------------------------------------


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
    if (
        not isinstance(value, str)
        or len(value) > MAX_FOLDER_LENGTH
        or any(char in value for char in "\r\n\x00")
    ):
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


def _str_tuple(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    raise SystemExit("Se esperaba una lista de textos en la configuración")
