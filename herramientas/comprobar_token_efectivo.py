#!/usr/bin/env python3
"""Comprobación de extremo a extremo del token efectivo de una cuenta MCP.

Arranca el servidor de verdad (``server.py``), da de alta un dominio y dos
cuentas en su base, deja una de ellas sin credencial propia, y comprueba
contra el servidor en marcha que:

- el token que devuelve el panel para la cuenta sin credencial propia es el
  del dominio, y es el que el servidor acepta en su ruta;
- el token propio de la otra cuenta también es aceptado;
- una credencial ajena da 403 y una credencial desconocida da 401;
- el token no aparece en la auditoría.

Los valores son de RFC 2606 y no son reales.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

DOMINIO = "corp.example.com"
CUENTA_CON_TOKEN = "ada@corp.example.com"
CUENTA_SIN_TOKEN = "luis@corp.example.com"

TOKEN_GENERAL = "token-general-ficticio-0123456789abcdef"
TOKEN_PANEL = "token-del-panel-ficticio-0123456789abcdef"
CLAVE = "clave-del-panel-ficticia-0123456789"

PUERTO_MCP = 8791
PUERTO_PANEL = 8792

JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _pedir(url: str, token: str | None = None, metodo: str = "GET", cuerpo: dict | None = None):
    peticion = urllib.request.Request(url, method=metodo)
    if token:
        peticion.add_header("Authorization", f"Bearer {token}")
    if cuerpo is not None:
        peticion.add_header("Content-Type", "application/json")
        peticion.data = json.dumps(cuerpo).encode()
    try:
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            return respuesta.status, respuesta.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def _mcp(ruta: str, token: str) -> tuple[int, str]:
    cuerpo = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "list_accounts", "arguments": {}},
    }
    peticion = urllib.request.Request(f"http://127.0.0.1:{PUERTO_MCP}{ruta}", method="POST")
    peticion.add_header("Authorization", f"Bearer {token}")
    for clave, valor in JSON_HEADERS.items():
        peticion.add_header(clave, valor)
    peticion.data = json.dumps(cuerpo).encode()
    try:
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            return respuesta.status, respuesta.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def _guia(ruta: str, token: str) -> dict:
    estado, texto = _mcp(ruta, token)
    if estado != 200:
        raise AssertionError(f"{ruta} con la credencial devolvió {estado}: {texto[:300]}")
    carga = json.loads(texto)
    return json.loads(carga["result"]["content"][0]["text"])


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mcp-correo-e2e-"))
    base = tmp / "cuentas.db"
    auditoria = tmp / "audit.jsonl"
    entorno = {
        **os.environ,
        "MCP_BEARER_TOKEN": TOKEN_GENERAL,
        "MCP_DASHBOARD_KEY": CLAVE,
        "MCP_DASHBOARD_TOKEN": TOKEN_PANEL,
        "MCP_DASHBOARD_DB": str(base),
        "MCP_AUDIT_LOG": str(auditoria),
        "MCP_BIND_HOST": "127.0.0.1",
        "MCP_BIND_PORT": str(PUERTO_MCP),
        "MCP_DASHBOARD_BIND_PORT": str(PUERTO_PANEL),
    }
    entorno.pop("PYTHONPATH", None)

    proceso = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=RAIZ,
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Espera a que el puerto del MCP responda.
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PUERTO_MCP}/health", timeout=1):
                    break
            except Exception:
                if proceso.poll() is not None:
                    salida = proceso.stdout.read() if proceso.stdout else ""
                    raise AssertionError("El servidor se paró al arrancar:\n" + salida) from None
                time.sleep(0.2)
        else:
            raise AssertionError("El servidor no arrancó a tiempo.")

        # El panel se loguea y da de alta el dominio y las cuentas.
        cookie = _entrar_al_panel()
        dominio_id = _crear_dominio(cookie)
        cuenta_con = _crear_cuenta(cookie, dominio_id, CUENTA_CON_TOKEN)
        cuenta_sin = _crear_cuenta(cookie, dominio_id, CUENTA_SIN_TOKEN)

        # Se deja la segunda cuenta sin credencial propia.
        _patch_cuenta(cookie, cuenta_sin, {"bearer": ""})

        # Y se le da al dominio una credencial propia.
        token_dominio = _rotar_token_dominio(cookie, dominio_id)
        token_cuenta = _credenciales(cookie, cuenta_con)["token"]

        # --- comprobaciones ---------------------------------------------------
        resultados: list[tuple[str, bool, str]] = []

        def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
            resultados.append((nombre, condicion, detalle))

        # 1. La cuenta sin credencial propia se abre con el token del dominio.
        credenciales_sin = _credenciales(cookie, cuenta_sin)
        comprobar(
            "el panel devuelve el token del dominio para la cuenta sin credencial propia",
            credenciales_sin["token"] == token_dominio,
            f"origen={credenciales_sin['origen']}",
        )
        guia = _guia(f"/mcp/{CUENTA_SIN_TOKEN}", credenciales_sin["token"])
        comprobar(
            "el servidor acepta ese token en la ruta de la cuenta",
            [c["account"] for c in guia["accounts"]] == [CUENTA_SIN_TOKEN],
        )
        comprobar(
            "el ámbito es solo esa cuenta",
            guia["scope"] == [CUENTA_SIN_TOKEN],
            f"scope={guia['scope']}",
        )

        # 2. La cuenta con credencial propia se abre con la suya.
        credenciales_con = _credenciales(cookie, cuenta_con)
        comprobar(
            "el panel devuelve el token propio cuando la cuenta lo tiene",
            credenciales_con["token"] == token_cuenta and credenciales_con["origen"] == "cuenta",
            f"origen={credenciales_con['origen']}",
        )
        guia = _guia(f"/mcp/{CUENTA_CON_TOKEN}", credenciales_con["token"])
        comprobar(
            "el servidor acepta el token propio en su ruta",
            [c["account"] for c in guia["accounts"]] == [CUENTA_CON_TOKEN],
        )

        # 3. Aislamiento: el token de una cuenta no abre la otra.
        estado, _ = _mcp(f"/mcp/{CUENTA_SIN_TOKEN}", token_cuenta)
        comprobar(
            "el token de una cuenta no abre la otra cuenta del dominio",
            estado == 403,
            f"estado={estado}",
        )
        estado, _ = _mcp(f"/mcp/{CUENTA_CON_TOKEN}", token_dominio)
        comprobar(
            "el token del dominio sí abre las cuentas de su dominio",
            estado == 200,
            f"estado={estado}",
        )
        estado, _ = _mcp("/mcp", token_dominio)
        comprobar(
            "el token del dominio no abre la ruta general",
            estado == 403,
            f"estado={estado}",
        )
        estado, _ = _mcp(f"/mcp/{CUENTA_CON_TOKEN}", "credencial-ajena-ficticia-0123456789")
        comprobar(
            "una credencial desconocida da 401",
            estado == 401,
            f"estado={estado}",
        )

        # 4. Leer el panel no rota nada.
        despues = _credenciales(cookie, cuenta_con)
        comprobar(
            "leer las credenciales no rota el token",
            despues["token"] == credenciales_con["token"],
        )

        # 5. La auditoría no guarda el valor del token.
        texto_auditoria = auditoria.read_text(encoding="utf-8") if auditoria.exists() else ""
        comprobar(
            "el token propio no está en la auditoría",
            token_cuenta not in texto_auditoria,
        )
        comprobar(
            "el token del dominio no está en la auditoría",
            token_dominio not in texto_auditoria,
        )
        comprobar(
            "la auditoría sí registra la lectura",
            "dashboard_read_account_credentials" in texto_auditoria,
        )

        # --- informe -----------------------------------------------------------
        fallos = [r for r in resultados if not r[1]]
        for nombre, bien, detalle in resultados:
            marca = "OK  " if bien else "FALLA"
            extra = f"  ({detalle})" if detalle else ""
            print(f"{marca}  {nombre}{extra}")
        print()
        total = len(resultados)
        print(f"{total - len(fallos)}/{total} comprobaciones de extremo a extremo")
        return 1 if fallos else 0
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proceso.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def _cookie(cabecera: str) -> str:
    """El valor de la cookie del panel, de la cabecera Set-Cookie."""
    return cabecera.split("=", 1)[1].split(";", 1)[0].strip()


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """Sin seguir redirecciones: la cookie va en la respuesta del login."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _entrar_al_panel() -> str:
    peticion = urllib.request.Request(
        f"http://127.0.0.1:{PUERTO_PANEL}/login",
        method="POST",
        data=urllib.parse.urlencode({"token": TOKEN_PANEL}).encode(),
    )
    peticion.add_header("Content-Type", "application/x-www-form-urlencoded")
    abridor = urllib.request.build_opener(_SinRedirecciones)
    try:
        with abridor.open(peticion, timeout=10) as respuesta:
            return _cookie(respuesta.headers.get("Set-Cookie", ""))
    except urllib.error.HTTPError as exc:
        # Un 303 es el login correcto: la cookie va en la cabecera de la respuesta.
        cabecera = exc.headers.get("Set-Cookie", "")
        if exc.code == 303 and cabecera:
            return _cookie(cabecera)
        raise AssertionError(f"No se pudo entrar al panel: {exc.code}") from None


def _api_panel(cookie: str, ruta: str, metodo: str = "GET", cuerpo: dict | None = None) -> dict:
    peticion = urllib.request.Request(f"http://127.0.0.1:{PUERTO_PANEL}{ruta}", method=metodo)
    peticion.add_header("Cookie", f"mcp_correo_panel={cookie}")
    peticion.add_header("X-MCP-Dashboard", "1")
    if cuerpo is not None:
        peticion.add_header("Content-Type", "application/json")
        peticion.data = json.dumps(cuerpo).encode()
    with urllib.request.urlopen(peticion, timeout=10) as respuesta:
        return json.loads(respuesta.read().decode())


def _crear_dominio(cookie: str) -> int:
    return _api_panel(cookie, "/api/domains", "POST", {"name": DOMINIO})["id"]


def _crear_cuenta(cookie: str, dominio_id: int, nombre: str) -> int:
    return _api_panel(
        cookie,
        "/api/accounts",
        "POST",
        {
            "domain_id": dominio_id,
            "name": nombre,
            "username": nombre,
            "password": "clave-ficticia",
            "imap_host": "imap.corp.example.com",
        },
    )["id"]


def _patch_cuenta(cookie: str, identificador: int, cambios: dict) -> None:
    _api_panel(cookie, f"/api/accounts/{identificador}", "PATCH", cambios)


def _rotar_token_dominio(cookie: str, dominio_id: int) -> str:
    return _api_panel(cookie, f"/api/domains/{dominio_id}/token", "POST")["token"]


def _credenciales(cookie: str, identificador: int) -> dict:
    return _api_panel(cookie, f"/api/accounts/{identificador}/credentials", "GET")


if __name__ == "__main__":
    sys.exit(main())
