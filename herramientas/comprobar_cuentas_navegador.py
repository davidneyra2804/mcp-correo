"""Comprobación del editor de cuentas y del menú de «más opciones».

Arranca el panel con una base ficticia (dominios de la RFC 2606 y tokens
de mentira) y lo abre en Chromium. Comprueba:

- que «Cancelar» cierra el modal «Añadir cuenta» sin errores ni envíos;
- que el menú de tres puntos se ve entero, sin recorte por el contenedor;
- que guardar una cuenta válida sigue funcionando.

No hay datos reales en ninguna parte: todo es de la RFC 2606.

Playwright no está en `requirements-dev.txt`: la suite de tests no lo
necesita y meterlo ahí ralentiza cada instalación, la de CI incluida. Va
aparte:

    .venv/bin/pip install -r requirements-browser.txt
    .venv/bin/playwright install chromium
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CLAVE = "clave-de-comprobacion-0123456789abcdef"
TOKEN_PANEL = "token-del-panel-0123456789abcdef"
HOST_PUBLICO = "mcp.example.com"
DOMINIO = "corp.example.com"
CUENTA = "ada@corp.example.com"
BEARER_CUENTA = "token-de-la-cuenta-0123456789abcdef"
BEARER_DOMINIO = "token-del-dominio-0123456789abcdef"


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _preparar() -> tuple[str, int]:
    """Levanta el panel en un hilo y devuelve su dirección."""
    import uvicorn

    from config import DashboardSettings
    from dashboard.app import crear_app
    from store.crypto import Cipher
    from store.db import Database
    from store.store import Store
    from tests.ayuda import ajustes

    base_dir = Path(tempfile.mkdtemp(prefix="mcp-correo-cuentas-"))
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
    # Varias cuentas más: el menú de tres puntos se recortaba según dónde
    # cayera la cuenta dentro del bloque del dominio, y con una sola no
    # se alcanzaba el caso que lo reproducía.
    for indice in range(1, 5):
        store.crear_cuenta(
            {
                "name": f"persona{indice}@corp.example.com",
                "username": f"persona{indice}",
                "domain_id": dominio_id,
                "password": "contrasena-de-prueba",
            }
        )

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
    import threading

    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    return f"http://127.0.0.1:{puerto}", puerto


async def _abrir_acordeon(pagina) -> None:
    await pagina.evaluate(
        """() => {
            document.querySelectorAll("details").forEach((d) => { d.open = true; });
        }"""
    )
    await pagina.wait_for_timeout(150)


async def _comprobar() -> int:
    from playwright.async_api import async_playwright

    url, _ = _preparar()
    fallos: list[str] = []
    capturas: list[Path] = []

    def check(condicion: bool, mensaje: str) -> None:
        if not condicion:
            fallos.append(mensaje)
            print(f"  FALLO: {mensaje}")
        else:
            print(f"  ok: {mensaje}")

    async with async_playwright() as pw:
        navegador = await pw.chromium.launch()
        contexto = await navegador.new_context(
            viewport={"width": 1440, "height": 1000},
            color_scheme="dark",
        )
        pagina = await contexto.new_page()
        errores: list[str] = []
        pagina.on("pageerror", lambda e: errores.append(str(e)))
        pagina.on(
            "console",
            lambda m: errores.append(m.text) if m.type == "error" else None,
        )
        peticiones: list[str] = []
        pagina.on(
            "request",
            lambda r: (
                peticiones.append(f"{r.method} {r.url}")
                if r.method == "POST" and "/api/" in r.url
                else None
            ),
        )

        await pagina.goto(f"{url}/login")
        await pagina.fill("input[name='token']", TOKEN_PANEL)
        await pagina.click("button[type='submit']")
        await pagina.wait_for_selector(".cuenta", state="attached", timeout=15000)
        await _abrir_acordeon(pagina)

        # --- el modal «Añadir cuenta» y su Cancelar --------------------------
        print("\n[1] «Añadir cuenta»: abrir, cancelar y cerrar")
        await pagina.click("#nueva-cuenta")
        await pagina.wait_for_timeout(300)
        abierto = await pagina.evaluate('document.querySelector("#editor").open')
        check(abierto, f"el modal se abre (open={abierto})")

        titulo = await pagina.inner_text("#titulo")
        check("Añadir cuenta" in titulo, f"el título es «Añadir cuenta» ({titulo!r})")

        peticiones.clear()
        await pagina.click('#formulario button[value="cancelar"]')
        await pagina.wait_for_timeout(500)
        abierto_tras = await pagina.evaluate('document.querySelector("#editor").open')
        check(not abierto_tras, f"el modal se cierra al cancelar (open={abierto_tras})")
        check(
            not [p for p in peticiones if "/api/accounts" in p],
            f"no se envía nada al cancelar (POST: {peticiones})",
        )
        resultado = await pagina.inner_text("#resultado")
        check(not resultado.strip(), f"no queda un error de validación ({resultado!r})")
        capturas.append(await guardar_captura(pagina, "vyra45-modal-cancelado.png"))

        # --- el menú de tres puntos ------------------------------------------
        print("\n[2] El menú de tres puntos: visible y sin recorte")
        # Se revisa el menú de cada cuenta: el recorte dependía de dónde
        # cayera la cuenta dentro del bloque del dominio, así que una sola
        # no basta para verlo.
        disparadores = await pagina.query_selector_all(".cuenta .menu-envoltorio > button.menu")
        check(len(disparadores) >= 1, f"hay menús de tres puntos ({len(disparadores)})")
        for indice in range(len(disparadores)):
            await disparadores[indice].click()
            await pagina.wait_for_timeout(250)
            estado = await pagina.evaluate(
                """(i) => {
                    const filas = [...document.querySelectorAll(".cuenta")];
                    const fila = filas[i];
                    const lista = fila.querySelector(".menu-lista");
                    if (!lista || lista.hidden) return { abierto: false };
                    const r = lista.getBoundingClientRect();
                    const entradas = [...lista.querySelectorAll('[role="menuitem"]')].map((b) => {
                        const c = b.getBoundingClientRect();
                        const encima = document.elementFromPoint(
                            c.left + c.width / 2, c.top + c.height / 2);
                        return {
                            texto: b.textContent,
                            visible: c.top >= 0 && c.bottom <= window.innerHeight
                                     && c.left >= 0 && c.right <= window.innerWidth,
                            alcanzable: encima === b || b.contains(encima),
                        };
                    });
                    // ¿Algún ancestro con `overflow` recorta el menú?
                    const cortadores = [];
                    let n = lista.parentElement;
                    while (n && n !== document.body) {
                        const estilo = getComputedStyle(n);
                        if (estilo.overflow !== "visible") {
                            const c = n.getBoundingClientRect();
                            cortadores.push({
                                sel: n.tagName + "." + n.className,
                                fuera: r.bottom > c.bottom || r.top < c.top
                                       || r.right > c.right || r.left < c.left,
                            });
                        }
                        n = n.parentElement;
                    }
                    return {
                        abierto: true,
                        total: entradas.length,
                        fuera: entradas.filter((e) => !e.visible).map((e) => e.texto),
                        inalcanzables: entradas.filter((e) => !e.alcanzable).map((e) => e.texto),
                        recortadores: cortadores.filter((c) => c.fuera).map((c) => c.sel),
                    };
                }""",
                indice,
            )
            check(estado.get("abierto"), f"el menú {indice} se abre")
            if estado.get("abierto"):
                check(
                    not estado["fuera"],
                    f"el menú {indice} se ve entero ({estado['fuera']} fuera de la ventana)",
                )
                check(
                    not estado["inalcanzables"],
                    f"el menú {indice} es pulsable ({estado['inalcanzables']} con algo encima)",
                )
                check(
                    not estado["recortadores"],
                    f"el menú {indice} no lo recorta ningún contenedor ({estado['recortadores']})",
                )
            await pagina.keyboard.press("Escape")
            await pagina.wait_for_timeout(150)
        capturas.append(await guardar_captura(pagina, "vyra45-menu-abierto.png"))

        # --- cerrar el menú y guardar una cuenta válida ----------------------
        print("\n[3] Cerrar el menú y guardar una cuenta válida")
        await pagina.keyboard.press("Escape")
        await pagina.wait_for_timeout(300)
        oculto = await pagina.evaluate(
            """() => {
                const lista = document.querySelector(".cuenta .menu-lista");
                return lista ? lista.hidden : null;
            }"""
        )
        check(oculto is True, f"el menú se cierra con Escape (hidden={oculto})")

        peticiones.clear()
        await pagina.click("#nueva-cuenta")
        await pagina.wait_for_timeout(300)
        await pagina.fill('#campos input[type="email"]', "nuevo@example.com")
        await pagina.fill('#campos input[type="password"]', "contrasena-de-prueba")
        await pagina.click('#formulario button[value="guardar"]')
        await pagina.wait_for_timeout(1200)
        cerrada = await pagina.evaluate('document.querySelector("#editor").open')
        check(not cerrada, f"el modal se cierra tras guardar (open={cerrada})")
        check(
            any("/api/accounts" in p for p in peticiones),
            f"la cuenta se envía al servidor (POST: {peticiones})",
        )
        await pagina.wait_for_timeout(500)
        await _abrir_acordeon(pagina)
        hay = await pagina.evaluate(
            """() => document.body.textContent.includes("nuevo@example.com")"""
        )
        check(hay, "la cuenta nueva aparece en el panel")
        capturas.append(await guardar_captura(pagina, "vyra45-cuenta-guardada.png"))

        await contexto.close()
        await navegador.close()

    print("\n=== errores de JavaScript en la consola ===")
    if errores:
        for error in errores:
            print(f"  {error}")
        fallos.append(f"{len(errores)} errores de JavaScript en la consola")
    else:
        print("  ninguno")

    print("\n=== capturas ===")
    for captura in capturas:
        print(f"  {captura}")

    print("\n=== resultado ===")
    if fallos:
        print(f"{len(fallos)} fallos:")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    print("Todo correcto.")
    return 0


async def guardar_captura(pagina, nombre: str) -> Path:
    destino = Path(os.environ.get("VYRA45_CAPTURAS", "/tmp/vyra45-capturas"))
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / nombre
    await pagina.screenshot(path=str(ruta), full_page=True)
    return ruta


if __name__ == "__main__":
    os.environ.setdefault("MCP_PUBLIC_HOST", HOST_PUBLICO)
    sys.exit(asyncio.run(_comprobar()))
