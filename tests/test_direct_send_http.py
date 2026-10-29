"""El envío directo por HTTP, con el panel y las cuentas de verdad.

Esta es la prueba que reproduce el caso de uso: un agente que llama una
sola vez a una ruta de cuenta y recibe el correo enviado. Sin red y sin
buzón real: el IMAP y el SMTP son dobles, pero el servidor, el panel, la
base y el enrutado son los de verdad.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from audit import AuditLog
from config import DashboardSettings, ServerSettings, load_server_settings
from server import create_app
from store.accounts import DatabaseAccounts
from store.crypto import Cipher
from store.db import Database
from store.store import Store
from tests.fakes import FakeSMTP, sample_mailbox

TOKEN = "token-general-de-prueba-0123456789abcdef"
CLAVE = "clave-del-panel-de-prueba-0123456789abcdef"
CUENTA = "ada@corp.example.com"

JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


@pytest.fixture
def cliente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeSMTP]:
    monkeypatch.setenv("MCP_ENABLE_DIRECT_SEND", "true")
    settings: ServerSettings = load_server_settings()
    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    store = Store(base, Cipher(CLAVE), settings)
    store.comprobar_clave()
    dominio = store.crear_dominio({"name": "corp.example.com"})
    store.crear_cuenta(
        {
            "domain_id": dominio,
            "name": CUENTA,
            "username": CUENTA,
            "password": "clave-ficticia",
            "imap_host": "imap.corp.example.com",
            "allow_direct_send": True,
        }
    )
    source = DatabaseAccounts(store, settings)
    smtp = FakeSMTP()
    audit = AuditLog(tmp_path / "audit.jsonl")
    # El IMAP también es un doble: la copia en Enviados usa APPEND.
    _fake, _service, _cuenta = sample_mailbox(with_trash=True, with_drafts=True)
    application, _runtime = create_app(
        settings,
        source,
        TOKEN,
        audit=audit,
        client_factory=lambda _a, _s: _fake,
        smtp_factory=lambda _a, _s: smtp,
        database=base,
        store=store,
        dashboard=DashboardSettings(
            enabled=True,
            db_path=str(tmp_path / "cuentas.db"),
            key=CLAVE,
            token="token-del-panel-de-prueba-0123456789abcdef",
        ),
    )
    with TestClient(application, base_url="http://127.0.0.1:8765") as http:
        yield http, smtp


def _llamar(http: TestClient, nombre: str, argumentos: dict, ruta: str = "/mcp") -> dict:
    respuesta = http.post(
        ruta,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": nombre, "arguments": argumentos},
        },
        headers={**JSON_HEADERS, "Authorization": f"Bearer {TOKEN}"},
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    return json.loads(cuerpo["result"]["content"][0]["text"])


def test_una_sola_llamada_envia_el_correo(cliente: tuple[TestClient, FakeSMTP]) -> None:
    """El agente llama una vez y el correo sale: sin confirmation_id."""
    http, smtp = cliente
    resultado = _llamar(
        http,
        "send_message_direct",
        {
            "account": CUENTA,
            "to": ["ana@example.com"],
            "subject": "Pendiente Trello-42",
            "body": "Detalle del pendiente",
            "idempotency_key": "trello-42",
        },
        ruta=f"/mcp/{CUENTA}",
    )
    assert resultado["sent"] is True
    assert resultado["status"] == "sent"
    assert resultado["duplicate"] is False
    assert resultado["message_id"]
    assert len(smtp.sent) == 1


def test_la_ruta_por_cuenta_no_necesita_saber_el_alias(
    cliente: tuple[TestClient, FakeSMTP],
) -> None:
    """En `/mcp/<cuenta>` el `account` es opcional: lo dice la ruta."""
    http, smtp = cliente
    resultado = _llamar(
        http,
        "send_message_direct",
        {
            "to": ["ana@example.com"],
            "subject": "Sin alias",
            "body": "Cuerpo",
            "idempotency_key": "trello-43",
        },
        ruta=f"/mcp/{CUENTA}",
    )
    assert resultado["sent"] is True
    assert len(smtp.sent) == 1


def test_el_reintento_no_duplica_el_correo(cliente: tuple[TestClient, FakeSMTP]) -> None:
    """La misma clave, dos llamadas: un solo correo."""
    http, smtp = cliente
    argumentos = {
        "account": CUENTA,
        "to": ["ana@example.com"],
        "subject": "Pendiente Trello-44",
        "body": "Detalle",
        "idempotency_key": "trello-44",
    }
    primero = _llamar(http, "send_message_direct", argumentos, ruta=f"/mcp/{CUENTA}")
    segundo = _llamar(http, "send_message_direct", argumentos, ruta=f"/mcp/{CUENTA}")
    assert primero["sent"] is True
    assert segundo["sent"] is True
    assert segundo["duplicate"] is True
    assert len(smtp.sent) == 1


def test_otra_cuenta_no_puede_usar_la_clave(cliente: tuple[TestClient, FakeSMTP]) -> None:
    """La idempotencia no cruza cuentas: el aislamiento sigue en pie."""
    http, smtp = cliente
    argumentos = {
        "account": CUENTA,
        "to": ["ana@example.com"],
        "subject": "A",
        "body": "Cuerpo",
        "idempotency_key": "trello-45",
    }
    _llamar(http, "send_message_direct", argumentos, ruta=f"/mcp/{CUENTA}")
    # La misma clave en otra cuenta se rechaza, no se reenvía. Aquí la
    # otra cuenta no existe, así que el error es de cuenta; lo que
    # importa es que no salga un segundo correo.
    with pytest.raises(Exception, match="not found|forbidden|desconocida"):
        _llamar(
            http,
            "send_message_direct",
            {**argumentos, "account": "otra@corp.example.com"},
            ruta="/mcp/otra@corp.example.com",
        )
    assert len(smtp.sent) == 1


def test_el_catalogo_de_tools_incluye_el_envio_directo(
    cliente: tuple[TestClient, FakeSMTP],
) -> None:
    """El cliente tiene que ver la tool nueva para poder llamarla."""
    http, _smtp = cliente
    respuesta = http.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={**JSON_HEADERS, "Authorization": f"Bearer {TOKEN}"},
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    herramientas = cuerpo["result"]["tools"]
    nombres = {tool["name"] for tool in herramientas}
    assert "send_message_direct" in nombres
    # Y el esquema lleva la clave de idempotencia.
    directa = next(tool for tool in herramientas if tool["name"] == "send_message_direct")
    assert "idempotency_key" in directa["inputSchema"]["properties"]
