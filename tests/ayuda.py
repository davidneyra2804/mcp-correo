"""Ayudantes para las pruebas: ajustes del servidor y cuentas de mentira.

Las cuentas ya no se configuran por variables de entorno ni por ficheros:
viven en la base de datos y las da de alta el panel. Para las pruebas que
necesitan cuentas en memoria, se construyen aquí.
"""

from __future__ import annotations

from config import Account, ServerSettings, load_server_settings


def ajustes() -> ServerSettings:
    """Los ajustes del servidor tal como los deja el entorno de pruebas."""
    return load_server_settings()


def cuenta(
    key: str,
    *,
    username: str | None = None,
    imap_host: str = "imap.corp.example.com",
    password: str = "clave-ficticia",
    bearer: str = "",
    index: int = 0,
    domain: str = "",
    **extra: object,
) -> Account:
    """Una cuenta para las pruebas, con los valores por defecto."""
    return Account(
        key=key,
        label=key,
        imap_host=imap_host,
        imap_port=993,
        username=username or key,
        password=password,
        bearer=bearer,
        index=index,
        domain=domain,
        **extra,  # type: ignore[arg-type]
    )
