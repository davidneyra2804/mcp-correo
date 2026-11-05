"""La interfaz dice de dónde sale el token de cada cuenta.

Una cuenta del panel puede no tener credencial propia: la abre la de su
dominio. El token que se copia es ese, y **sí** sirve para abrir la
cuenta, pero quien configura un cliente MCP tiene que saberlo.

Estas pruebas comprueban dos cosas:

- La interfaz dice el origen del token antes de que se pulse nada, y no
  promete una copia que no va a funcionar.
- El botón de copiar usa el token **efectivo** que devuelve la API, y su
  aviso de fallo distingue el caso «no hay token» del resto.

Los valores son ficticios: dominios de la RFC 2606 y tokens de mentira.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from config import DashboardSettings
from dashboard.app import crear_app
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

HOST_PUBLICO = "mcp.example.com"
DOMINIO = "corp.example.com"


@pytest.fixture
def cliente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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


def _dominio(http: TestClient, nombre: str = DOMINIO, **extra: object) -> dict:
    cuerpo: dict[str, object] = {"name": nombre}
    cuerpo.update(extra)
    respuesta = http.post("/api/domains", json=cuerpo, headers=CSRF)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _cuenta(http: TestClient, dominio: int, nombre: str, **extra: object) -> dict:
    cuerpo: dict[str, object] = {
        "domain_id": dominio,
        "name": nombre,
        "username": nombre,
        "password": "clave-ficticia",
        "imap_host": "imap.corp.example.com",
        "smtp_host": "smtp.corp.example.com",
    }
    cuerpo.update(extra)
    respuesta = http.post("/api/accounts", json=cuerpo, headers=CSRF)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# --- el origen, en la API ------------------------------------------------------


def test_el_listado_dice_el_origen_de_cada_credencial(cliente: TestClient) -> None:
    """Cada cuenta del listado dice de dónde sale su token.

    Es lo que permite que la interfaz avise sin tener que pedir nada:
    quien mira la pantalla ya sabe qué va a pasar al pulsar el botón.
    """
    _entrar(cliente)
    dominio = _dominio(cliente)
    _cuenta(cliente, dominio["id"], "ada@corp.example.com")

    listado = cliente.get("/api/domains").json()
    cuenta = listado["domains"][0]["accounts"][0]
    assert cuenta["credential_source"] == "cuenta"
    assert cuenta["own_credential"] is True


def test_una_cuenta_sin_credencial_propia_dice_que_usa_la_del_dominio(
    cliente: TestClient,
) -> None:
    """Sin credencial propia, el origen es el dominio.

    Y `has_credential` sigue siendo cierto: hay un token que abre esta
    cuenta, que es lo que significa.
    """
    _entrar(cliente)
    dominio = _dominio(cliente, bearer="bearer-del-dominio-ficticio")
    cuenta = _cuenta(cliente, dominio["id"], "luis@corp.example.com")
    # Se le quita la credencial propia: el servidor la acepta vacía.
    respuesta = cliente.patch(f"/api/accounts/{cuenta['id']}", json={"bearer": ""}, headers=CSRF)
    assert respuesta.status_code == 200, respuesta.text

    listado = cliente.get("/api/domains").json()
    fila = listado["domains"][0]["accounts"][0]
    assert fila["credential_source"] == "dominio"
    assert fila["own_credential"] is False
    # Hay un token que abre esta cuenta: el del dominio.
    assert fila["has_credential"] is True


def test_una_cuenta_sin_ningun_token_avisa_que_no_hay_que_copiar(
    cliente: TestClient,
) -> None:
    """Ni la cuenta ni su dominio tienen token: no hay nada que copiar."""
    _entrar(cliente)
    dominio = _dominio(cliente)
    cuenta = _cuenta(cliente, dominio["id"], "luis@corp.example.com")
    cliente.patch(f"/api/accounts/{cuenta['id']}", json={"bearer": ""}, headers=CSRF)

    listado = cliente.get("/api/domains").json()
    fila = listado["domains"][0]["accounts"][0]
    assert fila["credential_source"] == "general"
    assert fila["has_credential"] is False


def test_la_ruta_de_credenciales_dice_el_origen_del_token(cliente: TestClient) -> None:
    """La ruta dice de dónde sale el token que devuelve.

    Sin esto, la interfaz no puede distinguir «no hay token» de «hay un
    token y el botón falló por otra cosa».
    """
    _entrar(cliente)
    dominio = _dominio(cliente, bearer="bearer-del-dominio-ficticio")
    cuenta = _cuenta(cliente, dominio["id"], "luis@corp.example.com")
    cliente.patch(f"/api/accounts/{cuenta['id']}", json={"bearer": ""}, headers=CSRF)

    cuerpo = cliente.get(f"/api/accounts/{cuenta['id']}/credenciales").json()
    assert cuerpo["origen"] == "dominio"
    assert cuerpo["has_token"] is True
    # Y el token es el del dominio, que es el que abre su ruta.
    assert cuerpo["token"] == "bearer-del-dominio-ficticio"


def test_sin_ningun_token_la_ruta_dice_que_no_hay(cliente: TestClient) -> None:
    """Sin token, la ruta lo dice con `has_token` en falso y origen general."""
    _entrar(cliente)
    dominio = _dominio(cliente)
    cuenta = _cuenta(cliente, dominio["id"], "luis@corp.example.com")
    cliente.patch(f"/api/accounts/{cuenta['id']}", json={"bearer": ""}, headers=CSRF)

    cuerpo = cliente.get(f"/api/accounts/{cuenta['id']}/credenciales").json()
    assert cuerpo["origen"] == "general"
    assert cuerpo["has_token"] is False
    assert cuerpo["token"] == ""


# --- la interfaz ----------------------------------------------------------------


def test_la_interfaz_usa_el_origen_para_explicar_el_boton() -> None:
    """La ayuda del botón depende del origen del token.

    Una cuenta sin credencial propia no es igual que una con ella: el
    token que se copia es el del dominio. Decirlo en la ayuda evita que
    quien configura un cliente piense que hay un token que se ha perdido.
    """
    bloque = JS[JS.index("function ayudaDelToken") : JS.index("/* Copia un valor al portapapeles")]
    assert "credential_source" in bloque
    assert '"dominio"' in bloque
    assert '"general"' in bloque
    # El texto del dominio explica que ese token abre su ruta.
    assert "abre" in bloque and "su ruta" in bloque


def test_el_boton_de_token_pide_la_ayuda_segun_el_origen() -> None:
    """El botón de copiar el token usa esa ayuda, no una fija."""
    bloque = JS[JS.index("function pintarCuenta") : JS.index("function botonCopiar")]
    assert 'botonCopiar(cuenta, "token"' in bloque
    assert "ayuda: ayudaDelToken(cuenta)" in bloque


def test_la_fila_enseña_de_donde_sale_el_token() -> None:
    """Se ve en la fila, sin tener que pasar el ratón por encima.

    La etiqueta solo aparece cuando el token no es el de la cuenta: si
    lo tiene, no hay nada que aclarar y la fila se queda limpia.
    """
    bloque = JS[JS.index("function pintarCuenta") : JS.index("function botonCopiar")]
    assert "credential_source" in bloque
    assert "Token del dominio" in bloque
    assert "Solo con el token general" in bloque


def test_el_aviso_de_sin_token_es_el_verdadero() -> None:
    """El fallo distingue el caso «no hay token» del resto.

    El texto anterior («usa el de su dominio») era falso con el backend
    nuevo: el token del dominio sí se copia. Y para el caso general, el
    aviso tiene que decirlo.
    """
    bloque = JS[
        JS.index("async function copiar") : JS.index("async function escribirEnElPortapapeles")
    ]
    assert "cuerpo.origen" in bloque
    assert '"general"' in bloque
    assert "solo se abre con el token general" in bloque
    # El texto viejo, que prometía una copia que sí existe, no puede quedar.
    assert "no tiene token propio: usa el de su dominio" not in bloque


def test_la_etiqueta_del_origen_usa_las_variables_del_tema() -> None:
    """La etiqueta nueva se ve bien en los dos temas."""
    bloque = CSS[CSS.index(".origen-Token {") :]
    bloque = bloque[: bloque.index("\n}")]
    assert "var(--aviso-suave)" in bloque
    assert "var(--texto-aviso)" in bloque
    # Y el caso sin token, con su propia clase.
    assert ".origen-Token.sin-token" in CSS
    assert "var(--fondo-3)" in CSS
