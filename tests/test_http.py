from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from audit import AuditLog
from server import INSTRUCTIONS, create_app
from tests.ayuda import ajustes

TOKEN = os.environ["MCP_BEARER_TOKEN"]
JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """Cada test necesita su propia app: el session manager del SDK solo arranca una vez."""
    settings = ajustes()
    audit = AuditLog(tmp_path / "audit.jsonl", secrets=[TOKEN])
    application, _runtime = create_app(settings, {}, TOKEN, audit=audit)
    with TestClient(application, base_url="http://127.0.0.1:8765") as http:
        yield http


def test_salud_no_exige_token(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "unauthorized" not in response.text


def test_sin_token_responde_401(client: TestClient) -> None:
    response = client.post("/mcp", json={}, headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_token_incorrecto_no_se_refleja(client: TestClient) -> None:
    presented = "esto-no-es-el-token-real-0123456789"
    response = client.post(
        "/mcp",
        json={},
        headers={**JSON_HEADERS, "Authorization": f"Bearer {presented}"},
    )
    assert response.status_code == 401
    assert presented not in response.text


def test_token_de_otra_longitud_responde_401(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json={},
        headers={**JSON_HEADERS, "Authorization": "Bearer corto"},
    )
    assert response.status_code == 401


def test_tools_list_con_token(client: TestClient) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    response = client.post(
        "/mcp",
        json=payload,
        headers={**JSON_HEADERS, "Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    body = response.json()
    names = {tool["name"] for tool in body["result"]["tools"]}
    assert {
        "list_accounts",
        "list_folders",
        "list_messages",
        "search_messages",
        "get_message",
        "get_attachment",
        "find_unanswered",
        "list_threads",
    } <= names
    assert "send_message" not in names
    assert "prepare_send" not in names
    assert "create_draft" not in names


def test_host_no_permitido(client: TestClient) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    response = client.post(
        "/mcp",
        json=payload,
        headers={
            **JSON_HEADERS,
            "Authorization": f"Bearer {TOKEN}",
            "Host": "evil.example.com",
        },
    )
    assert response.status_code == 421


def test_origin_no_permitido(client: TestClient) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    response = client.post(
        "/mcp",
        json=payload,
        headers={
            **JSON_HEADERS,
            "Authorization": f"Bearer {TOKEN}",
            "Origin": "https://evil.example.com",
        },
    )
    assert response.status_code == 403


def test_instrucciones_avisan_de_contenido_no_confiable() -> None:
    text = INSTRUCTIONS.lower()
    assert "no confiables" in text
    assert "inyección" in text
    assert "solo lectura" in text
    assert "orden explícita" in text
    assert "confirm_token" in text


def test_instrucciones_describen_el_flujo_de_envio_paso_a_paso() -> None:
    """Las instrucciones del servidor tienen que contar el flujo completo.

    El agente no debe tener que deducir que preparar no envía y que luego
    hay que llamar a send_message. Las instrucciones son la primera capa
    que ve el modelo, pero no la única: la descripción de cada tool y el
    aviso de la respuesta repiten el mismo contrato.
    """
    text = INSTRUCTIONS.lower()
    assert "preparar no ejecuta" in text
    assert "send_message" in text
    assert "no envíes" not in text
    for paso in ("1.", "2.", "3.", "4."):
        assert paso in text
    assert "vuelve a preparar" in text
