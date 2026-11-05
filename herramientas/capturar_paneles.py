"""Capturas del «antes» y del «después» del panel.

El «antes» se toma de la base real: el commit `4992f46` (VYRA-32), que
era la última versión sin selector de tema. Esa base era **de modo
oscuro único**, así que del «antes» solo hay capturas en oscuro: no
existe un «antes en claro» porque ese panel no se podía ver en claro.

El «después» se toma del árbol de trabajo, con los tres temas.

Todo lo que sale de aquí es ficticio: dominios de la RFC 2606 y tokens
de mentira.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CLAVE = "clave-de-capturas-0123456789abcdef"
TOKEN_PANEL = "token-del-panel-0123456789abcdef"
HOST_PUBLICO = "mcp.example.com"
DOMINIO = "corp.example.com"
CUENTA = "ada@corp.example.com"
CUENTA_SIN_TOKEN = "grace@corp.example.com"
DOMINIO_SIN_TOKEN = "norte.example.net"
CUENTA_SIN_NINGUN_TOKEN = "heidi@norte.example.net"
BEARER_CUENTA = "token-de-la-cuenta-0123456789abcdef"
BEARER_DOMINIO = "token-del-dominio-0123456789abcdef"

#: El «antes» se saca de aquí: VYRA-32, sin selector de tema.
ANTES = Path("/tmp/vyra34-antes")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _preparar(origen: Path) -> str:
    """Levanta el panel de un árbol concreto y devuelve su dirección."""
    import uvicorn

    sys.path.insert(0, str(origen))
    try:
        from config import DashboardSettings
        from dashboard.app import crear_app
        from store.crypto import Cipher
        from store.db import Database
        from store.store import Store
        from tests.ayuda import ajustes
    finally:
        sys.path.pop(0)

    base_dir = Path(tempfile.mkdtemp(prefix="mcp-correo-capturas-"))
    base = Database(base_dir / "cuentas.db")
    base.prepare()
    settings = ajustes()
    store = Store(base, Cipher(CLAVE), settings)

    dominio_id = store.crear_dominio(
        {
            "name": DOMINIO,
            "label": "Corp",
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "bearer": BEARER_DOMINIO,
        }
    )
    store.crear_cuenta(
        {
            "name": CUENTA,
            "username": "ada",
            "domain_id": dominio_id,
            "password": "contrasena-de-prueba",
            "bearer": BEARER_CUENTA,
        }
    )
    store.crear_cuenta(
        {
            "name": CUENTA_SIN_TOKEN,
            "username": "grace",
            "domain_id": dominio_id,
            "password": "contrasena-de-prueba",
        }
    )
    store.cambiar_cuenta(store.cuenta_por_nombre(CUENTA_SIN_TOKEN).id, {"bearer": ""})
    dominio_sin_token = store.crear_dominio(
        {
            "name": DOMINIO_SIN_TOKEN,
            "label": "Norte",
            "imap_host": "imap.example.net",
            "smtp_host": "smtp.example.net",
        }
    )
    store.crear_cuenta(
        {
            "name": CUENTA_SIN_NINGUN_TOKEN,
            "username": "heidi",
            "domain_id": dominio_sin_token,
            "password": "contrasena-de-prueba",
        }
    )
    store.cambiar_cuenta(store.cuenta_por_nombre(CUENTA_SIN_NINGUN_TOKEN).id, {"bearer": ""})

    dashboard = DashboardSettings(
        enabled=True,
        db_path=str(base_dir / "cuentas.db"),
        key=CLAVE,
        token=TOKEN_PANEL,
        bind_host="127.0.0.1",
        bind_port=_puerto_libre(),
    )
    app = crear_app(dashboard, store, settings)
    puerto = dashboard.bind_port
    config = uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="warning")
    servidor = uvicorn.Server(config)
    threading.Thread(target=servidor.run, daemon=True).start()
    return f"http://127.0.0.1:{puerto}"


async def _abrir_acordeon(pagina) -> None:
    await pagina.evaluate(
        "() => { document.querySelectorAll('details').forEach((d) => { d.open = true; }); }"
    )
    await pagina.wait_for_timeout(150)


async def _capturar(url: str, destino: Path, tema: str | None, ancho: int, alto: int) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        navegador = await pw.chromium.launch()
        contexto = await navegador.new_context(
            permissions=["clipboard-read", "clipboard-write"],
            viewport={"width": ancho, "height": alto},
            color_scheme="dark",
        )
        pagina = await contexto.new_page()
        await pagina.goto(f"{url}/login")
        await pagina.fill("input[name='token']", TOKEN_PANEL)
        await pagina.click("button[type='submit']")
        await pagina.wait_for_selector(".cuenta", state="attached", timeout=15000)
        await _abrir_acordeon(pagina)
        if tema is not None:
            await pagina.click(f'[data-tema-opcion="{tema}"]')
            await pagina.wait_for_timeout(250)
        destino.parent.mkdir(parents=True, exist_ok=True)
        await pagina.screenshot(path=str(destino), full_page=True)
        await contexto.close()
        await navegador.close()


async def _main() -> int:
    destino = Path(os.environ.get("VYRA34_CAPTURAS", "/tmp/vyra34-capturas"))
    destino.mkdir(parents=True, exist_ok=True)

    # Cada fase se hace en un proceso aparte, con `--fase`. Los módulos
    # de Python se cachean por nombre: cargar el panel del «antes» y luego
    # el del «después» en el mismo proceso daría el «antes» dos veces,
    # sin que se note.
    fase = sys.argv[1] if len(sys.argv) > 1 else "todo"

    if fase in ("antes", "todo"):
        print("El «antes» (base 4992f46, modo oscuro único):")
        url_antes = _preparar(ANTES)
        for nombre, ancho, alto in (
            ("vyra34-antes-oscuro-escritorio.png", 1440, 1000),
            ("vyra34-antes-oscuro-movil.png", 390, 844),
        ):
            await _capturar(url_antes, destino / nombre, None, ancho, alto)
            print(f"  {destino / nombre}")

    if fase in ("despues", "todo"):
        print("El «después»:")
        url_despues = _preparar(ROOT)
        for tema in ("claro", "oscuro"):
            for etiqueta, ancho, alto in (("escritorio", 1440, 1000), ("movil", 390, 844)):
                nombre = f"vyra34-despues-{tema}-{etiqueta}.png"
                await _capturar(url_despues, destino / nombre, tema, ancho, alto)
                print(f"  {destino / nombre}")

        # --- el estado «Copiado», en los dos temas ------------------------
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            navegador = await pw.chromium.launch()
            contexto = await navegador.new_context(
                permissions=["clipboard-read", "clipboard-write"],
                viewport={"width": 1440, "height": 1000},
                color_scheme="dark",
            )
            pagina = await contexto.new_page()
            await pagina.goto(f"{url_despues}/login")
            await pagina.fill("input[name='token']", TOKEN_PANEL)
            await pagina.click("button[type='submit']")
            await pagina.wait_for_selector(".cuenta", state="attached", timeout=15000)
            await _abrir_acordeon(pagina)
            for tema in ("claro", "oscuro"):
                await pagina.click(f'[data-tema-opcion="{tema}"]')
                await pagina.wait_for_timeout(250)
                await pagina.click('button.copiar[data-copiar="token"]')
                await pagina.wait_for_timeout(350)
                nombre = f"vyra34-despues-copiado-{tema}-escritorio.png"
                await pagina.screenshot(path=str(destino / nombre), full_page=True)
                print(f"  {destino / nombre}")
            await contexto.close()
            await navegador.close()

    return 0


if __name__ == "__main__":
    os.environ.setdefault("MCP_PUBLIC_HOST", HOST_PUBLICO)
    sys.exit(asyncio.run(_main()))
