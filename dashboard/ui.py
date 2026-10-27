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
<main class="acceso">
  <section class="acceso-historia" aria-label="Correo conectado">
    <div class="acceso-marca"><span aria-hidden="true">✉</span> mcp-correo</div>
    <div class="sobre" aria-hidden="true">✉</div>
    <p class="eyebrow">MENOS CONFIGURACIÓN. MÁS CONEXIÓN.</p>
    <h1>Tu correo.<br>Tu asistente.<br>Un mismo espacio.</h1>
    <p>Organiza tus cuentas y conecta tu asistente,
      sin compartir las contraseñas de tus buzones.</p>
    <span class="acceso-sello">Control de acceso por cuenta</span>
  </section>
  <section class="acceso-formulario" aria-labelledby="acceso-titulo">
  <span class="eyebrow">PANEL DE ADMINISTRACIÓN</span>
  <h2 id="acceso-titulo">Bienvenido de nuevo</h2>
  <p class="acceso-intro">Tu espacio de correo está a una clave de distancia.</p>
  <form method="post" action="/login" class="acceso-form">
    <label for="token">Clave de acceso al panel</label>
    <input id="token" name="token" type="password" autocomplete="current-password"
      placeholder="Introduce tu clave de acceso" aria-describedby="acceso-ayuda" required autofocus>
    <!--error-->
    <button type="submit" class="primario">Entrar a mi panel
      <span aria-hidden="true">→</span></button>
  </form>
  <p id="acceso-ayuda" class="acceso-ayuda">
    Usa la clave que te facilitó quien administra el servicio.
    No es la contraseña de tu correo.</p>
  <details class="acceso-tecnico"><summary>¿Administras este servicio?</summary>
    <p>La clave corresponde a <code>MCP_DASHBOARD_TOKEN</code>, no al token del MCP.</p>
  </details>
  </section>
</main>
</body>
</html>
"""

_ERROR = (
    '<p class="error" role="alert">El token no vale. '
    "Revisa tu clave de acceso e inténtalo de nuevo.</p>"
)


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
