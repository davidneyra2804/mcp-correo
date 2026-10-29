"""Carga de configuración. Todo sale del entorno.

El servidor se configura entero con variables ``MCP_*``: una variable por
campo, sin listas que mantener. Los dominios, las cuentas, sus contraseñas y
sus credenciales **no** se configuran aquí: viven en la base de datos y se
gestionan desde el panel de control.

Todo valor mal escrito aborta el arranque. Un interruptor de escritura que
no se puede interpretar no puede quedarse en "apagado" sin que nadie se
entere.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger("mcp_correo.config")

ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MIN_TOKEN_LENGTH = 16

#: Las variables del panel. El panel y la base de datos siempre están: lo
#: que se puede cambiar es dónde viven y cómo se les llama.
DASHBOARD_ENV: tuple[str, ...] = (
    "MCP_DASHBOARD_DB",
    "MCP_DASHBOARD_KEY",
    "MCP_DASHBOARD_TOKEN",
    "MCP_DASHBOARD_BIND_HOST",
    "MCP_DASHBOARD_BIND_PORT",
)
#: Dónde está la base de datos si no se dice otra cosa.
DEFAULT_DASHBOARD_DB = "cuentas.db"

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

#: Clave de configuración del servidor -> variable de entorno que la define.
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
    "enable_direct_send": "MCP_ENABLE_DIRECT_SEND",
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
    #: Envío directo: una sola llamada, sin confirmation_id y sin
    #: confirmación humana por mensaje. Apagado por defecto.
    enable_direct_send: bool = False
    confirm_ttl_seconds: int = 600
    max_recipients: int = 10
    max_sends_per_day: int = 30
    max_delete_per_call: int = 20
    max_mark_per_call: int = 50
    smtp_timeout: float = 30
    smtp_security: str = "ssl"
    allowed_recipient_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class DashboardSettings:
    """Los ajustes del panel. Siempre están: es la forma de gestionar las cuentas."""

    enabled: bool = True
    db_path: str = ""
    key: str = ""
    token: str = ""
    bind_host: str = "127.0.0.1"
    bind_port: int = 8766


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
    #: Nombre visible en los correos salientes. Vacío = solo la dirección.
    sender: str = ""
    imap_ssl: bool = True
    smtp_host: str = ""
    smtp_port: int = 465
    drafts_folder: str = "Drafts"
    sent_folder: str = "Sent"
    trash_folder: str = ""
    smtp_security: str = ""
    #: Permiso de escritura por cuenta. None = no definido, y entonces
    #: hereda el interruptor global. True/False = permiso explícito.
    allow_send: bool | None = None
    allow_mark: bool | None = None
    allow_delete: bool | None = None
    allow_drafts: bool | None = None
    #: Permiso de envío directo. None = no definido, y entonces hereda
    #: el interruptor global.
    allow_direct_send: bool | None = None
    #: Dominio al que pertenece. Vacío si no hay.
    domain: str = ""
    #: Identificador numérico de la cuenta en la base de datos. 0 si no lo
    #: tiene: las rutas por número solo valen para las cuentas del panel.
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


def load_server_settings() -> ServerSettings:
    """Carga los ajustes del servidor desde el entorno.

    Las cuentas no se cargan aquí: las da de alta el panel, y la base de
    datos empieza vacía. No es un error de arranque.
    """
    return _server_settings()


def load_dashboard_settings() -> DashboardSettings:
    """Los ajustes del panel.

    El panel y la base de datos **siempre están**: son la forma de gestionar
    las cuentas. Lo que cambia es dónde vive el fichero y cómo se llama la
    credencial.

    ``MCP_DASHBOARD_KEY`` y ``MCP_DASHBOARD_TOKEN`` son obligatorias. Sin la
    clave no se pueden descifrar las contraseñas, y sin el token no se puede
    entrar. El proceso para y dice cuál falta: no se arranca a medias.
    """
    db_path = _env_text("MCP_DASHBOARD_DB") or DEFAULT_DASHBOARD_DB
    key = _env_text("MCP_DASHBOARD_KEY")
    if not key:
        raise SystemExit(
            "Falta MCP_DASHBOARD_KEY: es la clave con la que se cifran las contraseñas de las "
            "cuentas. No está en la base de datos, así que hay que guardarla. "
            "Se genera con: openssl rand -base64 48"
        )
    if len(key) < MIN_TOKEN_LENGTH:
        raise SystemExit(
            f"MCP_DASHBOARD_KEY es demasiado corta (mínimo {MIN_TOKEN_LENGTH} caracteres). "
            "Se genera con: openssl rand -base64 48"
        )
    token = _env_text("MCP_DASHBOARD_TOKEN")
    if not token:
        raise SystemExit(
            "Falta MCP_DASHBOARD_TOKEN: es la credencial de acceso al panel. "
            "Se genera con: openssl rand -base64 48"
        )
    if len(token) < MIN_TOKEN_LENGTH:
        raise SystemExit(
            f"MCP_DASHBOARD_TOKEN es demasiado corto (mínimo {MIN_TOKEN_LENGTH} caracteres). "
            "Se genera con: openssl rand -base64 48"
        )
    global_token = os.environ.get("MCP_BEARER_TOKEN", "").strip()
    if global_token and token == global_token:
        raise SystemExit(
            "MCP_DASHBOARD_TOKEN es el mismo que MCP_BEARER_TOKEN. Son dos superficies "
            "distintas: el panel no puede abrirse con el token del MCP."
        )
    bind_host = _env_text("MCP_DASHBOARD_BIND_HOST") or "127.0.0.1"
    bind_port = _port(_env_int_or("MCP_DASHBOARD_BIND_PORT", 8766), "MCP_DASHBOARD_BIND_PORT")
    ensure_local_bind(bind_host)
    return DashboardSettings(
        enabled=True,
        db_path=db_path,
        key=key,
        token=token,
        bind_host=bind_host,
        bind_port=bind_port,
    )


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


def _env_int_or(name: str, default: int) -> int:
    """El entero de la variable, o el default si no está definida.

    Un `0` explícito no es "sin definir": llega al validador y se rechaza.
    """
    value = _env_int(name)
    return default if value is None else value


def _env_float_or(name: str, default: float) -> float:
    """El float de la variable, o el default si no está definida."""
    value = _env_float(name)
    return default if value is None else value


# --- Servidor ----------------------------------------------------------------


def _server_settings() -> ServerSettings:
    env_public = _env_text("MCP_PUBLIC_HOST") or ""
    public_host = env_public or "127.0.0.1"
    bind_host = _env_text("MCP_BIND_HOST") or "127.0.0.1"
    bind_port = _port(_env_int_or("MCP_BIND_PORT", 8765), "MCP_BIND_PORT")
    max_results = _positive_int(_env_int_or("MCP_MAX_RESULTS", 100), "MCP_MAX_RESULTS")
    max_chars = _positive_int(_env_int_or("MCP_MAX_CHARS", 20_000), "MCP_MAX_CHARS")
    max_attachment_bytes = _positive_int(
        _env_int_or("MCP_MAX_ATTACHMENT_BYTES", 5_000_000), "MCP_MAX_ATTACHMENT_BYTES"
    )
    max_message_bytes = _positive_int(
        _env_int_or("MCP_MAX_MESSAGE_BYTES", 15_000_000), "MCP_MAX_MESSAGE_BYTES"
    )
    imap_timeout = _env_float_or("MCP_IMAP_TIMEOUT", 20)
    if imap_timeout <= 0:
        raise SystemExit("MCP_IMAP_TIMEOUT debe ser mayor que 0")
    sent_scan_limit = _positive_int(_env_int_or("MCP_SENT_SCAN_LIMIT", 300), "MCP_SENT_SCAN_LIMIT")
    attachment_types = _str_tuple(
        _env_csv("MCP_ALLOWED_ATTACHMENT_TYPES"), DEFAULT_ATTACHMENT_TYPES
    )
    hosts = _hosts_from_env(env_public, public_host)
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
    origins = _origins_from_env(env_public, public_host)
    audit_log = _env_text("MCP_AUDIT_LOG") or "audit.jsonl"
    smtp_timeout = _env_float_or("MCP_SMTP_TIMEOUT", 30)
    if smtp_timeout <= 0:
        raise SystemExit("MCP_SMTP_TIMEOUT debe ser mayor que 0")
    smtp_security = _smtp_security(_env_text("MCP_SMTP_SECURITY") or "ssl", "MCP_SMTP_SECURITY")
    domains = _domains(_env_csv("MCP_ALLOWED_RECIPIENT_DOMAINS"))
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
        enable_drafts=_switch("MCP_ENABLE_DRAFTS"),
        enable_send=_switch("MCP_ENABLE_SEND"),
        enable_mark=_switch("MCP_ENABLE_MARK"),
        enable_delete=_switch("MCP_ENABLE_DELETE"),
        enable_direct_send=_switch("MCP_ENABLE_DIRECT_SEND"),
        confirm_ttl_seconds=_positive_int(
            _env_int_or("MCP_CONFIRM_TTL_SECONDS", 600), "MCP_CONFIRM_TTL_SECONDS"
        ),
        max_recipients=_positive_int(_env_int_or("MCP_MAX_RECIPIENTS", 10), "MCP_MAX_RECIPIENTS"),
        max_sends_per_day=_positive_int(
            _env_int_or("MCP_MAX_SENDS_PER_DAY", 30), "MCP_MAX_SENDS_PER_DAY"
        ),
        max_delete_per_call=_positive_int(
            _env_int_or("MCP_MAX_DELETE_PER_CALL", 20), "MCP_MAX_DELETE_PER_CALL"
        ),
        max_mark_per_call=_positive_int(
            _env_int_or("MCP_MAX_MARK_PER_CALL", 50), "MCP_MAX_MARK_PER_CALL"
        ),
        smtp_timeout=smtp_timeout,
        smtp_security=smtp_security,
        allowed_recipient_domains=domains,
    )


def _switch(env_name: str) -> bool:
    """Interruptor global. Apagado por defecto; un texto no lo enciende."""
    return bool(_env_bool(env_name))


def _hosts_from_env(env_public: str, public_host: str) -> tuple[str, ...]:
    explicit = _env_csv("MCP_ALLOWED_HOSTS")
    if explicit is not None:
        return explicit
    return _default_hosts(public_host)


def _origins_from_env(env_public: str, public_host: str) -> tuple[str, ...]:
    explicit = _env_csv("MCP_ALLOWED_ORIGINS")
    if explicit is not None:
        return explicit
    return _default_origins(public_host)


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


#: Capacidad de escritura -> (interruptor global, permiso de cuenta, etiqueta
#: corta, etiqueta larga). La usa `write_capabilities` para saber qué tools
#: registrar, y `mail.mutate` para comprobar cada operación. Vive aquí para
#: que no puedan discrepar.
WRITE_GATES: dict[str, tuple[str, str, str, str]] = {
    "send": ("enable_send", "allow_send", "envío", "El envío"),
    "mark": ("enable_mark", "allow_mark", "marcado", "Marcar mensajes"),
    "delete": ("enable_delete", "allow_delete", "borrado", "La eliminación"),
    "drafts": ("enable_drafts", "allow_drafts", "borradores", "Los borradores"),
    # El envío directo es una capacidad aparte: no hereda de `send`. Es
    # opt-in, y una cuenta que lo tiene permitido puede enviar sin pasar
    # por la preparación con confirmation_id.
    "direct_send": (
        "enable_direct_send",
        "allow_direct_send",
        "envío directo",
        "El envío directo",
    ),
}

#: Longitud máxima de un nombre de carpeta. La comparten la validación del
#: panel y la del IMAP.
MAX_FOLDER_LENGTH = 200


def resolve_permission(account_value: bool | None, domain_value: bool | None) -> bool | None:
    """Qué valor gana entre la cuenta y el dominio.

    La cuenta manda sobre el dominio. Si ninguna de las dos lo dice, None:
    hereda el interruptor global.

    La regla vive aquí, y no en la base de datos, porque la usan tanto el
    cargador de las cuentas como el resto del servidor. Es la misma cadena
    de siempre con un nivel más: global, dominio, cuenta.
    """
    if account_value is not None:
        return account_value
    return domain_value


def account_allows(account: Account, capability: str, settings: ServerSettings) -> bool:
    """Si una cuenta puede usar una capacidad de escritura.

    El interruptor global manda y además es el valor por defecto:

    - global apagado -> nada, ni con permisos por cuenta.
    - global encendido y la cuenta no dice nada -> la cuenta lo hereda.
    - global encendido y la cuenta lo dice -> manda la cuenta.

    Así, encender una capacidad es una línea, y el permiso por cuenta es un
    override opcional.
    """
    global_name, account_name, _corta, _larga = WRITE_GATES[capability]
    if not getattr(settings, global_name):
        return False
    valor = getattr(account, account_name)
    if valor is None:
        return True
    return bool(valor)


def write_capabilities(
    settings: ServerSettings, accounts: dict[str, Account], *, dynamic: bool = False
) -> dict[str, bool]:
    """Una tool de escritura existe solo si alguna cuenta puede usarla.

    Con cuentas dinámicas (el panel) el conjunto de cuentas cambia con el
    tiempo, y la lista de tools se fija al arrancar. En ese modo se
    registra la tool si el interruptor global está encendido, y el permiso
    por cuenta se comprueba en cada llamada, que es donde se comprueba de
    todos modos. Lo que no cambia nunca es quién puede escribir: eso lo
    decide ``account_allows``.
    """
    if dynamic:
        return {
            name: bool(getattr(settings, global_name))
            for name, (global_name, _cuenta, _corta, _larga) in WRITE_GATES.items()
        }
    return {
        name: any(account_allows(account, name, settings) for account in accounts.values())
        for name in WRITE_GATES
    }


def write_capabilities_detail(
    settings: ServerSettings, accounts: dict[str, Account]
) -> tuple[list[str], list[str]]:
    """Qué capacidades hay, y por qué faltan las demás.

    Cada capacidad dice solo lo que falta. Decir "necesita X e Y" cuando X ya
    está puesto hace dudar de lo que hay que tocar.
    """
    activas: list[str] = []
    motivos: list[str] = []
    for name, (global_name, _account_name, corta, _larga) in WRITE_GATES.items():
        variable_global = "MCP_" + global_name.upper()
        if not getattr(settings, global_name):
            motivos.append(f"{corta}: falta {variable_global}=true")
            continue
        if not any(account_allows(account, name, settings) for account in accounts.values()):
            # El global está bien: lo que falla es que todas las cuentas lo
            # tienen puesto en false.
            motivos.append(f"{corta}: ninguna cuenta lo permite; revisa los permisos en el panel")
            continue
        activas.append(corta)
    return activas, motivos


# --- Validadores -------------------------------------------------------------


def _smtp_security(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise SystemExit(f"{field_name} debe ser ssl o starttls")
    text = value.strip().lower()
    if text not in {"ssl", "starttls"}:
        raise SystemExit(f"{field_name} debe ser ssl o starttls")
    return text


def _display_name(value: object, field_name: str) -> str:
    """El nombre visible de una cuenta en los correos salientes.

    Acaba en una cabecera, así que un salto de línea dejaría inyectar
    cabeceras (un Bcc de verdad, por ejemplo). Se rechaza al cargar la
    configuración, no ya al enviar.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SystemExit(f"{field_name} tiene que ser un texto")
    name = value.strip()
    if not name:
        return ""
    if any(char in name for char in "\r\n\x00"):
        raise SystemExit(
            f"{field_name} no puede llevar saltos de línea ni caracteres nulos: "
            "acaba en una cabecera de correo."
        )
    if len(name) > 100:
        raise SystemExit(f"{field_name} es demasiado largo (máximo 100 caracteres).")
    return name


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
