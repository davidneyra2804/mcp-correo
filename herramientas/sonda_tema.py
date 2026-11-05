"""Comprobación rápida del tema en Chromium real.

No es la validación final: es una sonda para ver si la base del tema
funciona antes de invertir en las pruebas completas.

El panel se sirve por HTTP real (no `set_content`) porque `localStorage`
no está disponible en un documento `about:blank`.
"""

import http.server
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

PANEL = Path(__file__).resolve().parents[1] / "dashboard" / "static"


class Servidor(socketserver.TCPServer):
    allow_reuse_address = True


class Manejador(http.server.SimpleHTTPRequestHandler):
    """Sirve el panel bajo `/static/`, que es donde lo pide el HTML."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PANEL), **kwargs)

    def translate_path(self, path):
        ruta = super().translate_path(path)
        if "/static/" in ruta:
            return ruta.replace("/static", "", 1)
        return ruta

    def log_message(self, *args, **kwargs):
        """Silencio: el servidor solo existe para el navegador."""


def servir() -> tuple[Servidor, int]:
    servidor = Servidor(("127.0.0.1", 0), Manejador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    return servidor, servidor.server_address[1]


def main() -> int:
    servidor, puerto = servir()
    base = f"http://127.0.0.1:{puerto}"
    fallos = []
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            pagina = navegador.new_page(viewport={"width": 1440, "height": 1000})
            pagina.goto(f"{base}/static/panel.html")
            pagina.wait_for_timeout(300)
            for tema in ("claro", "oscuro", "sistema"):
                pagina.click(f'[data-tema-opcion="{tema}"]')
                pagina.wait_for_timeout(150)
                fondo = pagina.evaluate("getComputedStyle(document.body).backgroundColor")
                color = pagina.evaluate("getComputedStyle(document.body).color")
                esquema = pagina.evaluate("getComputedStyle(document.documentElement).colorScheme")
                attr = pagina.evaluate("document.documentElement.getAttribute('data-tema')")
                guardado = pagina.evaluate("localStorage.getItem('mcp-correo-tema')")
                marca = pagina.evaluate(
                    "document.querySelector('[data-tema-opcion].activo')?.dataset.temaOpcion"
                )
                print(
                    f"{tema:8} fondo={fondo:20} texto={color:20} scheme={esquema:6} "
                    f"attr={attr} guardado={guardado} activo={marca}"
                )
                if guardado != tema:
                    fallos.append(f"{tema}: no se guardó ({guardado})")
                if marca != tema:
                    fallos.append(f"{tema}: el selector no marca la opción ({marca})")
            navegador.close()
    finally:
        servidor.shutdown()
    if fallos:
        print("\nFALLOS:")
        for f in fallos:
            print(" -", f)
        return 1
    print("\nTema: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
