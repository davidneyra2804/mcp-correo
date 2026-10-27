"""La sonda de salud del contenedor.

Comprueba el MCP y el panel. Si uno de los dos no responde, el contenedor
está unhealthy: es mejor que el orquestador lo sepa a que no lo sepa.
"""

from __future__ import annotations

import os
import sys
import urllib.request


def _sonda(puerto: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/health", timeout=5) as respuesta:
            return respuesta.status == 200
    except Exception:
        return False


def main() -> int:
    mcp = int(os.environ.get("MCP_BIND_PORT", "8765"))
    if not _sonda(mcp):
        print(f"El MCP no responde en el puerto {mcp}.")
        return 1
    panel = int(os.environ.get("MCP_DASHBOARD_BIND_PORT", "8766"))
    if not _sonda(panel):
        print(f"El panel no responde en el puerto {panel}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
