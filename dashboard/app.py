"""La aplicación del panel: la interfaz y su API.

El panel es una superficie aparte del MCP. No registra tools, no habla
con el SDK y no puede tocar un buzón: solo gestiona la configuración y
prueba conexiones.
"""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from audit import AuditLog
from config import DashboardSettings, ServerSettings
from dashboard import api, ui
from dashboard.auth import CABECERA_CSRF, COOKIE, verificar
from store.store import Store

#: Los ficheros estáticos del panel.
STATIC = Path(__file__).parent / "static"


class PanelAuth:
    """La sesión del panel y la comprobación anti-CSRF.

    Sin sesión, la página redirige al login y la API responde 401. Las
    peticiones que cambian algo exigen además la cabecera ``X-MCP-Dashboard``:
    un formulario de otro sitio no puede poner una cabecera a medida.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        metodo = scope.get("method") or "GET"
        if path == "/health" or path.startswith("/static"):
            await self.app(scope, receive, send)
            return
        cookie = _cookie(scope)
        tiene_sesion = verificar(self._token, cookie)
        if path == "/login":
            if metodo == "GET":
                await self.app(scope, receive, send)
                return
            # El POST del login es el que comprueba el token.
            await self.app(scope, receive, send)
            return
        if not tiene_sesion:
            if path.startswith("/api/"):
                await _json(send, 401, {"ok": False, "error": "Sesión no válida."})
                return
            await _redirigir(send, "/login")
            return
        if metodo not in {"GET", "HEAD", "OPTIONS"} and not _tiene_cabecera(scope, CABECERA_CSRF):
            await _json(send, 403, {"ok": False, "error": "Falta la cabecera anti-CSRF."})
            return
        await self.app(scope, receive, send)


def _cookie(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name != b"cookie":
            continue
        for parte in value.decode("utf-8", "ignore").split(";"):
            clave, _, contenido = parte.strip().partition("=")
            if clave == COOKIE:
                return contenido
    return None


def _tiene_cabecera(scope: Scope, nombre: str) -> bool:
    for name, _value in scope.get("headers", []):
        if name.decode("utf-8", "ignore").lower() == nombre:
            return True
    return False


async def _json(send: Send, status: int, cuerpo: dict) -> None:
    import json

    datos = json.dumps(cuerpo, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(datos)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": datos, "more_body": False})


async def _redirigir(send: Send, destino: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 303,
            "headers": [
                (b"location", destino.encode()),
                (b"content-length", b"0"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": b"", "more_body": False})


async def salud(request: Request) -> JSONResponse:
    """La sonda del panel. No dice nada de las cuentas."""
    return JSONResponse({"status": "ok"})


def crear_app(
    dashboard: DashboardSettings,
    store: Store,
    settings: ServerSettings,
    audit: AuditLog | None = None,
) -> Starlette:
    """La aplicación del panel."""
    app = Starlette(
        routes=[
            Route("/", ui.panel, methods=["GET"]),
            Route("/login", ui.login, methods=["GET"]),
            Route("/login", ui.entrar, methods=["POST"]),
            Route("/logout", ui.salir, methods=["POST"]),
            Mount("/static", StaticFiles(directory=str(STATIC)), name="static"),
            Route("/api/domains", api.listar_dominios, methods=["GET"]),
            Route("/api/domains", api.crear_dominio, methods=["POST"]),
            Route("/api/domains/{id}", api.cambiar_dominio, methods=["PATCH"]),
            Route("/api/domains/{id}", api.borrar_dominio, methods=["DELETE"]),
            Route("/api/domains/{id}/default", api.marcar_por_defecto, methods=["POST"]),
            Route("/api/domains/{id}/token", api.token_dominio, methods=["POST"]),
            Route("/api/accounts", api.crear_cuenta, methods=["POST"]),
            Route("/api/accounts/{id}", api.cambiar_cuenta, methods=["PATCH"]),
            Route("/api/accounts/{id}", api.borrar_cuenta, methods=["DELETE"]),
            Route("/api/accounts/{id}/token", api.token_cuenta, methods=["POST"]),
            Route("/api/test/imap", api.probar_conexion_imap, methods=["POST"]),
            Route("/api/test/smtp", api.probar_conexion_smtp, methods=["POST"]),
            Route("/health", salud, methods=["GET"]),
        ],
        middleware=[Middleware(PanelAuth, token=dashboard.token)],
    )
    app.state.store = store
    app.state.settings = settings
    app.state.audit = audit
    app.state.dashboard_token = dashboard.token
    # Las fábricas de IMAP y SMTP. Se pueden sustituir (las pruebas lo
    # hacen); si no, se usan las de verdad.
    app.state.imap_factory = None
    app.state.smtp_factory = None
    return app
