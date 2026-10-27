"""La interfaz del panel: el login y la página.

La página es un fichero estático, con el JavaScript al lado. No hay
framework: el panel es una herramienta de operación, no una aplicación.
"""

from __future__ import annotations

import hmac
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from dashboard.auth import COOKIE, TTL, firmar

#: Los ficheros estáticos del panel.
STATIC = Path(__file__).parent / "static"

_LOGIN = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel de mcp-correo</title>
<link rel="stylesheet" href="/static/panel.css">
</head>
<body class="login">
<main>
  <h1>Panel de mcp-correo</h1>
  <form method="post" action="/login">
    <label for="token">Token del panel</label>
    <input id="token" name="token" type="password" autocomplete="current-password" autofocus>
    <!--error-->
    <button type="submit">Entrar</button>
  </form>
  <p class="pista">Es <code>MCP_DASHBOARD_TOKEN</code>, no el token del MCP.</p>
</main>
</body>
</html>
"""

_ERROR = '<p class="error">El token no vale.</p>'


async def panel(request: Request) -> HTMLResponse:
    """La página del panel."""
    return HTMLResponse((STATIC / "panel.html").read_text(encoding="utf-8"))


async def login(request: Request) -> HTMLResponse:
    """El formulario de acceso."""
    return HTMLResponse(_LOGIN)


async def entrar(request: Request) -> Response:
    """Comprueba el token y abre sesión."""
    form = await request.form()
    token = str(form.get("token") or "")
    esperado = str(request.app.state.dashboard_token)
    if not token or not hmac.compare_digest(token, esperado):
        return HTMLResponse(_LOGIN.replace("<!--error-->", _ERROR), status_code=401)
    respuesta = RedirectResponse("/", status_code=303)
    respuesta.set_cookie(
        COOKIE,
        firmar(esperado, int(time.time()) + TTL),
        httponly=True,
        samesite="strict",
        path="/",
    )
    return respuesta


async def salir(request: Request) -> Response:
    """Cierra la sesión."""
    respuesta = RedirectResponse("/login", status_code=303)
    respuesta.delete_cookie(COOKIE, path="/")
    return respuesta
