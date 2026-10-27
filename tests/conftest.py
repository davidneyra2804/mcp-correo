"""Entorno ficticio. Tiene que ejecutarse antes de importar `server`."""

from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _puerto_libre() -> int:
    """Un puerto que está libre ahora mismo.

    El panel hace `bind` de verdad al importar `server`. Si compartiera
    puerto con otro proceso, el arranque del panel fallaría, y con él el
    test que comprueba que el panel arranca.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


os.environ.setdefault(
    "MCP_BEARER_TOKEN",
    "token-de-prueba-no-real-0123456789abcdef",
)
os.environ.setdefault("MCP_CONFIG", str(ROOT / "accounts.example.toml"))
os.environ.setdefault("MCP_AUDIT_LOG", "/tmp/mcp-correo-test-audit.jsonl")
os.environ.setdefault("MAIL_PRINCIPAL_PASSWORD", "clave-ficticia-principal")
os.environ.setdefault("MAIL_ARCHIVO_PASSWORD", "clave-ficticia-archivo")
os.environ.setdefault("MCP_BIND_HOST", "127.0.0.1")

# El panel y la base de datos siempre están. En los tests, en un fichero
# temporal: la base de cada test tiene que estar separada.
os.environ.setdefault("MCP_DASHBOARD_KEY", "clave-de-prueba-0123456789abcdef")
os.environ.setdefault("MCP_DASHBOARD_TOKEN", "token-del-panel-0123456789abcdef")
os.environ.setdefault(
    "MCP_DASHBOARD_DB",
    str(Path(tempfile.gettempdir()) / "mcp-correo-test-cuentas.db"),
)
os.environ.setdefault("MCP_DASHBOARD_BIND_PORT", str(_puerto_libre()))
