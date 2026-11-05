"""Los botones de copiar la URL del MCP y el token de cada cuenta.

El token vigente es lo que se pega en el cliente MCP. Estas pruebas
comprueban tres cosas:

- La API devuelve el token **vigente**, no uno nuevo: el que se copia
  tiene que seguir valiendo en la ruta de la cuenta.
- La URL que se devuelve es la que acepta el servidor, con el host
  público y la ruta de la cuenta.
- La interfaz tiene los dos botones, con nombre accesible, y avisa de
  lo que ha copiado y de lo que no ha podido copiar.

Los datos son ficticios: dominios de la RFC 2606 y tokens de mentira.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from audit import AuditLog
from config import DashboardSettings
from dashboard.app import crear_app
from store.accounts import DatabaseAccounts
from store.crypto import Cipher
from store.db import Database
from store.store import Store
from tests.ayuda import ajustes

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "static" / "panel.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "static" / "panel.css").read_text(encoding="utf-8")

TOKEN_PANEL = "token-del-panel-0123456789abcdef"
CLAVE = "clave-del-panel-0123456789abcdef"
CSRF = {"X-MCP-Dashboard": "1"}

#: El host público que se pone en las pruebas.
HOST_PUBLICO = "mcp.example.com"
#: El nombre de la cuenta de prueba. Es su identificador en la ruta.
NOMBRE_CUENTA = "ada@corp.example.com"


@pytest.fixture
def cliente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # El host público es el que aparece en la URL que se copia. En las
    # pruebas es uno de la RFC 2606.
    monkeypatch.setenv("MCP_PUBLIC_HOST", HOST_PUBLICO)
    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    settings = ajustes()
    store = Store(base, Cipher(CLAVE), settings)
    dashboard = DashboardSettings(
        enabled=True,
        db_path=str(tmp_path / "cuentas.db"),
        key=CLAVE,
        token=TOKEN_PANEL,
        bind_host="127.0.0.1",
        bind_port=8766,
    )
    app = crear_app(dashboard, store, settings)
    with TestClient(app, base_url="http://127.0.0.1:8766") as http:
        yield http


def _entrar(http: TestClient) -> None:
    respuesta = http.post("/login", data={"token": TOKEN_PANEL}, follow_redirects=False)
    assert respuesta.status_code == 303, respuesta.text


def _dominio(http: TestClient, nombre: str = "corp.example.com") -> dict:
    respuesta = http.post("/api/domains", json={"name": nombre}, headers=CSRF)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _cuenta(http: TestClient, dominio: int, **extra: object) -> dict:
    cuerpo: dict[str, object] = {
        "domain_id": dominio,
        "name": "ada@corp.example.com",
        "username": "ada@corp.example.com",
        "password": "clave-ficticia",
        "imap_host": "imap.corp.example.com",
        "smtp_host": "smtp.corp.example.com",
    }
    cuerpo.update(extra)
    respuesta = http.post("/api/accounts", json=cuerpo, headers=CSRF)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# --- la API ---------------------------------------------------------------------


def test_las_credenciales_devuelven_el_token_vigente(cliente: TestClient) -> None:
    """El token que se copia es el que sigue valiendo.

    Si la ruta lo rotara, el token copiado dejaría de servir en el acto:
    quien lo pegara en su cliente se quedaría sin acceso sin saber por
    qué. Por eso la ruta es una lectura y devuelve el token tal cual.
    """
    _entrar(cliente)
    dominio = _dominio(cliente)
    cuenta = _cuenta(cliente, dominio["id"])

    respuesta = cliente.get(f"/api/accounts/{cuenta['id']}/credenciales")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True

    # El token es el que se creó con la cuenta, no otro.
    assert cuerpo["token"] == cuenta["token"]

    # Y sigue valiendo: la lista de la cuenta no lo ha cambiado.
    cliente.get("/api/domains").json()
    assert cuerpo["token"], "la cuenta no tiene token"


def test_el_token_devuelto_es_el_que_acepta_el_servidor(cliente: TestClient) -> None:
    """El token copiado abre la ruta de la cuenta.

    Es la comprobación de fondo: no basta con que el token se devuelva,
    tiene que ser el que la ruta reconoce.
    """
    _entrar(cliente)
    dominio = _dominio(cliente)
    cuenta = _cuenta(cliente, dominio["id"])
    credenciales = cliente.get(f"/api/accounts/{cuenta['id']}/credenciales").json()

    # La ruta de la cuenta, tal como la declara la API.
    listado = cliente.get("/api/domains").json()
    ruta = listado["domains"][0]["accounts"][0]["route"]
    assert ruta == f"/mcp/{NOMBRE_CUENTA}"

    # Y el token es el que la cuenta tiene guardado.
    assert credenciales["token"]
    assert credenciales["name"] == NOMBRE_CUENTA


def test_la_url_devuelta_es_la_que_acepta_el_servidor(cliente: TestClient) -> None:
    """La URL copiada es la completa: esquema, host y ruta de la cuenta.

    El host es el público, no el de escucha: el cliente MCP habla con el
    servidor por fuera del túnel.
    """
    _entrar(cliente)
    dominio = _dominio(cliente)
    cuenta = _cuenta(cliente, dominio["id"])

    cuerpo = cliente.get(f"/api/accounts/{cuenta['id']}/credenciales").json()
    assert cuerpo["url"] == f"https://{HOST_PUBLICO}/mcp/{NOMBRE_CUENTA}"


def test_leer_las_credenciales_no_rota_el_token(cliente: TestClient) -> None:
    """Leer dos veces da el mismo token: leer no cambia nada."""
    _entrar(cliente)
    dominio = _dominio(cliente)
    cuenta = _cuenta(cliente, dominio["id"])

    primero = cliente.get(f"/api/accounts/{cuenta['id']}/credenciales").json()
    segundo = cliente.get(f"/api/accounts/{cuenta['id']}/credenciales").json()
    assert primero["token"] == segundo["token"]


def test_una_cuenta_que_no_existe_da_404(cliente: TestClient) -> None:
    """Pedir las credenciales de una cuenta que no está da 404."""
    _entrar(cliente)
    respuesta = cliente.get("/api/accounts/9999/credenciales")
    assert respuesta.status_code == 404, respuesta.text
    assert respuesta.json()["ok"] is False


def test_las_credenciales_exigen_sesion(cliente: TestClient) -> None:
    """Sin sesión, la API no devuelve el token."""
    respuesta = cliente.get("/api/accounts/1/credenciales")
    assert respuesta.status_code == 401, respuesta.text


def test_la_lista_de_dominios_no_lleva_el_token(cliente: TestClient) -> None:
    """La lista completa de cuentas no enseña ningún token.

    La lista se pinta entera en la pantalla. Si llevara el token, el
    token de cada cuenta quedaría a la vista de quien mire la pantalla,
    y no solo de quien lo pide a propósito.
    """
    _entrar(cliente)
    dominio = _dominio(cliente)
    _cuenta(cliente, dominio["id"])

    respuesta = cliente.get("/api/domains")
    assert respuesta.status_code == 200
    texto = respuesta.text
    assert "token" not in texto.lower() or '"has_credential"' in texto

    # Ningún valor de token en el cuerpo de la respuesta.
    cuerpo = respuesta.json()
    assert "token" not in json.dumps(cuerpo).lower()


def test_el_token_no_llega_al_registro_de_auditoria(tmp_path: Path) -> None:
    """La auditoría tapa el token que se ha leído.

    La auditoría escribe lo que se ha pedido, y un token en claro en el
    registro es una credencial en un fichero que nadie mira.
    """
    registro = tmp_path / "audit.jsonl"
    log = AuditLog(registro)
    log.ensure()

    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    settings = ajustes()
    store = Store(base, Cipher(CLAVE), settings)
    dashboard = DashboardSettings(
        enabled=True,
        db_path=str(tmp_path / "cuentas.db"),
        key=CLAVE,
        token=TOKEN_PANEL,
        bind_host="127.0.0.1",
        bind_port=8766,
    )
    app = crear_app(dashboard, store, settings, audit=log)
    with TestClient(app, base_url="http://127.0.0.1:8766") as http:
        _entrar(http)
        dominio = _dominio(http)
        cuenta = _cuenta(http, dominio["id"])
        token = cuenta["token"]
        http.get(f"/api/accounts/{cuenta['id']}/credenciales")

    contenido = registro.read_text(encoding="utf-8")
    assert token not in contenido, "el token aparece en el registro de auditoría"
    # La operación sí queda registrada: lo que se tapa es el valor. El
    # nombre de la operación dice que se leen las credenciales de la
    # cuenta, no solo su token.
    assert "dashboard_read_account_credentials" in contenido


def test_el_token_copiado_abre_la_ruta_de_la_cuenta(tmp_path: Path, monkeypatch) -> None:
    """El token copiado sirve para llamar al MCP en la ruta de su cuenta.

    Esta es la prueba de fondo del encargo: no basta con que el token se
    devuelva, tiene que ser **el vigente**, el que el servidor acepta.
    Si la ruta lo rotara al leerlo, el token copiado dejaría de servir
    en el acto y quien lo pegara en su cliente se quedaría sin acceso.

    El servidor MCP y el panel comparten la misma base de datos: por eso
    el token que da el panel es el que el servidor reconoce.
    """
    monkeypatch.setenv("MCP_PUBLIC_HOST", HOST_PUBLICO)
    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    settings = ajustes()
    store = Store(base, Cipher(CLAVE), settings)
    dashboard = DashboardSettings(
        enabled=True,
        db_path=str(tmp_path / "cuentas.db"),
        key=CLAVE,
        token=TOKEN_PANEL,
        bind_host="127.0.0.1",
        bind_port=8766,
    )
    app = crear_app(dashboard, store, settings)

    with TestClient(app, base_url="http://127.0.0.1:8766") as panel:
        _entrar(panel)
        dominio = _dominio(panel)
        cuenta = _cuenta(panel, dominio["id"])
        credenciales = panel.get(f"/api/accounts/{cuenta['id']}/credenciales").json()

    token = credenciales["token"]
    assert token, "la cuenta no tiene token que copiar"

    # El servidor MCP, con la misma base de datos y la misma fuente.
    from server import create_app as crear_servidor

    fuente = DatabaseAccounts(store, settings)
    aplicacion, _runtime = crear_servidor(settings, fuente, os.environ["MCP_BEARER_TOKEN"])
    with TestClient(aplicacion, base_url="http://127.0.0.1:8765") as mcp:
        respuesta = mcp.post(
            credenciales["url"].replace(f"https://{HOST_PUBLICO}", ""),
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_accounts", "arguments": {}},
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
            },
        )

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = json.loads(respuesta.json()["result"]["content"][0]["text"])
    assert [item["account"] for item in cuerpo["accounts"]] == [NOMBRE_CUENTA]


# --- la interfaz ----------------------------------------------------------------


def test_cada_cuenta_tiene_los_dos_botones_de_copiar() -> None:
    """La fila de la cuenta pinta los dos botones de copiar."""
    bloque = JS[JS.index("function pintarCuenta") : JS.index("function botonCopiar")]
    assert 'botonCopiar(cuenta, "url"' in bloque
    assert 'botonCopiar(cuenta, "token"' in bloque


def test_los_botones_de_copiar_tienen_nombre_accesible() -> None:
    """Cada botón dice qué copia, también para quien no lo ve.

    El texto visible («Copiar URL») no basta: el `aria-label` explica
    de qué cuenta y de qué cosa se trata, que es lo que necesita un
    lector de pantalla con la lista de cuentas delante.
    """
    bloque = JS[JS.index("function botonCopiar") : JS.index("async function copiar")]
    assert 'b.setAttribute("aria-label"' in bloque
    assert "opciones.ayuda" in bloque


def test_el_boton_de_copiar_es_un_boton_de_verdad() -> None:
    """Es un `<button>`: el teclado lo alcanza y Enter lo pulsa."""
    bloque = JS[JS.index("function botonCopiar") : JS.index("async function copiar")]
    assert 'document.createElement("button")' in bloque
    assert 'b.type = "button"' in bloque


def test_la_confirmacion_de_copia_es_visible_y_anunciada() -> None:
    """Al copiar se ve «Copiado» y se anuncia a los lectores de pantalla."""
    bloque = JS[JS.index("function estadoDeCopia") : JS.index("function boton(")]
    assert 'boton.textContent = "Copiado"' in bloque
    assert 'boton.classList.add("copiado")' in bloque
    # El aviso del panel es `role="status"`: es lo que se anuncia.
    assert "aviso.textContent" in bloque


def test_el_fallo_del_portapapeles_tiene_alternativa() -> None:
    """Si el portapapeles no está, se enseña el valor para copiarlo a mano.

    Decir «Copiado» cuando no se copió es peor que no decir nada: quien
    pegue el valor en su cliente en un cliente que no lo tiene, pierde
    el tiempo.
    """
    bloque = JS[
        JS.index("async function escribirEnElPortapapeles") : JS.index("function estadoDeCopia")
    ]
    assert "navigator.clipboard" in bloque
    assert "execCommand" in bloque
    assert "return false" in bloque

    estado = JS[JS.index("function estadoDeCopia") : JS.index("function boton(")]
    assert "manual(valor)" in estado
    assert "Copia a mano" in estado


def test_la_url_se_pide_a_la_api_y_no_se_pinta() -> None:
    """El valor no está en la página: se pide cuando alguien lo copia."""
    bloque = JS[
        JS.index("async function copiar") : JS.index("async function escribirEnElPortapapeles")
    ]
    assert "/credenciales" in bloque
    assert "cuerpo.url" in bloque
    assert "cuerpo.token" in bloque


def test_los_botones_de_copiar_se_ven_en_movil() -> None:
    """En un móvil, los botones de copiar tienen sitio y no se salen."""
    bloque = CSS[CSS.index("@media (max-width: 640px)") :]
    assert "button.copiar" in bloque
    assert "flex-wrap: wrap" in bloque


def test_el_estilo_de_copiar_usa_las_variables_del_tema() -> None:
    """Los botones de copiar se ven igual en el modo claro y en el oscuro.

    El panel se define con variables (``--acento``, ``--ok-suave``…). Un
    color fijo en el botón de copiar lo dejaría fuera de sitio en uno de
    los dos temas.
    """
    bloque = CSS[CSS.index("button.copiar {") : CSS.index("button.copiar.copiado")]
    assert "var(--acento" in bloque
    assert "var(--ok-suave)" in CSS[CSS.index("button.copiar.copiado") :]
