"""Ámbito de la petición: qué cuentas puede tocar una llamada.

El servidor expone dos rutas:

- ``/mcp``            todas las cuentas configuradas.
- ``/mcp/<cuenta>``   solo una.

La ruta fija el ámbito y el Bearer fija la credencial. El ámbito viaja en un
``ContextVar`` porque las tools del SDK MCP son síncronas y se ejecutan en un
hilo del pool: ``anyio.to_thread.run_sync`` copia el contexto, así que el
valor llega intacto.

``None`` significa "sin restricción". Es lo que se ve fuera de una petición
HTTP (pruebas, uso interno), donde no hay nada que acotar.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

_SCOPE: ContextVar[frozenset[str] | None] = ContextVar("mcp_correo_scope", default=None)


def current_scope() -> frozenset[str] | None:
    """Claves de cuenta permitidas, o None si no hay restricción."""
    return _SCOPE.get()


def set_scope(keys: frozenset[str] | None) -> Token:
    """Fija el ámbito de la petición en curso."""
    return _SCOPE.set(keys)


def reset_scope(token: Token) -> None:
    """Restaura el ámbito anterior."""
    _SCOPE.reset(token)
