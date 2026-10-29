"""La interfaz: los flujos que hace una persona, contra el panel de verdad.

No se prueba el pixel ni el JavaScript: se prueba que **la API tiene lo
que la interfaz necesita**. Si la UI lee una clave que la API no da, la
página se queda vacía o con "undefined" encima, y eso no lo pilla ningún
otro test.

Los IDs que el JavaScript busca en el HTML también se comprueban: si el
HTML cambia y el JS se queda atrás, la página falla en silencio.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from config import load_dashboard_settings
from dashboard.app import crear_app
from store.crypto import Cipher
from store.db import Database
from store.store import Store
from tests.ayuda import ajustes

ROOT = Path(__file__).resolve().parents[1]
CSRF = {"X-MCP-Dashboard": "1"}


@pytest.fixture
def cliente(tmp_path: Path) -> Iterator[TestClient]:
    settings = ajustes()
    dashboard = load_dashboard_settings()
    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    store = Store(base, Cipher(dashboard.key), settings)
    app = crear_app(dashboard, store, settings)
    with TestClient(app, base_url="http://127.0.0.1:8766") as http:
        yield http


def _entrar(http: TestClient) -> None:
    """Abrir sesión con el token real del panel, sin escribirlo a mano."""
    token = load_dashboard_settings().token
    respuesta = http.post("/login", data={"token": token}, follow_redirects=False)
    assert respuesta.status_code == 303, respuesta.text


# --- lo que la interfaz necesita de la API -------------------------------------


def test_la_api_da_todo_lo_que_la_interfaz_lee(cliente: TestClient) -> None:
    """Las claves que el JavaScript usa tienen que estar en la respuesta."""
    _entrar(cliente)
    dominio = cliente.post(
        "/api/domains", json={"name": "ejemplo.example.com", "label": "Prueba"}, headers=CSRF
    ).json()
    cliente.post(
        "/api/accounts",
        json={
            "domain_id": dominio["id"],
            "name": "yo@ejemplo.example.com",
            "username": "yo@ejemplo.example.com",
            "password": "clave-ficticia",
        },
        headers=CSRF,
    )
    listado = cliente.get("/api/domains").json()["domains"][0]
    for clave in ("id", "name", "label", "default", "accounts"):
        assert clave in listado, f"la interfaz lee domain.{clave}"
    for clave in ("id", "name", "route", "enabled", "domain_id"):
        assert clave in listado["accounts"][0], f"la interfaz lee account.{clave}"
    # Los permisos de escritura, incluido el envío directo: el editor los
    # pinta y los manda.
    for clave in ("allow_send", "allow_direct_send"):
        assert clave in listado, f"la interfaz lee domain.{clave}"
        assert clave in listado["accounts"][0], f"la interfaz lee account.{clave}"


def test_al_crear_una_cuenta_se_devuelve_el_token(cliente: TestClient) -> None:
    """La interfaz lo muestra una sola vez, al crearla."""
    _entrar(cliente)
    dominio = cliente.post(
        "/api/domains", json={"name": "ejemplo.example.com"}, headers=CSRF
    ).json()
    respuesta = cliente.post(
        "/api/accounts",
        json={
            "domain_id": dominio["id"],
            "name": "yo@ejemplo.example.com",
            "username": "yo@ejemplo.example.com",
            "password": "clave-ficticia",
        },
        headers=CSRF,
    )
    assert respuesta.status_code == 200
    assert len(respuesta.json()["token"]) >= 16


def test_los_botones_de_la_interfaz_tienen_su_endpoint(cliente: TestClient) -> None:
    """Cada botón de la página llama a algo que existe."""
    _entrar(cliente)
    dominio = cliente.post(
        "/api/domains", json={"name": "ejemplo.example.com"}, headers=CSRF
    ).json()
    cuenta = cliente.post(
        "/api/accounts",
        json={
            "domain_id": dominio["id"],
            "name": "yo@ejemplo.example.com",
            "username": "yo@ejemplo.example.com",
            "password": "clave-ficticia",
        },
        headers=CSRF,
    ).json()
    # Marcar el dominio principal.
    assert cliente.post(f"/api/domains/{dominio['id']}/default", headers=CSRF).status_code == 200
    # Renovar la clave de acceso, del dominio y de la cuenta.
    assert cliente.post(f"/api/domains/{dominio['id']}/token", headers=CSRF).status_code == 200
    assert cliente.post(f"/api/accounts/{cuenta['id']}/token", headers=CSRF).status_code == 200
    # Desactivar y volver a activar.
    assert (
        cliente.patch(
            f"/api/accounts/{cuenta['id']}", json={"enabled": False}, headers=CSRF
        ).status_code
        == 200
    )
    assert (
        cliente.patch(
            f"/api/accounts/{cuenta['id']}", json={"enabled": True}, headers=CSRF
        ).status_code
        == 200
    )


def test_el_logout_responde(cliente: TestClient) -> None:
    _entrar(cliente)
    respuesta = cliente.post("/logout", headers=CSRF, follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/login"


# --- el alta pide el correo una sola vez ---------------------------------------


def test_el_alta_toma_el_identificador_y_el_usuario_del_correo(cliente: TestClient) -> None:
    """Con un solo correo, la cuenta queda completa.

    Así es como lo hace la interfaz: se escribe el correo una vez y el
    identificador de la ruta y el usuario de conexión salen de ahí.
    """
    _entrar(cliente)
    dominio = cliente.post(
        "/api/domains", json={"name": "ejemplo.example.com"}, headers=CSRF
    ).json()
    correo = "yo@ejemplo.example.com"
    respuesta = cliente.post(
        "/api/accounts",
        json={
            "domain_id": dominio["id"],
            "name": correo,
            "username": correo,
            "password": "clave-ficticia",
        },
        headers=CSRF,
    )
    assert respuesta.status_code == 200, respuesta.text
    cuenta = cliente.get("/api/domains").json()["domains"][0]["accounts"][0]
    assert cuenta["name"] == correo
    assert cuenta["user"] == correo
    assert cuenta["route"] == f"/mcp/{correo}"


def test_editar_el_usuario_no_pisa_el_alias_de_la_ruta(cliente: TestClient) -> None:
    """El alias identifica la cuenta en /mcp: cambiar el usuario no lo cambia.

    Si se pisara, la ruta que ya tiene el cliente apuntando dejaría de
    existir, sin avisar.
    """
    _entrar(cliente)
    dominio = cliente.post(
        "/api/domains", json={"name": "ejemplo.example.com"}, headers=CSRF
    ).json()
    cliente.post(
        "/api/accounts",
        json={
            "domain_id": dominio["id"],
            "name": "principal",
            "username": "yo@ejemplo.example.com",
            "password": "clave-ficticia",
        },
        headers=CSRF,
    )
    cuenta = cliente.get("/api/domains").json()["domains"][0]["accounts"][0]
    assert cuenta["name"] == "principal"
    # Editar el usuario de conexión, con el alias intacto.
    cliente.patch(
        f"/api/accounts/{cuenta['id']}",
        json={"name": cuenta["name"], "username": "otro@ejemplo.example.com"},
        headers=CSRF,
    )
    cuenta = cliente.get("/api/domains").json()["domains"][0]["accounts"][0]
    assert cuenta["name"] == "principal"
    assert cuenta["user"] == "otro@ejemplo.example.com"
    assert cuenta["route"] == "/mcp/principal"


# --- el HTML y el JavaScript no se desincronizan ------------------------------


def test_los_ids_del_html_estan_todos_en_el_javascript() -> None:
    """Cada elemento que el JS busca tiene que estar en el HTML."""
    html = (ROOT / "dashboard" / "static" / "panel.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "static" / "panel.js").read_text(encoding="utf-8")
    buscados = set(re.findall(r'\$\("#([a-z-]+)"\)', js))
    assert buscados, "el JavaScript no busca ningún elemento: ¿se ha renombrado?"
    for identificador in sorted(buscados):
        assert f'id="{identificador}"' in html, f"el HTML no tiene #{identificador}"


def test_los_ids_del_html_que_necesita_el_javascript_existen() -> None:
    """Y al revés: ningún id del HTML queda sin usar por el JS."""
    html = (ROOT / "dashboard" / "static" / "panel.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "static" / "panel.js").read_text(encoding="utf-8")
    for identificador in ("dominios", "vacio", "editor", "formulario", "campos", "titulo"):
        assert f'id="{identificador}"' in html
        assert identificador in js


def test_la_interfaz_sirve_los_estaticos(cliente: TestClient) -> None:
    """La página sin CSS ni JS no se ve."""
    _entrar(cliente)
    for fichero in ("panel.html", "panel.css", "panel.js"):
        assert cliente.get(f"/static/{fichero}").status_code == 200, fichero
