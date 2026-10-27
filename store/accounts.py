"""La fuente de cuentas: de dónde salen y cuándo se recargan.

El servidor no guarda el conjunto de cuentas en un diccionario: lo pide a
una fuente. Hay dos:

- ``StaticAccounts``, la de un conjunto fijo, que no cambia. La usan las
  pruebas y quien monta la aplicación a mano.
- ``DatabaseAccounts``, la del panel. Se recarga cuando alguien toca el
  panel, sin reiniciar el servidor.

La fuente entrega una ``AccountSnapshot``: las cuentas, los dominios y la
versión con la que se leyeron. La versión sirve para saber si lo que se
tiene en memoria sigue siendo bueno, sin volver a preguntar.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from config import Account, ServerSettings
from store.crypto import CipherError
from store.models import to_account
from store.store import Store

logger = logging.getLogger("mcp_correo.store")


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
    """Un conjunto fijo de cuentas. No cambian."""

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


class DatabaseAccounts:
    """Las cuentas de la base de datos.

    Se recarga cuando el panel toca algo. El contador de revisiones vive
    en la base, así que funciona igual dentro de un proceso que entre
    dos: el que escribe sube la revisión y el que lee la ve.
    """

    def __init__(
        self,
        store: Store,
        settings: ServerSettings,
        on_reload: Callable[[AccountSnapshot], None] | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._on_reload = on_reload
        self._lock = threading.Lock()
        self._snapshot = AccountSnapshot({}, {}, frozenset(), -1)

    def snapshot(self) -> AccountSnapshot:
        """Las cuentas de ahora.

        La revisión se lee en cada llamada: es una fila de una tabla de
        dos, y es lo que hace que una cuenta creada en el panel esté
        disponible en la siguiente petición, sin reiniciar nada.
        """
        revision = self._store.db.revision()
        with self._lock:
            if revision == self._snapshot.version:
                return self._snapshot
            nuevo = self._cargar(revision)
            self._snapshot = nuevo
        if self._on_reload is not None:
            self._on_reload(nuevo)
        return nuevo

    def invalidate(self) -> None:
        """Fuerza la recarga en la próxima llamada."""
        with self._lock:
            self._snapshot = AccountSnapshot({}, {}, frozenset(), -1)

    def _cargar(self, revision: int) -> AccountSnapshot:
        dominios = self._store.dominios()
        por_id = {dominio.id: dominio for dominio in dominios}
        cuentas: dict[str, Account] = {}
        por_dominio: dict[str, list[str]] = {dominio.name: [] for dominio in dominios}
        for registro in self._store.cuentas():
            if not registro.enabled:
                continue
            dominio = por_id.get(registro.domain_id)
            if dominio is None:  # pragma: no cover - la clave foránea lo impide
                continue
            try:
                password = self._store.cipher.decrypt(registro.password)
            except CipherError as exc:
                logger.error(
                    "La cuenta %s no se puede descifrar: %s. Se deja fuera.",
                    registro.name,
                    exc,
                )
                continue
            cuentas[registro.name] = to_account(registro, dominio, password, self._settings)
            por_dominio.setdefault(dominio.name, []).append(registro.name)
        infos = {
            dominio.name: DomainInfo(
                name=dominio.name,
                label=dominio.label,
                is_default=dominio.is_default,
                bearer=dominio.bearer,
                accounts=tuple(por_dominio.get(dominio.name, ())),
            )
            for dominio in dominios
        }
        por_defecto = next(
            (dominio.name for dominio in dominios if dominio.is_default),
            None,
        )
        alcance = frozenset(por_dominio.get(por_defecto, ())) if por_defecto else frozenset()
        return AccountSnapshot(
            accounts=cuentas,
            domains=infos,
            default_scope=alcance,
            version=revision,
        )
