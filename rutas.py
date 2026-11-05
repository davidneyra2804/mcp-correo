"""El contrato de las rutas del MCP, en un solo sitio.

El servidor enruta por estas rutas y el panel las enseña y las copia. Si
cada uno define la ruta por su cuenta, el panel puede pintar una URL que
el servidor no acepta: el error sale al pegar la URL en el cliente, no
antes.

Por eso aquí viven las tres cosas de la ruta:

- ``MCP_ROOT``, la raíz del transporte.
- ``ruta_de_cuenta()``, la ruta de una cuenta concreta.
- ``url_del_mcp()``, la URL completa que se pega en un cliente MCP.
"""

from __future__ import annotations

#: Raíz del transporte MCP. /mcp/<cuenta> se resuelve al mismo handler.
MCP_ROOT = "/mcp"

#: Esquema con el que se publica el servidor.
ESQUEMA_PUBLICO = "https"


def ruta_de_cuenta(cuenta: str) -> str:
    """La ruta de una cuenta: /mcp/<cuenta>."""
    return f"{MCP_ROOT}/{cuenta}"


def url_del_mcp(public_host: str, cuenta: str) -> str:
    """La URL completa del MCP de una cuenta, lista para pegar.

    El host es el público, no el de escucha: el cliente MCP habla con el
    servidor por fuera (el túnel, el proxy), no por el puerto interno.
    """
    return f"{ESQUEMA_PUBLICO}://{public_host}{ruta_de_cuenta(cuenta)}"
