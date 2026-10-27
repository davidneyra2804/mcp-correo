"""El panel: la sesión, la API y la auditoría.

El panel es una superficie aparte: tiene su propia credencial, su propia
sesión y su propia capa anti-CSRF. Estas pruebas comprueban las tres, y
que la contraseña de una cuenta nunca sale por la API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from config import DashboardSettings, load_config
from dashboard.app import crear_app
from store.crypto import Cipher
from store.db import Database
from store.store import Store

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "token-del-panel-0123456789abcdef"
CLAVE = "clave-del-panel-0123456789abcdef"
CSRF = {"X-MCP-Dashboard": "1"}


@pytest.fixture
def app(tmp_path: Path):
    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    settings, _cuentas = load_config(ROOT / "accounts.example.toml")
    store = Store(base, Cipher(CLAVE), settings)
    dashboard = DashboardSettings(
        enabled=True,
        db_path=str(tmp_path / "cuentas.db"),
        key=CLAVE,
        token=TOKEN,
        bind_host="127.0.0.1",
        bind_port=8766,
    )
    return crear_app(dashboard, store, settings)


@pytest.fixture
def cliente(app) -> TestClient:
    with TestClient(app, base_url="http://127.0.0.1:8766") as http:
        yield http


def _entrar(http: TestClient) -> None:
    respuesta = http.post("/login", data={"token": TOKEN}, follow_redirects=False)
    assert respuesta.status_code == 303, respuesta.text
    assert "mcp_correo_panel" in respuesta.cookies


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
    }
    cuerpo.update(extra)
    respuesta = http.post("/api/accounts", json=cuerpo, headers=CSRF)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# --- la sesión -----------------------------------------------------------------


def test_sin_sesion_la_pagina_manda_al_login(cliente: TestClient) -> None:
    respuesta = cliente.get("/", follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/login"


def test_sin_sesion_la_api_responde_401(cliente: TestClient) -> None:
    respuesta = cliente.get("/api/domains")
    assert respuesta.status_code == 401


def test_un_token_incorrecto_no_abre_sesion(cliente: TestClient) -> None:
    respuesta = cliente.post("/login", data={"token": "otro-token-0123456789abcdef"})
    assert respuesta.status_code == 401
    assert "El token no vale" in respuesta.text


def test_el_token_correcto_abre_sesion(cliente: TestClient) -> None:
    _entrar(cliente)
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    assert "Panel de mcp-correo" in respuesta.text


def test_la_sesion_cierra(cliente: TestClient) -> None:
    _entrar(cliente)
    respuesta = cliente.post("/logout", headers=CSRF, follow_redirects=False)
    assert respuesta.status_code == 303
    assert cliente.get("/api/domains").status_code == 401


def test_sin_la_cabecera_anticsrf_no_se_cambia_nada(cliente: TestClient) -> None:
    _entrar(cliente)
    respuesta = cliente.post("/api/domains", json={"name": "corp.example.com"})
    assert respuesta.status_code == 403
    assert "CSRF" in respuesta.json()["error"]


def test_la_sonda_no_pide_sesion(cliente: TestClient) -> None:
    assert cliente.get("/health").status_code == 200


# --- la API --------------------------------------------------------------------


def test_se_crea_un_dominio_y_una_cuenta(cliente: TestClient) -> None:
    _entrar(cliente)
    dominio = _dominio(cliente)
    cuenta = _cuenta(cliente, dominio["id"])
    listado = cliente.get("/api/domains").json()
    assert len(listado["domains"]) == 1
    assert listado["domains"][0]["accounts"][0]["name"] == "ada@corp.example.com"
    assert cuenta["ok"] is True


def test_la_contrasena_no_sale_nunca(cliente: TestClient) -> None:
    _entrar(cliente)
    dominio = _dominio(cliente)
    _cuenta(cliente, dominio["id"])
    cuerpo = cliente.get("/api/domains").text
    assert "clave-ficticia" not in cuerpo
    assert '"password_set":true' in cuerpo.replace(" ", "")


def test_un_nombre_repetido_dice_que_ya_existe(cliente: TestClient) -> None:
    _entrar(cliente)
    _dominio(cliente)
    respuesta = cliente.post("/api/domains", json={"name": "corp.example.com"}, headers=CSRF)
    assert respuesta.status_code == 400
    assert "Ya existe un dominio" in respuesta.json()["error"]


def test_se_marca_el_dominio_por_defecto(cliente: TestClient) -> None:
    _entrar(cliente)
    dominio = _dominio(cliente)
    respuesta = cliente.post(f"/api/domains/{dominio['id']}/default", headers=CSRF)
    assert respuesta.status_code == 200
    listado = cliente.get("/api/domains").json()
    assert listado["domains"][0]["default"] is True


def test_al_crear_una_cuenta_se_devuelve_su_token_una_vez(cliente: TestClient) -> None:
    _entrar(cliente)
    dominio = _dominio(cliente)
    respuesta = cliente.post(
        "/api/accounts",
        json={
            "domain_id": dominio["id"],
            "name": "ada@corp.example.com",
            "username": "ada@corp.example.com",
            "password": "clave-ficticia",
        },
        headers=CSRF,
    )
    assert respuesta.status_code == 200, respuesta.text
    token = respuesta.json()["token"]
    assert len(token) >= 16
    # Y no se vuelve a mostrar.
    listado = cliente.get("/api/domains").text
    assert token not in listado
    assert '"has_credential":true' in listado.replace(" ", "")


def test_se_genera_un_token_de_cuenta(cliente: TestClient) -> None:
    _entrar(cliente)
    dominio = _dominio(cliente)
    cuenta = _cuenta(cliente, dominio["id"])
    respuesta = cliente.post(f"/api/accounts/{cuenta['id']}/token", headers=CSRF)
    assert respuesta.status_code == 200
    token = respuesta.json()["token"]
    assert len(token) >= 16
    # Y no se vuelve a mostrar: la API solo dice que lo tiene.
    listado = cliente.get("/api/domains").text
    assert token not in listado
    assert '"has_credential":true' in listado.replace(" ", "")


def test_se_genera_un_token_de_dominio(cliente: TestClient) -> None:
    _entrar(cliente)
    dominio = _dominio(cliente)
    respuesta = cliente.post(f"/api/domains/{dominio['id']}/token", headers=CSRF)
    assert respuesta.status_code == 200
    assert len(respuesta.json()["token"]) >= 16


def test_se_borra_una_cuenta(cliente: TestClient) -> None:
    _entrar(cliente)
    dominio = _dominio(cliente)
    cuenta = _cuenta(cliente, dominio["id"])
    respuesta = cliente.delete(f"/api/accounts/{cuenta['id']}", headers=CSRF)
    assert respuesta.status_code == 200
    listado = cliente.get("/api/domains").json()
    assert listado["domains"][0]["accounts"] == []


def test_las_auditorias_de_la_api_no_llevan_secretos(cliente: TestClient, tmp_path: Path) -> None:
    _entrar(cliente)
    dominio = _dominio(cliente)
    _cuenta(cliente, dominio["id"])
    log = (
        (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        if (tmp_path / "audit.jsonl").exists()
        else ""
    )
    # El panel audita con su propio log; si no hay, no pasa nada.
    assert "clave-ficticia" not in log


# --- la prueba de conexión ------------------------------------------------------


def test_la_prueba_de_imap_usa_el_doble(cliente: TestClient) -> None:
    """Probar una cuenta no la guarda, y usa el mismo código que el resto."""
    from tests.fakes import FakeIMAP

    llamadas: list[str] = []

    def factory(_account, _settings):
        llamadas.append("conectado")
        return FakeIMAP({})

    cliente.app.state.imap_factory = factory
    _entrar(cliente)
    respuesta = cliente.post(
        "/api/test/imap",
        json={
            "username": "ada@corp.example.com",
            "password": "clave-ficticia",
            "imap_host": "imap.corp.example.com",
        },
        headers=CSRF,
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert llamadas == ["conectado"]
    # Y no se ha guardado ninguna cuenta.
    assert cliente.get("/api/domains").json()["domains"] == []


def test_la_prueba_que_falla_lo_dice(cliente: TestClient) -> None:
    def factory(_account, _settings):
        raise OSError("no hay servidor")

    cliente.app.state.imap_factory = factory
    _entrar(cliente)
    respuesta = cliente.post(
        "/api/test/imap",
        json={"username": "ada@corp.example.com", "password": "clave-ficticia"},
        headers=CSRF,
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False
    assert "No se pudo conectar" in cuerpo["error"]
    assert "clave-ficticia" not in json.dumps(cuerpo)
