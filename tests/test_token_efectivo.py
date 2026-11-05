"""El token efectivo de una cuenta: el propio, o el de su dominio.

El panel promete que, si la cuenta no tiene token propio, se usa el de su
dominio. Estas pruebas comprueba, contra el servidor de verdad, que esa
promesa se sostiene: qué token acepta el servidor para cada cuenta, sin
rotar nada y sin que el valor acabe en la auditoría.

Los valores son de RFC 2606 (example.com / example.net), nunca reales.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx2 import Response
from starlette.testclient import TestClient

from config import DashboardSettings, load_server_settings
from dashboard.app import crear_app as crear_app_panel
from server import create_app
from store.accounts import DatabaseAccounts
from store.crypto import Cipher
from store.db import Database
from store.store import Store

ROOT = Path(__file__).resolve().parents[1]

# Valores ficticios de RFC 2606: nada de esto existe fuera de las pruebas.
TOKEN_GENERAL = "token-general-ficticio-0123456789abcdef"
TOKEN_PANEL = "token-del-panel-ficticio-0123456789abcdef"
CLAVE = "clave-del-panel-ficticia-0123456789"

DOMINIO = "corp.example.com"
OTRO_DOMINIO = "otro.example.net"

CUENTA_CON_TOKEN = "ada@corp.example.com"
CUENTA_SIN_TOKEN = "luis@corp.example.com"
CUENTA_DE_OTRO = "carla@otro.example.net"

#: Token propio de la cuenta: con credencial de dominio encima.
BEARER_CUENTA = "bearer-propio-ficticio-0123456789abcdef"

CSRF = {"X-MCP-Dashboard": "1"}

JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


@pytest.fixture
def store(tmp_path: Path) -> Store:
    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    settings = load_server_settings()
    almacen = Store(base, Cipher(CLAVE), settings)
    almacen.comprobar_clave()
    return almacen


@pytest.fixture
def cliente(store: Store) -> Iterator[TestClient]:
    """El servidor MCP, el que decide qué credencial abre qué ruta."""
    settings = load_server_settings()
    source = DatabaseAccounts(store, settings)
    app, _runtime = create_app(settings, source, TOKEN_GENERAL, database=store.db)
    with TestClient(app, base_url="http://127.0.0.1:8765") as http:
        yield http


@pytest.fixture
def panel(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    """El panel, con su sesión iniciada."""
    settings = load_server_settings()
    dashboard = DashboardSettings(
        enabled=True,
        db_path=str(tmp_path / "cuentas.db"),
        key=CLAVE,
        token=TOKEN_PANEL,
        bind_host="127.0.0.1",
        bind_port=8766,
    )
    app = crear_app_panel(dashboard, store, settings)
    with TestClient(app, base_url="http://127.0.0.1:8766") as http:
        respuesta = http.post("/login", data={"token": TOKEN_PANEL}, follow_redirects=False)
        assert respuesta.status_code == 303, respuesta.text
        yield http


def _dominio(store: Store, nombre: str = DOMINIO) -> int:
    return store.crear_dominio({"name": nombre})


def _cuenta(
    store: Store,
    dominio: int,
    nombre: str,
    usuario: str | None = None,
    **extra: object,
) -> int:
    cuerpo: dict[str, object] = {
        "domain_id": dominio,
        "name": nombre,
        "username": usuario or nombre,
        "password": "clave-ficticia",
        "imap_host": "imap.corp.example.com",
    }
    cuerpo.update(extra)
    identificador, _token = store.crear_cuenta(cuerpo)
    return identificador


def _quitar_token_propio(store: Store, identificador: int) -> None:
    """Deja la cuenta sin credencial propia, como el panel puede dejarla."""
    store.cambiar_cuenta(identificador, {"bearer": ""})


def _llamar(http: TestClient, path: str, token: str = TOKEN_GENERAL) -> Response:
    return http.post(
        path,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_accounts", "arguments": {}},
        },
        headers={**JSON_HEADERS, "Authorization": f"Bearer {token}"},
    )


def _guia(http: TestClient, path: str, token: str = TOKEN_GENERAL) -> dict:
    respuesta = _llamar(http, path, token)
    assert respuesta.status_code == 200, respuesta.text
    return json.loads(respuesta.json()["result"]["content"][0]["text"])


# --- el modelo: qué token acepta el servidor para cada cuenta --------------------


def test_la_cuenta_sin_token_propio_se_abre_con_el_del_dominio(
    cliente: TestClient, store: Store
) -> None:
    """El caso que la UI promete: sin token propio, el del dominio abre la ruta."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_SIN_TOKEN)
    _quitar_token_propio(store, cuenta)
    token_dominio = store.rotar_token("dominio", dominio)
    assert not store.cuenta(cuenta).bearer

    respuesta = _llamar(cliente, f"/mcp/{CUENTA_SIN_TOKEN}", token_dominio)

    assert respuesta.status_code == 200, respuesta.text
    guia = json.loads(respuesta.json()["result"]["content"][0]["text"])
    assert [c["account"] for c in guia["accounts"]] == [CUENTA_SIN_TOKEN]


def test_el_token_del_dominio_abre_su_ruta_de_cuenta_sin_credencial(
    cliente: TestClient, store: Store
) -> None:
    """Lo mismo, comprobado por la ruta del dominio: la cuenta está en ella."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_SIN_TOKEN)
    _quitar_token_propio(store, cuenta)
    token_dominio = store.rotar_token("dominio", dominio)

    guia = _guia(cliente, f"/mcp/{DOMINIO}", token_dominio)

    assert [c["account"] for c in guia["accounts"]] == [CUENTA_SIN_TOKEN]


def test_la_cuenta_con_token_propio_se_abre_con_el_suyo(cliente: TestClient, store: Store) -> None:
    """Control: con token propio, ese es el que vale."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_CON_TOKEN)
    registro = store.cuenta(cuenta)
    assert registro is not None
    token_cuenta = registro.bearer
    assert token_cuenta

    respuesta = _llamar(cliente, f"/mcp/{CUENTA_CON_TOKEN}", token_cuenta)

    assert respuesta.status_code == 200, respuesta.text
    guia = json.loads(respuesta.json()["result"]["content"][0]["text"])
    assert [c["account"] for c in guia["accounts"]] == [CUENTA_CON_TOKEN]


def test_el_token_de_la_cuenta_no_abre_otra_cuenta_del_mismo_dominio(
    cliente: TestClient, store: Store
) -> None:
    """El token propio es el más acotado: solo abre su cuenta."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_CON_TOKEN, bearer=BEARER_CUENTA)
    _cuenta(store, dominio, CUENTA_SIN_TOKEN)
    token_cuenta = store.cuenta(cuenta).bearer

    assert _llamar(cliente, f"/mcp/{CUENTA_CON_TOKEN}", token_cuenta).status_code == 200
    assert _llamar(cliente, f"/mcp/{CUENTA_SIN_TOKEN}", token_cuenta).status_code == 403


def test_el_token_del_dominio_no_abre_las_cuentas_de_otro_dominio(
    cliente: TestClient, store: Store
) -> None:
    """Aislamiento: el token de un dominio no cruza a otro dominio."""
    uno = _dominio(store, DOMINIO)
    otro = _dominio(store, OTRO_DOMINIO)
    _cuenta(store, otro, CUENTA_DE_OTRO)
    token_dominio = store.rotar_token("dominio", uno)

    assert _llamar(cliente, f"/mcp/{CUENTA_DE_OTRO}", token_dominio).status_code == 403


def test_el_token_de_dominio_no_abre_la_ruta_general(cliente: TestClient, store: Store) -> None:
    """La ruta general es la puerta de la credencial general."""
    dominio = _dominio(store)
    _cuenta(store, dominio, CUENTA_SIN_TOKEN)
    token_dominio = store.rotar_token("dominio", dominio)

    assert _llamar(cliente, "/mcp", token_dominio).status_code == 403


def test_sin_ningun_token_la_ruta_da_401(cliente: TestClient, store: Store) -> None:
    """Sin credencial no se entra: 401, no 403."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_SIN_TOKEN)
    _quitar_token_propio(store, cuenta)
    store.rotar_token("dominio", dominio)

    respuesta = _llamar(cliente, f"/mcp/{CUENTA_SIN_TOKEN}", "no-existe-0123456789abcdef")

    assert respuesta.status_code == 401


# --- el panel: el token que devuelve es el que el servidor acepta --------------


def test_el_panel_devuelve_el_token_efectivo_de_la_cuenta_sin_token_propio(
    panel: TestClient, cliente: TestClient, store: Store
) -> None:
    """``credenciales_cuenta()`` devuelve el del dominio si la cuenta no tiene."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_SIN_TOKEN)
    _quitar_token_propio(store, cuenta)
    token_dominio = store.rotar_token("dominio", dominio)

    respuesta = panel.get(f"/api/accounts/{cuenta}/credentials")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert cuerpo["token"] == token_dominio
    assert cuerpo["origen"] == "dominio"
    # El token que devuelve es el que el servidor acepta de verdad.
    assert _llamar(cliente, f"/mcp/{CUENTA_SIN_TOKEN}", cuerpo["token"]).status_code == 200


def test_el_panel_devuelve_el_token_propio_cuando_la_cuenta_lo_tiene(
    panel: TestClient, cliente: TestClient, store: Store
) -> None:
    """Control: con token propio, ese es el que devuelve."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_CON_TOKEN)
    registro = store.cuenta(cuenta)
    assert registro is not None
    token_cuenta = registro.bearer

    respuesta = panel.get(f"/api/accounts/{cuenta}/credentials")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["token"] == token_cuenta
    assert cuerpo["origen"] == "cuenta"
    assert _llamar(cliente, f"/mcp/{CUENTA_CON_TOKEN}", cuerpo["token"]).status_code == 200


def test_el_panel_no_inventa_un_token_sin_credencial(
    panel: TestClient, cliente: TestClient, store: Store
) -> None:
    """Sin token propio ni de dominio, la cuenta solo la abre el bearer general."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_SIN_TOKEN)
    _quitar_token_propio(store, cuenta)

    respuesta = panel.get(f"/api/accounts/{cuenta}/credentials")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["token"] == ""
    assert cuerpo["has_token"] is False
    assert cuerpo["origen"] == "general"
    # Y con el bearer general sí se entra: ese es el único que vale.
    assert _llamar(cliente, f"/mcp/{CUENTA_SIN_TOKEN}", TOKEN_GENERAL).status_code == 200


def test_el_panel_da_404_para_una_cuenta_que_no_existe(panel: TestClient) -> None:
    respuesta = panel.get("/api/accounts/999999/credentials")

    # 404 y no 400: lo que no existe es el recurso, no la petición. Es lo
    # que ya devolvía la ruta en español del panel.
    assert respuesta.status_code == 404
    assert "No existe esa cuenta" in respuesta.json()["error"]


# --- el listado: el panel dice de dónde sale la credencial ---------------------


def test_el_listado_dice_de_que_credencial_viene_cada_cuenta(
    panel: TestClient, store: Store
) -> None:
    """La UI necesita saberlo para no prometer una copia que no va a funcionar."""
    dominio = _dominio(store)
    _cuenta(store, dominio, CUENTA_CON_TOKEN, bearer=BEARER_CUENTA)
    sin_token = _cuenta(store, dominio, CUENTA_SIN_TOKEN)
    _quitar_token_propio(store, sin_token)
    store.rotar_token("dominio", dominio)

    respuesta = panel.get("/api/domains")
    assert respuesta.status_code == 200, respuesta.text
    cuentas = {c["name"]: c for c in respuesta.json()["domains"][0]["accounts"]}

    assert cuentas[CUENTA_CON_TOKEN]["credential_source"] == "cuenta"
    assert cuentas[CUENTA_CON_TOKEN]["has_credential"] is True
    assert cuentas[CUENTA_SIN_TOKEN]["credential_source"] == "dominio"
    assert cuentas[CUENTA_SIN_TOKEN]["has_credential"] is True


def test_el_listado_avisa_cuando_no_hay_credencial_que_copiar(
    panel: TestClient, store: Store
) -> None:
    """Sin token propio ni de dominio, la cuenta solo la abre el bearer general."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_SIN_TOKEN)
    _quitar_token_propio(store, cuenta)

    respuesta = panel.get("/api/domains")
    assert respuesta.status_code == 200, respuesta.text
    publicas = respuesta.json()["domains"][0]["accounts"]

    assert publicas[0]["credential_source"] == "general"
    assert publicas[0]["has_credential"] is False


# --- la auditoría: el valor no se escribe --------------------------------------


def test_la_auditoria_no_guarda_el_token(panel: TestClient, store: Store, tmp_path: Path) -> None:
    """Ni el token propio ni el del dominio acaban en el registro de auditoría."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_CON_TOKEN, bearer=BEARER_CUENTA)
    token_dominio = store.rotar_token("dominio", dominio)

    panel.get(f"/api/accounts/{cuenta}/credentials")

    registros = list(tmp_path.glob("*.jsonl"))
    for registro in registros:
        texto = registro.read_text(encoding="utf-8")
        assert BEARER_CUENTA not in texto
        assert token_dominio not in texto


def test_leer_el_panel_no_rota_el_token(panel: TestClient, store: Store) -> None:
    """Leer el token efectivo no cambia ninguna credencial."""
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, CUENTA_SIN_TOKEN)
    _quitar_token_propio(store, cuenta)
    token_dominio = store.rotar_token("dominio", dominio)

    panel.get(f"/api/accounts/{cuenta}/credentials")

    assert not store.cuenta(cuenta).bearer
    assert store.dominio(dominio).bearer == token_dominio
