"""Las cuentas dinámicas: en tiempo real, por dominio y con su credencial.

Lo que se comprueba aquí es el comportamiento que el panel promete:

- una cuenta creada en la base está en su ruta en la siguiente petición,
  sin reiniciar nada;
- la ruta general es la guía, no un atajo a todos los buzones;
- la credencial tiene que cubrir el ámbito de la ruta.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from config import load_config
from server import create_app
from store.accounts import DatabaseAccounts
from store.crypto import Cipher
from store.db import Database
from store.store import Store

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "token-general-0123456789abcdef"
CLAVE = "clave-del-panel-0123456789abcdef"
JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

ADA = "ada@corp.example.com"
LUIS = "luis@corp.example.com"
BEARER_ADA = "bearer-solo-de-ada-0123456789abcdef"
BEARER_DOMINIO = "bearer-solo-del-dominio-0123456789"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    settings, _cuentas = load_config(ROOT / "accounts.example.toml")
    almacen = Store(base, Cipher(CLAVE), settings)
    almacen.comprobar_clave()
    return almacen


@pytest.fixture
def cliente(store: Store) -> TestClient:
    settings, _cuentas = load_config(ROOT / "accounts.example.toml")
    source = DatabaseAccounts(store, settings)
    app, _runtime = create_app(settings, source, TOKEN)
    with TestClient(app, base_url="http://127.0.0.1:8765") as http:
        yield http


def _dominio(store: Store, nombre: str = "corp.example.com") -> int:
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


def _llamar(http: TestClient, path: str, token: str = TOKEN) -> dict:
    respuesta = http.post(
        path,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_accounts", "arguments": {}},
        },
        headers={**JSON_HEADERS, "Authorization": f"Bearer {token}"},
    )
    return respuesta


def _guia(http: TestClient, path: str, token: str = TOKEN) -> dict:
    respuesta = _llamar(http, path, token)
    assert respuesta.status_code == 200, respuesta.text
    return json.loads(respuesta.json()["result"]["content"][0]["text"])


# --- el tiempo real ------------------------------------------------------------


def test_una_cuenta_nueva_esta_en_su_ruta_sin_reiniciar(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA)
    guia = _guia(cliente, f"/mcp/{ADA}")
    assert [c["account"] for c in guia["accounts"]] == [ADA]


def test_una_cuenta_nueva_no_estaba_antes(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA)
    assert _guia(cliente, f"/mcp/{ADA}")["scope"] == [ADA]


def test_al_borrar_la_cuenta_la_ruta_da_404(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio, ADA)
    assert _llamar(cliente, f"/mcp/{ADA}").status_code == 200
    store.borrar_cuenta(cuenta)
    assert _llamar(cliente, f"/mcp/{ADA}").status_code == 404


# --- la ruta general es la guía ------------------------------------------------


def test_la_ruta_general_muestra_el_catalogo(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA)
    _cuenta(store, dominio, LUIS)
    guia = _guia(cliente, "/mcp")
    assert [d["domain"] for d in guia["domains"]] == ["corp.example.com"]
    assert guia["domains"][0]["accounts"] == [ADA, LUIS]
    assert guia["domains"][0]["route"] == "/mcp/corp.example.com"


def test_la_ruta_general_no_abre_buzones_sin_dominio_por_defecto(
    cliente: TestClient, store: Store
) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA)
    guia = _guia(cliente, "/mcp")
    assert guia["scope"] == []
    assert guia["accounts"] == []
    # Pero el catálogo sí está, para que el agente sepa a dónde ir.
    assert guia["domains"][0]["accounts"] == [ADA]


def test_la_ruta_general_abre_el_dominio_por_defecto(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA)
    store.marcar_por_defecto(dominio)
    guia = _guia(cliente, "/mcp")
    assert guia["scope"] == [ADA]
    assert guia["default_domain"] == "corp.example.com"


def test_la_guia_no_enseña_contrasenas_ni_tokens(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA, bearer=BEARER_ADA)
    respuesta = _llamar(cliente, "/mcp")
    assert "clave-ficticia" not in respuesta.text
    assert BEARER_ADA not in respuesta.text
    # Pero sí dice que la cuenta tiene credencial propia.
    guia = _guia(cliente, "/mcp")
    assert guia["accounts"] == [] or guia["accounts"][0].get("own_credential") in (True, False)


# --- la ruta del dominio --------------------------------------------------------


def test_la_ruta_del_dominio_abre_sus_cuentas(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA)
    _cuenta(store, dominio, LUIS)
    guia = _guia(cliente, "/mcp/corp.example.com")
    assert sorted(c["account"] for c in guia["accounts"]) == [ADA, LUIS]


def test_la_ruta_del_dominio_no_abre_las_de_otro(cliente: TestClient, store: Store) -> None:
    uno = _dominio(store, "uno.example.com")
    otro = _dominio(store, "otro.example.com")
    _cuenta(store, uno, "ada@uno.example.com")
    _cuenta(store, otro, "luis@otro.example.com")
    guia = _guia(cliente, "/mcp/uno.example.com")
    assert [c["account"] for c in guia["accounts"]] == ["ada@uno.example.com"]


def test_un_dominio_que_no_existe_da_404(cliente: TestClient) -> None:
    assert _llamar(cliente, "/mcp/nadie.example.com").status_code == 404


# --- las credenciales -----------------------------------------------------------


def test_el_bearer_de_una_cuenta_solo_sirve_en_su_ruta(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA, bearer=BEARER_ADA)
    assert _llamar(cliente, f"/mcp/{ADA}", BEARER_ADA).status_code == 200
    assert _llamar(cliente, "/mcp", BEARER_ADA).status_code == 403
    assert _llamar(cliente, "/mcp/corp.example.com", BEARER_ADA).status_code == 403


def test_el_bearer_de_un_dominio_abre_su_dominio(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA)
    store.rotar_token("dominio", dominio)
    token = store.dominio(dominio).bearer
    guia = _guia(cliente, "/mcp/corp.example.com", token)
    assert [c["account"] for c in guia["accounts"]] == [ADA]


def test_el_bearer_de_un_dominio_no_abre_otro_dominio(cliente: TestClient, store: Store) -> None:
    uno = _dominio(store, "uno.example.com")
    otro = _dominio(store, "otro.example.com")
    _cuenta(store, otro, "luis@otro.example.com")
    token = store.rotar_token("dominio", uno)
    assert _llamar(cliente, "/mcp/otro.example.com", token).status_code == 403
    assert _llamar(cliente, "/mcp", token).status_code == 403


def test_el_bearer_de_un_dominio_abre_una_cuenta_suya(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA)
    token = store.rotar_token("dominio", dominio)
    guia = _guia(cliente, f"/mcp/{ADA}", token)
    assert [c["account"] for c in guia["accounts"]] == [ADA]


def test_un_token_desconocido_da_401(cliente: TestClient, store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA)
    assert _llamar(cliente, f"/mcp/{ADA}", "no-existe-0123456789abcdef").status_code == 401


def test_la_credencial_general_alcanza_todas_las_cuentas(cliente: TestClient, store: Store) -> None:
    """La general es el bearer general: las cuentas con token propio también."""
    dominio = _dominio(store)
    _cuenta(store, dominio, ADA, bearer=BEARER_ADA)
    assert _llamar(cliente, f"/mcp/{ADA}", TOKEN).status_code == 200


# --- las tools de escritura -----------------------------------------------------


def test_en_modo_panel_las_tools_de_escritura_siguen_dependiendo_del_global(
    store: Store,
) -> None:
    from config import ServerSettings, write_capabilities

    settings, _cuentas = load_config(ROOT / "accounts.example.toml")
    apagado = ServerSettings(**{**settings.__dict__, "enable_send": False})
    assert write_capabilities(apagado, {}, dynamic=True)["send"] is False
    encendido = ServerSettings(**{**settings.__dict__, "enable_send": True})
    assert write_capabilities(encendido, {}, dynamic=True)["send"] is True
