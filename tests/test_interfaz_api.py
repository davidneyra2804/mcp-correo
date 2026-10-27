"""La interfaz y la API no se pueden desincronizar.

La interfaz llama a la API por su cuenta. Si escribe mal una ruta, el
botón no hace nada y no hay ningun fallo visible: la pagina carga, el
cliente no se queja y el error aparece semanas despues, cuando alguien
intenta usar esa funcion.

Estos tests cierran ese hueco:

- Las rutas que usa el JavaScript existen en la aplicacion, con su metodo.
- Los botones tienen algo detras: si un boton no llama a nadie, sobra.
- Los campos de un formulario estan asociados a su input, para que
  pinchar en la etiqueta lleve al campo.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from config import load_config, load_dashboard_settings
from dashboard.app import crear_app, rutas_de_la_api
from store.crypto import Cipher
from store.db import Database
from store.store import Store

ROOT = Path(__file__).resolve().parents[1]
CSRF = {"X-MCP-Dashboard": "1"}
JS = ROOT / "dashboard" / "static" / "panel.js"
HTML = ROOT / "dashboard" / "static" / "panel.html"

#: Las llamadas que hace el JavaScript: /api/... con sus variables.
#: Se comparan con las rutas que declara la aplicacion.
_LLAMADA = re.compile(r"pedir\(\s*[`\"]([^`\"]+)[`\"]")
#: Una ruta de la API con sus huecos: {id}
_PLANTILLA = re.compile(r"^/api/[^/]+(?:/\{[^}]+\})?(?:/[a-z]+)?$")


@pytest.fixture
def cliente(tmp_path: Path) -> Iterator[TestClient]:
    settings, _cuentas = load_config(ROOT / "accounts.example.toml")
    dashboard = load_dashboard_settings()
    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    store = Store(base, Cipher(dashboard.key), settings)
    app = crear_app(dashboard, store, settings)
    with TestClient(app, base_url="http://127.0.0.1:8766") as http:
        yield http


@pytest.fixture
def rutas_api() -> set[tuple[str, str]]:
    """Las rutas de la API que declara la aplicación, con su método."""
    settings, _cuentas = load_config(ROOT / "accounts.example.toml")
    dashboard = load_dashboard_settings()
    base = Database(Path(tempfile.gettempdir()) / "mcp-correo-test-rutas.db")
    base.prepare()
    store = Store(base, Cipher(dashboard.key), settings)
    return rutas_de_la_api(crear_app(dashboard, store, settings))


def _llamadas_del_js() -> list[tuple[str, str]]:
    """Las llamadas que hace el JavaScript: (ruta, método)."""
    fuente = JS.read_text(encoding="utf-8")
    llamadas: list[tuple[str, str]] = []
    for ruta, resto in re.findall(r"pedir\(\s*[`\"]([^`\"]+)[`\"]([^)]*)\)", fuente, re.DOTALL):
        metodo = "GET"
        for candidato in ("POST", "PATCH", "DELETE", "PUT"):
            if f'method: "{candidato}"' in resto:
                metodo = candidato
                break
        llamadas.append((ruta, metodo))
    return llamadas


def _como_plantilla(ruta: str) -> str:
    """Una ruta con variables del JavaScript, como la que declara la API.

    El JavaScript escribe `/api/${recurso}/${id}/token`. La API declara
    `/api/domains/{id}/token`. La parte variable es el *recurso* (domains
    o accounts), y al compararlas no puede ser la misma: se comparan las
    partes fijas y la forma.
    """
    return re.sub(r"\$\{[^}]+\}", "{id}", ruta)


def _forma(ruta: str) -> tuple[str, ...]:
    """La forma de una ruta: sus partes, con las variables unificadas.

    `/api/${recurso}/${id}/token` queda como api, {var}, {var}, token, y
    `/api/domains/{id}/token` como api, domains, {var}, token. La variable
    del JavaScript puede ser el recurso, asi que se comparan las formas
    con las variables como comodines.
    """
    partes = []
    for parte in ruta.split("/"):
        if not parte:
            continue
        if parte.startswith("{") or parte.startswith("$"):
            partes.append("{var}")
        else:
            partes.append(parte)
    return tuple(partes)


def _encaja(forma_js: tuple[str, ...], forma_api: tuple[str, ...]) -> bool:
    """Si las dos formas encajan, tolerando variables por un lado o por otro."""
    if len(forma_js) != len(forma_api):
        return False
    for izquierda, derecha in zip(forma_js, forma_api, strict=True):
        if izquierda == "{var}" or derecha == "{var}":
            continue
        if izquierda != derecha:
            return False
    return True


def test_las_rutas_de_la_api_se_pueden_leer(rutas_api: set[tuple[str, str]]) -> None:
    """El test se apoya en leer las rutas de la aplicacion: que no falle."""
    assert rutas_api, "la aplicacion no declara ninguna ruta de API"


def test_toda_llamada_del_js_existe_en_la_api(rutas_api: set[tuple[str, str]]) -> None:
    """Cada llamada del JavaScript tiene que existir en la aplicación.

    Es el fallo que mas caro sale: la ruta mal escrita no da error, da
    silencio.
    """
    declaradas = rutas_api
    assert declaradas
    rotas: list[str] = []
    for ruta, metodo in _llamadas_del_js():
        forma = _forma(ruta)
        # La ruta tiene que existir con esa forma y ese metodo. La parte
        # variable (el recurso) la comprueba el test de recursos.
        if not any(
            _encaja(forma, _forma(declarada)) and m == metodo for declarada, m in declaradas
        ):
            rotas.append(f"{metodo} {ruta}")
    assert not rotas, "Llamadas del JavaScript que no existen en la API:\n  " + "\n  ".join(rotas)


def test_los_recursos_del_js_son_los_de_la_api(rutas_api: set[tuple[str, str]]) -> None:
    """Los recursos que nombra el JavaScript son los que declara la API.

    `/api/${recurso}/${id}/token` con `recurso` = "domains" o "accounts".
    Si uno de los dos nombres cambia, la llamada deja de existir y el
    botón deja de hacer nada, en silencio.
    """
    declarados = {ruta.split("/")[2] for ruta, _ in rutas_api}
    # El JavaScript pasa el recurso como argumento: rotar("domains", id).
    usados = set(re.findall(r'(?:rotar|borrar)\(\s*"([a-z]+)"', JS.read_text(encoding="utf-8")))
    assert usados, "el JavaScript no llama a un recurso variable"
    assert usados <= declarados, (
        f"Recursos que usa el JavaScript y no declara la API: {sorted(usados - declarados)}"
    )


def test_los_botones_del_html_tienen_accion() -> None:
    """Un botón sin acción es un botón que no hace nada.

    El HTML declara los botones del diálogo y de la cabecera; el
    JavaScript les engancha el comportamiento. Si un botón se queda sin
    enganchar, hay que verlo aquí.
    """
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    ids_de_boton = set(re.findall(r'<button[^>]*id="([a-z-]+)"', html))
    for identificador in sorted(ids_de_boton):
        assert f'#{identificador}"' in js, f"el botón #{identificador} no tiene acción"


def test_las_etiquetas_de_los_campos_estan_asociadas() -> None:
    """Cada etiqueta apunta a su campo: pinchar en ella lleva al campo.

    Sin el atributo `for`, el texto es decorativo y no hace nada al
    pincharlo. Es un detalle pequeño, pero es el que hace la Difference
    entre un formulario usable y uno que obliga a apuntar con el raton.
    """
    js = JS.read_text(encoding="utf-8")
    # La función campo() es la que crea las etiquetas.
    assert "label.htmlFor" in js, "las etiquetas no se asocian a su campo"
    assert "control.id" in js, "los campos no reciben un identificador"


def test_las_llamadas_del_js_llevan_la_cabecera_anticsrf() -> None:
    """Las peticiones que cambian algo llevan la cabecera anti-CSRF.

    Sin ella, el panel responde 403 y el botón no hace nada.
    """
    js = JS.read_text(encoding="utf-8")
    assert "X-MCP-Dashboard" in js
    # Todas las llamadas pasan por pedir(), que la pone siempre.
    assert "const CABECERA" in js


def test_los_subprocesos_usan_el_entorno_correcto() -> None:
    """Todo subproceso que importe el proyecto usa el entorno compartido.

    Sin PYTHONPATH, el subproceso no encuentra el modulo: con
    PYTHONSAFEPATH (Actions) eso es lo que pasa, y el test falla solo en
    CI. Y sin puerto propio, el panel choca con el del proceso de tests.

    El helper `entorno_de_subproceso` deja las dos cosas puestas. Aqui se
    comprueba que nadie se lo salta.
    """
    for fichero in sorted((ROOT / "tests").glob("test_*.py")):
        fuente = fichero.read_text(encoding="utf-8")
        if 'sys.executable, "-c"' not in fuente:
            continue
        assert "entorno_de_subproceso" in fuente, (
            f"{fichero.name} lanza un subproceso sin entorno_de_subproceso: "
            "le faltará PYTHONPATH y un puerto propio para el panel"
        )
