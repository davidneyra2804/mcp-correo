"""Comprobación del panel en un navegador real: tema y botones de copiar.

Arranca el panel con una base ficticia (dominios de la RFC 2606 y tokens
de mentira) y lo abre en Chromium, en escritorio y en móvil. Comprueba:

- que los tres temas (claro, oscuro y sistema) se ven distintos;
- que la elección persiste tras recargar;
- que en «sistema» el panel sigue al dispositivo;
- que los botones de copiar la URL y el token funcionan y el portapapeles
  recibe el valor;
- que se puede recorrer con el teclado.

No hay datos reales en ninguna parte: todo es de la RFC 2606.
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
DOMINIO_SIN_TOKEN = "norte.example.net"
CUENTA = "ada@corp.example.com"
CUENTA_SIN_TOKEN = "grace@corp.example.com"
CUENTA_SIN_NINGUN_TOKEN = "heidi@norte.example.net"
BEARER_CUENTA = "token-de-la-cuenta-0123456789abcdef"
BEARER_DOMINIO = "token-del-dominio-0123456789abcdef"


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _preparar() -> tuple[str, int]:
    """Levanta el panel en un hilo y devuelve su dirección."""
    import uvicorn
    from starlette.testclient import TestClient  # noqa: F401  (comprueba que importa)

    from config import DashboardSettings
    from dashboard.app import crear_app
    from store.accounts import DatabaseAccounts  # noqa: F401
    from store.crypto import Cipher
    from store.db import Database
    from store.store import Store
    from tests.ayuda import ajustes

    base_dir = Path(tempfile.mkdtemp(prefix="mcp-correo-panel-"))
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
    # Una cuenta con token propio, y otra sin él: la segunda se abre con
    # el de su dominio, que es el caso que trae VYRA-33.
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
    # Y la cuenta sin token propio se queda sin él.
    store.cambiar_cuenta(
        store.cuenta_por_nombre(CUENTA_SIN_TOKEN).id,
        {"bearer": ""},
    )
    # Y un segundo dominio sin ningún token, con una cuenta que tampoco
    # tiene: esa cuenta solo la abre el bearer general, así que no hay un
    # token que copiar. Es el caso que la interfaz tiene que decir con
    # honestidad en vez de prometer una copia que no va a funcionar.
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
    store.cambiar_cuenta(
        store.cuenta_por_nombre(CUENTA_SIN_NINGUN_TOKEN).id,
        {"bearer": ""},
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
    """Abre el acordeón del dominio, si está cerrado.

    Las cuentas viven dentro de un `<details>`: si el dominio no es el
    principal, viene cerrado y sus botones no se pueden pulsar.
    """
    await pagina.evaluate(
        """() => {
            document.querySelectorAll("details").forEach((d) => { d.open = true; });
        }"""
    )
    await pagina.wait_for_timeout(150)


async def _id_de(pagina, nombre_cuenta: str) -> str:
    """El identificador de la cuenta, buscado por su nombre visible."""
    return await pagina.evaluate(
        """(nombre) => {
            const filas = [...document.querySelectorAll(".cuenta")];
            const fila = filas.find((f) => f.textContent.includes(nombre));
            if (!fila) return "";
            const boton = fila.querySelector('button.copiar[data-copiar="token"]');
            return boton ? boton.dataset.cuenta : "";
        }""",
        nombre_cuenta,
    )


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
        # El portapapeles necesita permiso; en Chromium se concede por
        # contexto.
        contexto = await navegador.new_context(
            permissions=["clipboard-read", "clipboard-write"],
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

        # --- entrar en el panel ---------------------------------------------
        await pagina.goto(f"{url}/login")
        await pagina.fill("input[name='token']", TOKEN_PANEL)
        await pagina.click("button[type='submit']")
        await pagina.wait_for_selector(".cuenta", state="attached", timeout=15000)
        await _abrir_acordeon(pagina)
        print("\n[1] El panel carga y pinta las cuentas")

        # --- el tema oscuro por defecto --------------------------------------
        print("\n[2] El tema por defecto")
        fondo = await pagina.evaluate("getComputedStyle(document.body).backgroundColor")
        check(fondo == "rgb(12, 16, 23)", f"el fondo oscuro por defecto es {fondo}")

        # --- el selector de tema ---------------------------------------------
        print("\n[3] El selector de tema")
        opciones = await pagina.query_selector_all("[data-tema-opcion]")
        check(len(opciones) == 3, f"hay tres opciones de tema ({len(opciones)})")
        pressed = await pagina.evaluate(
            'document.querySelector(\'[data-tema-opcion="sistema"]\').getAttribute("aria-pressed")'
        )
        check(pressed == "true", f"«sistema» queda marcado (aria-pressed={pressed})")

        # --- cambiar a claro --------------------------------------------------
        print("\n[4] Cambiar a claro")
        await pagina.click('[data-tema-opcion="claro"]')
        await pagina.wait_for_timeout(250)
        fondo_claro = await pagina.evaluate("getComputedStyle(document.body).backgroundColor")
        texto_claro = await pagina.evaluate("getComputedStyle(document.body).color")
        check(
            fondo_claro == "rgb(244, 246, 251)",
            f"el fondo claro es {fondo_claro}",
        )
        check(texto_claro != "rgb(232, 237, 245)", f"el texto cambia a {texto_claro}")
        atributo = await pagina.evaluate("document.documentElement.getAttribute('data-tema')")
        check(atributo == "claro", f"el atributo data-tema es {atributo}")

        capturas.append(await guardar_captura(pagina, "vyra34-claro-escritorio.png"))

        # --- el tema persiste tras recargar ----------------------------------
        print("\n[5] La elección persiste tras recargar")
        await pagina.reload()
        await pagina.wait_for_selector(".cuenta", state="attached", timeout=15000)
        await _abrir_acordeon(pagina)
        atributo = await pagina.evaluate("document.documentElement.getAttribute('data-tema')")
        check(atributo == "claro", f"tras recargar sigue en claro ({atributo})")
        fondo = await pagina.evaluate("getComputedStyle(document.body).backgroundColor")
        check(fondo == "rgb(244, 246, 251)", f"el fondo sigue siendo claro ({fondo})")

        # --- copiar el token y la URL -----------------------------------------
        print("\n[6] Copiar el token y la URL")
        await pagina.click('[data-tema-opcion="oscuro"]')
        await pagina.wait_for_timeout(200)

        await pagina.click('button.copiar[data-copiar="token"]')
        await pagina.wait_for_timeout(400)
        texto_boton = await pagina.inner_text('button.copiar[data-copiar="token"]')
        check("Copiado" in texto_boton, f"el botón confirma «Copiado» ({texto_boton})")
        portapapeles = await pagina.evaluate("navigator.clipboard.readText()")
        check(
            portapapeles == BEARER_CUENTA,
            f"el portapapeles tiene el token de la cuenta ({portapapeles!r})",
        )

        await pagina.click('button.copiar[data-copiar="url"]')
        await pagina.wait_for_timeout(400)
        portapapeles = await pagina.evaluate("navigator.clipboard.readText()")
        check(
            portapapeles.endswith(f"/mcp/{CUENTA}"),
            f"el portapapeles tiene la URL de la cuenta ({portapapeles!r})",
        )

        # La cuenta sin token propio: lo que se copia es el de su dominio,
        # que es el que el servidor acepta para abrir su ruta.
        print("\n[6b] El token efectivo de una cuenta sin token propio")
        id_sin_token = await _id_de(pagina, CUENTA_SIN_TOKEN)
        check(bool(id_sin_token), f"la cuenta sin token propio tiene su botón ({id_sin_token})")
        if id_sin_token:
            await pagina.click(f'button.copiar[data-copiar="token"][data-cuenta="{id_sin_token}"]')
            await pagina.wait_for_timeout(400)
            portapapeles = await pagina.evaluate("navigator.clipboard.readText()")
            check(
                portapapeles == BEARER_DOMINIO,
                f"se copia el token del dominio, no uno vacío ({portapapeles!r})",
            )

        # --- la etiqueta del origen en la fila -------------------------------
        print("\n[6c] La fila dice de dónde sale el token")
        etiqueta_dominio = await pagina.evaluate(
            """(nombre) => {
                const filas = [...document.querySelectorAll(".cuenta")];
                const fila = filas.find((f) => f.textContent.includes(nombre));
                const e = fila && fila.querySelector(".origen-Token");
                return e ? e.textContent : "";
            }""",
            CUENTA_SIN_TOKEN,
        )
        check(
            etiqueta_dominio == "Token del dominio",
            f"la cuenta sin token propio lo dice en la fila ({etiqueta_dominio!r})",
        )
        etiqueta_propia = await pagina.evaluate(
            """(nombre) => {
                const filas = [...document.querySelectorAll(".cuenta")];
                const fila = filas.find((f) => f.textContent.includes(nombre));
                const e = fila && fila.querySelector(".origen-Token");
                return e ? e.textContent : "";
            }""",
            CUENTA,
        )
        check(
            etiqueta_propia == "",
            f"la cuenta con token propio no lleva etiqueta ({etiqueta_propia!r})",
        )

        # --- la cuenta que no tiene ningún token ----------------------------
        # Ni la cuenta ni su dominio tienen token: la cuenta solo la abre
        # el bearer general, que no es de esta cuenta. No hay un token que
        # copiar, y la interfaz tiene que decirlo en vez de prometer una
        # copia que no va a funcionar.
        print("\n[6d] La cuenta sin ningún token que copiar")
        id_sin_nada = await _id_de(pagina, CUENTA_SIN_NINGUN_TOKEN)
        check(bool(id_sin_nada), f"la cuenta sin token tiene su botón ({id_sin_nada})")
        if id_sin_nada:
            etiqueta = await pagina.evaluate(
                """(id) => {
                    const fila = document.querySelector(`.cuenta:has(button[data-cuenta="${id}"])`)
                        || document.querySelector(`button[data-cuenta="${id}"]`).closest(".cuenta");
                    const e = fila.querySelector(".origen-Token");
                    return e ? e.textContent : "";
                }""",
                id_sin_nada,
            )
            check(
                etiqueta == "Solo con el token general",
                f"la fila avisa de que no hay token que copiar ({etiqueta!r})",
            )
            # Y al pulsarlo, avisa en vez de decir «Copiado».
            await pagina.click(f'button.copiar[data-copiar="token"][data-cuenta="{id_sin_nada}"]')
            await pagina.wait_for_timeout(400)
            texto_boton = await pagina.inner_text(
                f'button.copiar[data-copiar="token"][data-cuenta="{id_sin_nada}"]'
            )
            check(
                "Copiado" not in texto_boton,
                f"no dice «Copiado» cuando no hay nada que copiar ({texto_boton})",
            )
            aviso = await pagina.inner_text("#aviso")
            check(
                "token general" in aviso,
                f"el aviso explica que solo se abre con el token general ({aviso!r})",
            )
            # Y el portapapeles no se ha tocado.
            portapapeles = await pagina.evaluate("navigator.clipboard.readText()")
            check(
                portapapeles == BEARER_DOMINIO,
                f"el portapapeles no se ha cambiado ({portapapeles!r})",
            )

        # --- el teclado llega a los botones -----------------------------------
        print("\n[7] El teclado")
        # El foco visible lo da `:focus-visible`, que solo se activa con el
        # teclado: hay que llegar al botón con el Tab, no con un
        # `element.focus()` de JavaScript.
        # Se busca el de una cuenta que **sí** tiene token: en la que solo
        # se abre con el bearer general no hay nada que copiar, y el botón
        # avisa de eso en vez de confirmar.
        id_con_token = await _id_de(pagina, CUENTA)
        check(bool(id_con_token), f"la cuenta con token tiene su botón ({id_con_token})")
        selector = f'button.copiar[data-copiar="token"][data-cuenta="{id_con_token}"]'
        await pagina.evaluate(
            """(sel) => {
                document.querySelector(sel).scrollIntoView({ block: "center" });
                document.body.focus();
            }""",
            selector,
        )
        # Se busca el botón con el teclado, desde el principio de la página.
        await pagina.keyboard.press("Tab")
        alcanzado = False
        for _ in range(80):
            activo = await pagina.evaluate(
                """(id) => {
                    const a = document.activeElement;
                    if (!a || !a.dataset) return "";
                    // Solo el botón de esta cuenta: hay varias, y en la que
                    // solo se abre con el bearer general no hay nada que
                    // copiar, así que su botón avisa en vez de confirmar.
                    return a.dataset.copiar === "token" && a.dataset.cuenta === id ? "token" : "";
                }""",
                id_con_token,
            )
            if activo == "token":
                alcanzado = True
                break
            await pagina.keyboard.press("Tab")
        check(alcanzado, "el botón de copiar se alcanza con el Tab")
        # El botón que tiene el foco tiene que ser el de la cuenta con
        # token: si es otro, el Enter no copia nada.
        en_foco = await pagina.evaluate(
            """() => {
                const a = document.activeElement;
                return a && a.dataset ? a.dataset.cuenta : "";
            }"""
        )
        check(
            en_foco == id_con_token,
            f"el foco está en el botón de la cuenta con token ({en_foco} vs {id_con_token})",
        )
        contorno = await pagina.evaluate(
            """() => {
                const e = getComputedStyle(document.activeElement);
                return e.outlineStyle !== "none" && parseFloat(e.outlineWidth) > 0;
            }"""
        )
        check(contorno, "el botón de copiar tiene foco visible con el teclado")
        # Y con Enter se copia. Se lee el botón que **tiene el foco**, que
        # no tiene por qué ser el primero: con varias cuentas, el Tab se
        # para en el primero que encuentra, y ese es el que hay que leer.
        await pagina.keyboard.press("Enter")
        await pagina.wait_for_timeout(400)
        texto_boton = await pagina.evaluate(
            """() => {
                const a = document.activeElement;
                return a && a.dataset && a.dataset.copiar ? a.textContent : "";
            }"""
        )
        check("Copiado" in texto_boton, f"con Enter también copia ({texto_boton})")
        # Y el portapapeles tiene el token de esa misma cuenta.
        portapapeles = await pagina.evaluate("navigator.clipboard.readText()")
        esperado = await pagina.evaluate(
            """() => {
                const a = document.activeElement;
                return a && a.dataset ? a.dataset.cuenta : "";
            }"""
        )
        check(
            portapapeles in (BEARER_CUENTA, BEARER_DOMINIO),
            f"con Enter se copia el token de esa cuenta ({portapapeles!r}, cuenta {esperado})",
        )

        # --- el error de portapapeles -----------------------------------------
        print("\n[8] El portapapeles que falla")
        await pagina.evaluate(
            """() => {
                Object.defineProperty(navigator, "clipboard", {
                    configurable: true,
                    get() { return { writeText: () => Promise.reject(new Error("denegado")) }; },
                });
                document.execCommand = () => false;
            }"""
        )
        await pagina.click('button.copiar[data-copiar="token"]')
        await pagina.wait_for_timeout(400)
        texto_boton = await pagina.inner_text('button.copiar[data-copiar="token"]')
        check(
            "Copiado" not in texto_boton,
            f"no dice «Copiado» cuando no se copió ({texto_boton})",
        )
        aviso = await pagina.inner_text("#aviso")
        check(
            "portapapeles" in aviso.lower(),
            f"el aviso explica que no se pudo ({aviso!r})",
        )

        # --- el tema oscuro, en escritorio y en móvil ------------------------
        print("\n[9] Capturas por tema y por tamaño")
        await pagina.reload()
        await pagina.wait_for_selector(".cuenta", state="attached", timeout=15000)
        await _abrir_acordeon(pagina)
        await pagina.click('[data-tema-opcion="oscuro"]')
        await pagina.wait_for_timeout(250)
        capturas.append(await guardar_captura(pagina, "vyra34-oscuro-escritorio.png"))
        await pagina.click('[data-tema-opcion="claro"]')
        await pagina.wait_for_timeout(250)
        capturas.append(await guardar_captura(pagina, "vyra34-claro-escritorio.png"))

        # --- el estado «Copiado», en los dos temas ---------------------------
        # Es la confirmación que ve la persona: el botón en verde y el
        # aviso visible. Sin esta captura no se ve que la copia funcionó.
        print("\n[9b] El estado «Copiado»")
        for tema in ("claro", "oscuro"):
            await pagina.click(f'[data-tema-opcion="{tema}"]')
            await pagina.wait_for_timeout(250)
            await pagina.click('button.copiar[data-copiar="token"]')
            await pagina.wait_for_timeout(350)
            estado = await pagina.inner_text('button.copiar[data-copiar="token"]')
            check("Copiado" in estado, f"el botón dice «Copiado» en {tema} ({estado})")
            capturas.append(await guardar_captura(pagina, f"vyra34-copiado-{tema}-escritorio.png"))
            # El aviso del panel es el que se anuncia: `role="status"`.
            papel = await pagina.get_attribute("#aviso", "role")
            check(papel == "status", f"el aviso es un «status» ({papel})")
            vivo = await pagina.get_attribute("#aviso", "aria-live")
            check(vivo == "polite", f"el aviso se anuncia en vivo ({vivo})")

        # Móvil.
        movil = await navegador.new_context(
            permissions=["clipboard-read", "clipboard-write"],
            viewport={"width": 390, "height": 844},
            color_scheme="dark",
        )
        pagina_movil = await movil.new_page()
        await pagina_movil.goto(f"{url}/login")
        await pagina_movil.fill("input[name='token']", TOKEN_PANEL)
        await pagina_movil.click("button[type='submit']")
        await pagina_movil.wait_for_selector(".cuenta", state="attached", timeout=15000)
        await _abrir_acordeon(pagina_movil)
        await pagina_movil.click('[data-tema-opcion="oscuro"]')
        await pagina_movil.wait_for_timeout(250)
        capturas.append(await guardar_captura(pagina_movil, "vyra34-oscuro-movil.png"))
        await pagina_movil.click('[data-tema-opcion="claro"]')
        await pagina_movil.wait_for_timeout(250)
        capturas.append(await guardar_captura(pagina_movil, "vyra34-claro-movil.png"))

        # --- el sistema manda cuando está en «sistema» -----------------------
        print("\n[10] El tema sistema sigue al dispositivo")
        # El contexto del navegador está en oscuro, así que en «sistema» el
        # panel tiene que verse en oscuro: es lo que manda el dispositivo.
        await pagina.evaluate(
            """() => {
                document.querySelector('[data-tema-opcion="sistema"]').click();
            }"""
        )
        await pagina.wait_for_timeout(250)
        atributo = await pagina.evaluate("document.documentElement.getAttribute('data-tema')")
        check(atributo is None, f"en «sistema» no hay atributo ({atributo})")
        fondo = await pagina.evaluate("getComputedStyle(document.body).backgroundColor")
        check(
            fondo == "rgb(12, 16, 23)",
            f"en «sistema» manda el dispositivo, que está en oscuro ({fondo})",
        )

        # Y si el dispositivo cambia de apariencia con el panel abierto, el
        # panel lo sigue sin recargar.
        await pagina.emulate_media(color_scheme="light")
        await pagina.wait_for_timeout(250)
        fondo = await pagina.evaluate("getComputedStyle(document.body).backgroundColor")
        check(
            fondo == "rgb(244, 246, 251)",
            f"el panel sigue al dispositivo en vivo, sin recargar ({fondo})",
        )
        await pagina.emulate_media(color_scheme="dark")
        await pagina.wait_for_timeout(200)

        # Con el tema elegido a mano, el dispositivo ya no manda.
        await pagina.click('[data-tema-opcion="claro"]')
        await pagina.wait_for_timeout(200)
        await pagina.emulate_media(color_scheme="dark")
        await pagina.wait_for_timeout(250)
        fondo = await pagina.evaluate("getComputedStyle(document.body).backgroundColor")
        check(
            fondo == "rgb(244, 246, 251)",
            f"con un tema elegido a mano, el dispositivo no manda ({fondo})",
        )
        await pagina.emulate_media(color_scheme="light")

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
    destino = Path(os.environ.get("VYRA34_CAPTURAS", "/tmp/vyra34-capturas"))
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / nombre
    await pagina.screenshot(path=str(ruta), full_page=True)
    return ruta


if __name__ == "__main__":
    os.environ.setdefault("MCP_PUBLIC_HOST", HOST_PUBLICO)
    sys.exit(asyncio.run(_comprobar()))
