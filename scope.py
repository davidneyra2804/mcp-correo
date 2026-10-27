"""Ámbito de la petición: qué cuentas puede tocar una llamada.

El servidor expone tres rutas:

- ``/mcp``            la guía: el catálogo de rutas y el dominio por
                      defecto, si hay uno.
- ``/mcp/<dominio>``  las cuentas de un dominio.
- ``/mcp/<cuenta>``   una cuenta.

La ruta fija el ámbito y el Bearer fija la credencial. El ámbito viaja en un
``ContextVar`` porque las tools del SDK MCP son síncronas y se ejecutan en un
hilo del pool: ``anyio.to_thread.run_sync`` copia el contexto, así que el
valor llega intacto.

``None`` significa "sin restricción". Es lo que se ve fuera de una petición
HTTP (pruebas, uso interno), donde no hay nada que acotar.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    """Qué cuentas puede tocar la petición, y en qué ruta está."""

    #: Claves de cuenta permitidas. None = todas.
    keys: frozenset[str] | None = None
    #: La ruta que se pidió, tal y como se escribe: "/mcp", "/mcp/<dominio>".
    route: str = ""
    #: "root", "domain" o "account".
    kind: str = ""
    #: El identificador de la ruta, sin la parte inicial.
    ident: str = ""
    #: Las cuentas que alcanza la credencial. None = todas.
    reach: frozenset[str] | None = None

    def allows(self, key: str) -> bool:
        """Si esta cuenta está en el ámbito."""
        return self.keys is None or key in self.keys


_SCOPE: ContextVar[Scope | None] = ContextVar("mcp_correo_scope", default=None)


def current_scope() -> Scope | None:
    """El ámbito de la petición en curso, o None si no hay ninguno."""
    return _SCOPE.get()


def scope_keys() -> frozenset[str] | None:
    """Las claves de cuenta permitidas, o None si no hay restricción."""
    scope = _SCOPE.get()
    return None if scope is None else scope.keys


def set_scope(scope: Scope | Iterable[str] | None) -> Token:
    """Fija el ámbito de la petición en curso.

    Acepta un ``Scope`` entero o un conjunto de claves: lo segundo es el
    atajo para cuando solo importa el conjunto.
    """
    if scope is None or isinstance(scope, Scope):
        nuevo = scope
    else:
        nuevo = Scope(keys=frozenset(scope))
    return _SCOPE.set(nuevo)


def reset_scope(token: Token) -> None:
    """Restaura el ámbito anterior."""
    _SCOPE.reset(token)
