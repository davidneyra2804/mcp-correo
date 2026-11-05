"""La integración de VYRA-33 con el panel de VYRA-32.

Las dos entregas aterrizaron a la vez sobre el mismo panel y tocaron los
mismos archivos. Esto vigila que lo que quedó sea coherente:

- la ruta de las credenciales es la misma en las dos formas de escribirla
  y devuelve lo mismo;
- la lectura devuelve la URL y el nombre de la cuenta, que es lo que
  necesita el botón de copiar la URL;
- el token que se copia es el efectivo, no uno vacío;
- renovar el token sigue siendo una operación aparte, y rota.

Los valores son de RFC 2606 (example.com), nunca reales.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from config import DashboardSettings, load_server_settings
from dashboard.app import crear_app
from store.crypto import Cipher
from store.db import Database
from store.store import Store

CLAVE = "clave-del-panel-ficticia-0123456789"
TOKEN_PANEL = "token-del-panel-ficticio-0123456789abcdef"

DOMINIO = "corp.example.com"
CUENTA = "ada@corp.example.com"
CUENTA_SIN_TOKEN = "grace@corp.example.com"

BEARER_CUENTA = "bearer-propio-ficticio-0123456789abcdef"
BEARER_DOMINIO = "bearer-de-dominio-ficticio-0123456789abcdef"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    settings = load_server_settings()
    almacen = Store(base, Cipher(CLAVE), settings)
    almacen.comprobar_clave()
    return almacen


@pytest.fixture
def panel(store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MCP_PUBLIC_HOST", "mcp.example.com")
    settings = load_server_settings()
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
        respuesta = http.post("/login", data={"token": TOKEN_PANEL}, follow_redirects=False)
        assert respuesta.status_code == 303, respuesta.text
        yield http


def _preparar(store: Store) -> int:
    """Un dominio con token y dos cuentas: una con token propio y otra sin."""
    dominio = store.crear_dominio({"name": DOMINIO, "bearer": BEARER_DOMINIO})
    store.crear_cuenta(
        {
            "name": CUENTA,
            "username": "ada",
            "domain_id": dominio,
            "password": "contrasena-ficticia",
            "bearer": BEARER_CUENTA,
        }
    )
    sin_token, _ = store.crear_cuenta(
        {
            "name": CUENTA_SIN_TOKEN,
            "username": "grace",
            "domain_id": dominio,
            "password": "contrasena-ficticia",
        }
    )
    # Se le quita su token propio: se queda con el de su dominio.
    store.cambiar_cuenta(sin_token, {"bearer": ""})
    return sin_token


def test_las_dos_rutas_dicen_lo_mismo(panel: TestClient, store: Store) -> None:
    """`/credenciales` y `/credentials` son la misma lectura.

    La primera es la que usa el panel; la segunda, la que usa la entrega
    de VYRA-33. Si divergieran, el panel dejaría de funcionar con una de
    las dos.
    """
    cuenta = _preparar(store)
    en_espanol = panel.get(f"/api/accounts/{cuenta}/credenciales")
    en_ingles = panel.get(f"/api/accounts/{cuenta}/credentials")

    assert en_espanol.status_code == 200, en_espanol.text
    assert en_ingles.status_code == 200, en_ingles.text
    assert en_espanol.json() == en_ingles.json()


def test_la_lectura_devuelve_la_url_de_la_cuenta(panel: TestClient, store: Store) -> None:
    """El botón de copiar la URL necesita la URL, y también el nombre.

    La URL es lo que se pega en un cliente MCP: con el host público y la
    ruta de la cuenta.
    """
    cuenta = _preparar(store)
    cuerpo = panel.get(f"/api/accounts/{cuenta}/credenciales").json()

    assert cuerpo["name"] == CUENTA_SIN_TOKEN
    assert cuerpo["url"] == f"https://mcp.example.com/mcp/{CUENTA_SIN_TOKEN}"


def test_el_token_que_se_copia_es_el_efectivo(panel: TestClient, store: Store) -> None:
    """La cuenta sin token propio copia el de su dominio, no uno vacío.

    Es el punto de VYRA-33: el token que el servidor acepta para esa
    cuenta es el de su dominio, así que es el que hay que copiar.
    """
    cuenta = _preparar(store)
    cuerpo = panel.get(f"/api/accounts/{cuenta}/credenciales").json()

    assert cuerpo["token"] == BEARER_DOMINIO
    assert cuerpo["origen"] == "dominio"
    assert cuerpo["has_token"] is True


def test_renovar_el_token_sigue_siendo_otra_cosa(panel: TestClient, store: Store) -> None:
    """Copiar no renueva, y renovar sigue_invalidando el anterior.

    Son dos operaciones distintas y no se pueden confundir: si el botón de
    copiar rotara, cada copia dejaría el token anterior sin servir.
    """
    cuenta = _preparar(store)

    antes = panel.get(f"/api/accounts/{cuenta}/credenciales").json()["token"]
    otro = panel.get(f"/api/accounts/{cuenta}/credenciales").json()["token"]
    assert antes == otro, "leer dos veces no cambia el token"

    renovado = panel.post(f"/api/accounts/{cuenta}/token", headers={"X-MCP-Dashboard": "1"})
    assert renovado.status_code == 200, renovado.text
    nuevo = renovado.json()["token"]
    assert nuevo != antes, "renovar genera un token distinto"

    # Y el token viejo ya no sirve.
    respuesta = panel.get(f"/api/accounts/{cuenta}/credenciales").json()
    assert respuesta["token"] == nuevo
