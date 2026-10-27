"""La versión tiene que ser la misma en todos los sitios.

Hay tres lugares donde aparece el número: `version.py` (la fuente de
verdad), `pyproject.toml` (lo exige el formato) y la etiqueta de la
imagen. Si uno se queda atrás, el despliegue y la documentación mienten.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from audit import AuditLog
from config import load_config
from server import create_app
from version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_la_version_sigue_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_pyproject_dice_la_misma_version() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_la_etiqueta_de_la_imagen_dice_la_misma_version() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"ARG MCP_VERSION=(\S+)", dockerfile)
    assert match, "El Dockerfile debería declarar ARG MCP_VERSION"
    assert match.group(1) == __version__


def test_el_handshake_mcp_dice_la_version(tmp_path: Path) -> None:
    """El cliente ve la versión en el initialize, sin exponerla en /health."""
    settings, accounts = load_config(ROOT / "accounts.example.toml")
    audit = AuditLog(tmp_path / "audit.jsonl")
    application, _runtime = create_app(
        settings, accounts, "token-de-prueba-0123456789abcdef", audit=audit
    )
    with TestClient(application, base_url="http://127.0.0.1:8765") as http:
        response = http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": "Bearer token-de-prueba-0123456789abcdef",
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["serverInfo"]["version"] == __version__


def test_health_no_revela_la_version(tmp_path: Path) -> None:
    """`/health` no pide token: no debe filtrar la versión a quien llame."""
    settings, accounts = load_config(ROOT / "accounts.example.toml")
    audit = AuditLog(tmp_path / "audit.jsonl")
    application, _runtime = create_app(
        settings, accounts, "token-de-prueba-0123456789abcdef", audit=audit
    )
    with TestClient(application, base_url="http://127.0.0.1:8765") as http:
        response = http.get("/health")
    assert response.status_code == 200
    assert __version__ not in response.text


def test_el_banner_de_arranque_se_ve(tmp_path: Path) -> None:
    """Los logs del arranque tienen que salir de verdad.

    Antes salían porque el SDK configuraba el logger raíz de rebote al
    construir el MCPServer, con su formato. Si el SDK cambiaba, el banner
    cambiaba con él, o desaparecía.
    """
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env["MCP_BEARER_TOKEN"] = "token-de-prueba-0123456789abcdef"
    env["MCP_AUDIT_LOG"] = str(tmp_path / "audit.jsonl")
    env["MCP_CONFIG"] = str(ROOT / "accounts.example.toml")
    # PYTHONSAFEPATH (Actions) no añade el cwd. PYTHONPATH sí entra en
    # sys.path. Sin esto, el subproceso no encuentra `server` y el test
    # falla solo en CI.
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else os.pathsep.join((str(ROOT), previous))
    # Y el panel hace bind de verdad: necesita un puerto propio, o choca
    # con el del proceso de los tests.
    from tests.fakes import puerto_libre

    env["MCP_DASHBOARD_BIND_PORT"] = str(puerto_libre())
    completed = subprocess.run(
        [sys.executable, "-c", "import server"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    salida = completed.stdout + completed.stderr
    assert "Servidor listo:" in salida, salida
    assert "Configuración: " in salida, salida
    assert f"mcp-correo {__version__}" in salida, salida
    # Con el prefijo de nivel, como los de uvicorn.
    assert "INFO     Servidor listo:" in salida, salida


@pytest.mark.parametrize("fichero", ["README.md", "docs/configuracion.md"])
def test_la_documentacion_no_contradice_la_version(fichero: str) -> None:
    """Si el README habla de una versión concreta, tiene que ser la buena."""
    text = (ROOT / fichero).read_text(encoding="utf-8")
    for mentioned in set(re.findall(r"\bv?(\d+\.\d+\.\d+)\b", text)):
        if mentioned in {"0.2.0", "1.0.0"}:
            assert mentioned == __version__, f"{fichero} menciona {mentioned}"
