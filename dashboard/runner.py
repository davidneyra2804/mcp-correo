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
    """Levanta el panel en su hilo. Devuelve el hilo, para poder esperarlo.

    El socket se abre **antes**, en el hilo principal. Si el puerto está
    ocupado, el proceso para y lo dice, en vez de quedarse con un panel
    muerto: el panel es parte del servidor, y un servidor sin panel no
    puede gestionar sus cuentas.
    """
    app = crear_app(dashboard, store, settings, audit)
    config = uvicorn.Config(
        app,
        host=dashboard.bind_host,
        port=dashboard.bind_port,
        log_level="info",
        access_log=False,
    )
    try:
        # uvicorn devuelve un socket suelto y, si no puede hacer el bind,
        # avisa y sale con sys.exit. Aquí se convierte en un error del
        # servidor, con el puerto y qué hacer.
        sockets = [config.bind_socket()]
    except (OSError, SystemExit):
        raise SystemExit(
            f"El panel no puede escuchar en {dashboard.bind_host}:{dashboard.bind_port}. "
            "Puede que el puerto esté ocupado por otro proceso."
        ) from None
    servidor = uvicorn.Server(config)

    def _servir() -> None:
        servidor.run(sockets=sockets)

    hilo = threading.Thread(target=_servir, name="mcp-correo-panel", daemon=True)
    hilo.start()
    logger.info("Panel en marcha: http://%s:%s", dashboard.bind_host, dashboard.bind_port)
    return hilo
