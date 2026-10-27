"""La sesión del panel.

Una cookie firmada con HMAC, con la clave del panel. La comparación es
con ``hmac.compare_digest``, como el bearer del MCP.

Las peticiones que cambian algo exigen además una cabecera a medida
(``X-MCP-Dashboard``). Un formulario de otro sitio no puede poner una
cabecera a medida, así que el CSRF queda cerrado sin inventar un token
anti-CSRF aparte.
"""

from __future__ import annotations

import hashlib
import hmac
import time

#: La cookie de la sesión.
COOKIE = "mcp_correo_panel"
#: Cuánto dura una sesión, en segundos.
TTL = 8 * 60 * 60
#: La cabecera que exigen las peticiones que cambian algo.
CABECERA_CSRF = "x-mcp-dashboard"
#: Lo que tiene que valer esa cabecera.
VALOR_CSRF = "1"


def firmar(token: str, expira: int) -> str:
    """La cookie: cuándo caduca y su firma."""
    payload = str(expira).encode()
    firma = hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()
    return f"{expira}.{firma}"


def verificar(token: str, cookie: str | None) -> bool:
    """Si la cookie es de este panel y no ha caducado."""
    if not cookie:
        return False
    expira, _, firma = cookie.partition(".")
    if not firma or not expira.isdigit():
        return False
    esperado = firmar(token, int(expira)).partition(".")[2]
    if not hmac.compare_digest(firma, esperado):
        return False
    return int(expira) > int(time.time())
