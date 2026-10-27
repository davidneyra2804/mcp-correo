"""Prueba de humo: el servidor con el panel, de punta a punta.

No es un test (no se ejecuta con pytest): se lanza a mano para ver que
las dos superficies funcionan a la vez.

    python3 herramientas/humo.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MCP = "http://127.0.0.1:18765"
PANEL = "http://127.0.0.1:18766"
TOKEN = "token-general-de-humo-0123456789abcdef"
PANEL_TOKEN = "token-del-panel-de-humo-0123456789abcdef"
CLAVE = "clave-del-panel-de-humo-0123456789abcdef"


def pedir(
    url: str,
    datos: dict | None = None,
    token: str = "",
    cookie: str = "",
    metodo: str = "",
) -> dict:
    metodo = metodo or ("POST" if datos is not None else "GET")
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    peticion = urllib.request.Request(url, data=cuerpo, method=metodo)
    if datos is not None:
        peticion.add_header("Content-Type", "application/json")
        peticion.add_header("Accept", "application/json, text/event-stream")
        peticion.add_header("X-MCP-Dashboard", "1")
    if metodo != "GET":
        peticion.add_header("X-MCP-Dashboard", "1")
    if token:
        peticion.add_header("Authorization", f"Bearer {token}")
    if cookie:
        peticion.add_header("Cookie", cookie)
    with urllib.request.urlopen(peticion, timeout=10) as respuesta:
        return json.loads(respuesta.read().decode())


def esperar(url: str, segundos: float = 20.0) -> None:
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception:
            time.sleep(0.2)
    raise SystemExit(f"El servidor no respondió en {url}")


def main() -> int:
    temporal = tempfile.mkdtemp(prefix="mcp-humo-")
    entorno = {
        **os.environ,
        "MCP_BEARER_TOKEN": TOKEN,
        "MCP_DASHBOARD_DB": str(Path(temporal) / "cuentas.db"),
        "MCP_DASHBOARD_KEY": CLAVE,
        "MCP_DASHBOARD_TOKEN": PANEL_TOKEN,
        "MCP_BIND_PORT": "18765",
        "MCP_DASHBOARD_BIND_PORT": "18766",
        "MCP_AUDIT_LOG": str(Path(temporal) / "audit.jsonl"),
        "MCP_CONFIG": str(RAIZ / "accounts.example.toml"),
        "MAIL_PRINCIPAL_PASSWORD": "clave-ficticia-principal",
        "MAIL_ARCHIVO_PASSWORD": "clave-ficticia-archivo",
        "PYTHONPATH": str(RAIZ),
    }
    proceso = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=RAIZ,
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        esperar(f"{MCP}/health")
        esperar(f"{PANEL}/health")
        print("Los dos puertos responden.\n")

        # 1. El panel: entrar, listar, crear.
        class SinRedireccion(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None

        opener = urllib.request.build_opener(SinRedireccion)
        peticion = urllib.request.Request(
            f"{PANEL}/login",
            data=b"token=" + PANEL_TOKEN.encode(),
            method="POST",
        )
        peticion.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            opener.open(peticion, timeout=10)
            cabeceras = {}
        except urllib.error.HTTPError as exc:
            cabeceras = exc.headers
        cookie = cabeceras.get("Set-Cookie", "").split(";")[0]
        print("1. Sesion abierta:", cookie[:28] + "...")

        dominios = pedir(f"{PANEL}/api/domains", cookie=cookie)
        print("   Dominios al entrar:", dominios["domains"])

        creado = pedir(
            f"{PANEL}/api/domains",
            {"name": "corp.example.com", "label": "Corporacion"},
            cookie=cookie,
        )
        cuenta = pedir(
            f"{PANEL}/api/accounts",
            {
                "domain_id": creado["id"],
                "name": "nueva@corp.example.com",
                "username": "nueva@corp.example.com",
                "password": "clave-ficticia",
                "imap_host": "imap.corp.example.com",
            },
            cookie=cookie,
        )
        print("   Creados: dominio", creado["id"], "y cuenta", cuenta["id"])

        # 2. La ruta, sin reiniciar nada.
        cuerpo = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_accounts", "arguments": {}},
        }
        respuesta = pedir(f"{MCP}/mcp/nueva@corp.example.com", cuerpo, token=TOKEN)
        guia = json.loads(respuesta["result"]["content"][0]["text"])
        print("\n2. La cuenta nueva en su ruta, sin reiniciar:", guia["scope"])

        # 3. La guia en la ruta general.
        respuesta = pedir(f"{MCP}/mcp", cuerpo, token=TOKEN)
        guia = json.loads(respuesta["result"]["content"][0]["text"])
        print("\n3. La guia:")
        print(json.dumps(guia, indent=2, ensure_ascii=False)[:900])

        # 4. El token de la cuenta, por su panel.
        token = pedir(f"{PANEL}/api/accounts/{cuenta['id']}/token", cookie=cookie, metodo="POST")[
            "token"
        ]
        peticion = urllib.request.Request(
            f"{MCP}/mcp/nueva@corp.example.com",
            data=json.dumps(cuerpo).encode(),
            method="POST",
        )
        peticion.add_header("Content-Type", "application/json")
        peticion.add_header("Accept", "application/json, text/event-stream")
        peticion.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            print("\n4. Con el token de la cuenta en su ruta:", respuesta.status)
        peticion = urllib.request.Request(
            f"{MCP}/mcp",
            data=json.dumps(cuerpo).encode(),
            method="POST",
        )
        peticion.add_header("Content-Type", "application/json")
        peticion.add_header("Accept", "application/json, text/event-stream")
        peticion.add_header("Authorization", f"Bearer {token}")
        try:
            urllib.request.urlopen(peticion, timeout=10)
            print("   En la ruta general: 200 (no deberia)")
        except urllib.error.HTTPError as exc:
            print("   En la ruta general:", exc.code, "(correcto: 403)")

        print("\nOK")
        return 0
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proceso.kill()


if __name__ == "__main__":
    import urllib.error

    raise SystemExit(main())
