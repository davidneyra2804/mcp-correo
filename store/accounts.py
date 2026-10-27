"""La fuente de cuentas: de dónde salen y cuándo se recargan.

El servidor no guarda el conjunto de cuentas en un diccionario: lo pide a
una fuente. Hay dos:

- ``StaticAccounts``, la del entorno o del ``accounts.toml``. No cambia.
- ``DatabaseAccounts``, la del panel. Se recarga cuando alguien toca el
  panel, sin reiniciar el servidor.

La fuente entrega una ``AccountSnapshot``: las cuentas, los dominios y la
versión con la que se leyeron. La versión sirve para saber si lo que se
tiene en memoria sigue siendo bueno, sin volver a preguntar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from config import Account


@dataclass(frozen=True)
class DomainInfo:
    """Un dominio: un grupo de cuentas, con su credencial y sus defaults."""

    name: str
    label: str = ""
    #: Si es el dominio por defecto, el que abre la ruta /mcp.
    is_default: bool = False
    #: Credencial propia del dominio. Vacía = no tiene.
    bearer: str = ""
    #: Claves de las cuentas del dominio.
    accounts: tuple[str, ...] = ()


@dataclass(frozen=True)
class AccountSnapshot:
    """Las cuentas de un momento, con la versión con la que se leyeron."""

    accounts: Mapping[str, Account]
    domains: Mapping[str, DomainInfo] = field(default_factory=dict)
    #: Las cuentas que abre la ruta /mcp. En el modo estático, todas.
    default_scope: frozenset[str] = frozenset()
    version: int = 0


class AccountSource(Protocol):
    """De dónde salen las cuentas que puede tocar una petición."""

    def snapshot(self) -> AccountSnapshot:
        """Las cuentas de ahora, y su versión."""
        ...


class StaticAccounts:
    """Las cuentas del entorno o del ``accounts.toml``. No cambian."""

    def __init__(self, accounts: Mapping[str, Account]) -> None:
        self._snapshot = AccountSnapshot(
            accounts=dict(accounts),
            default_scope=frozenset(accounts),
            version=0,
        )

    def snapshot(self) -> AccountSnapshot:
        return self._snapshot


def como_fuente(accounts: Mapping[str, Account] | AccountSource) -> AccountSource:
    """Normaliza a una fuente. Un diccionario es una fuente estática.

    Lo usan los llamantes que tienen las cuentas en la mano (las pruebas,
    el arranque con el entorno) para no tener que distinguir los dos
    casos en cada sitio.
    """
    if isinstance(accounts, Mapping):
        return StaticAccounts(accounts)
    return accounts


def account_secrets(snapshot: AccountSnapshot) -> list[str]:
    """Los secretos que la auditoría tiene que tapar.

    Contraseñas y tokens. Cuando las cuentas vienen de la base de datos,
    la lista cambia, y quien los añade es la propia fuente al recargar.
    """
    secrets: list[str] = []
    for account in snapshot.accounts.values():
        if account.bearer:
            secrets.append(account.bearer)
        if account.password:
            secrets.append(account.password)
    for domain in snapshot.domains.values():
        if domain.bearer:
            secrets.append(domain.bearer)
    return secrets
