"""El segundo servidor: el panel, en su puerto.

Un hilo aparte, con su propio bucle de eventos. El MCP sigue siendo el
proceso principal: es el que tiene en memoria el token de confirmación y
el cupo diario de envíos, y los dos tienen que estar en el mismo sitio.

uvicorn no toca las señales en un hilo que no es el principal, así que el
SIGTERM lo sigue cogiendo el servidor del MCP.
"""

from __future__ import annotations

import logging
import threading

import uvicorn

from audit import AuditLog
from config import DashboardSettings, ServerSettings
from dashboard.app import crear_app
from store.store import Store

logger = logging.getLogger("mcp_correo.panel")


def lanzar(
    dashboard: DashboardSettings,
    store: Store,
    settings: ServerSettings,
    audit: AuditLog | None = None,
) -> threading.Thread:
    """Levanta el panel en su hilo. Devuelve el hilo, para poder esperarlo."""
    app = crear_app(dashboard, store, settings, audit)
    config = uvicorn.Config(
        app,
        host=dashboard.bind_host,
        port=dashboard.bind_port,
        log_level="info",
        access_log=False,
    )
    servidor = uvicorn.Server(config)

    def _servir() -> None:
        logger.info("Panel en marcha: http://%s:%s", dashboard.bind_host, dashboard.bind_port)
        servidor.run()

    hilo = threading.Thread(target=_servir, name="mcp-correo-panel", daemon=True)
    hilo.start()
    return hilo
