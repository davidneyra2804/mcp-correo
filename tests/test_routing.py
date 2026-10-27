"""Rutas por cuenta: /mcp expone todas, /mcp/<cuenta> solo una.

El aislamiento tiene que ser real: una credencial de una cuenta no puede
llegar a las demás, ni por la ruta de otra cuenta ni por la de todas.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from audit import AuditLog
from config import Account, load_config
from server import create_app

TOKEN = os.environ["MCP_BEARER_TOKEN"]
JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

ADA = "ada@corp.example.com"
LUIS = "luis@corp.example.com"
CARLOS = "carlos@corp.example.com"
BEARER_ADA = "bearer-solo-de-ada-0123456789abcdef"
BEARER_LUIS = "bearer-solo-de-luis-0123456789abcdef"


def _cuentas() -> dict[str, Account]:
    return {
        ADA: Account(
            key=ADA,
            label="Correo de Ada",
            imap_host="imap.corp.example.com",
            imap_port=993,
            username=ADA,
            password="clave-ada",
            bearer=BEARER_ADA,
            index=1,
        ),
        LUIS: Account(
            key=LUIS,
            label="Correo de Luis",
            imap_host="imap.corp.example.com",
            imap_port=993,
            username=LUIS,
            password="clave-luis",
            bearer=BEARER_LUIS,
            index=2,
        ),
        "principal": Account(
            key="principal",
            label="Correo de Carlos",
            imap_host="imap.corp.example.com",
            imap_port=993,
            username=CARLOS,
            password="clave-carlos",
            index=3,
        ),
    }


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """Cada test necesita su propia app: el session manager del SDK solo arranca una vez."""
    settings, _accounts = load_config(Path(__file__).resolve().parents[1] / "accounts.example.toml")
    audit = AuditLog(tmp_path / "audit.jsonl", secrets=[TOKEN, BEARER_ADA, BEARER_LUIS])
    application, _runtime = create_app(settings, _cuentas(), TOKEN, audit=audit)
    with TestClient(application, base_url="http://127.0.0.1:8765") as http:
        yield http


def _call(http: TestClient, path: str, token: str, method: str = "tools/call") -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {"name": "list_accounts", "arguments": {}} if method == "tools/call" else {},
    }
    response = http.post(
        path,
        json=payload,
        headers={**JSON_HEADERS, "Authorization": f"Bearer {token}"},
    )
    return response


def _cuentas_devueltas(http: TestClient, path: str, token: str) -> list[str]:
    response = _call(http, path, token)
    assert response.status_code == 200, response.text
    body = response.json()["result"]["content"][0]["text"]
    import json

    return [item["account"] for item in json.loads(body)["accounts"]]


def test_la_ruta_raiz_ve_todas_las_cuentas(client: TestClient) -> None:
    assert _cuentas_devueltas(client, "/mcp", TOKEN) == [ADA, LUIS, "principal"]


def test_la_ruta_de_una_cuenta_ve_solo_esa(client: TestClient) -> None:
    assert _cuentas_devueltas(client, f"/mcp/{ADA}", TOKEN) == [ADA]


def test_la_ruta_acepta_el_nombre_de_la_cuenta(client: TestClient) -> None:
    """Con MCP_ACCOUNT_NAME, el nombre es el identificador de la ruta."""
    assert _cuentas_devueltas(client, "/mcp/principal", TOKEN) == ["principal"]


def test_la_ruta_acepta_el_correo_de_una_cueta_con_nombre(client: TestClient) -> None:
    assert _cuentas_devueltas(client, f"/mcp/{CARLOS}", TOKEN) == ["principal"]


def test_la_ruta_acepta_el_numero_de_cuenta(client: TestClient) -> None:
    assert _cuentas_devueltas(client, "/mcp/2", TOKEN) == [LUIS]


def test_el_bearer_de_una_cuenta_solo_sirve_en_su_ruta(client: TestClient) -> None:
    assert _cuentas_devueltas(client, f"/mcp/{ADA}", BEARER_ADA) == [ADA]


def test_el_bearer_de_una_cuenta_no_sirve_en_la_ruta_de_todas(client: TestClient) -> None:
    response = _call(client, "/mcp", BEARER_ADA)
    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_el_bearer_de_una_cuenta_no_sirve_en_la_ruta_de_otra(client: TestClient) -> None:
    response = _call(client, f"/mcp/{LUIS}", BEARER_ADA)
    assert response.status_code == 403


def test_un_bearer_desconocido_responde_401(client: TestClient) -> None:
    response = _call(client, f"/mcp/{ADA}", "este-no-existe-0123456789abcdefgh")
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_una_cuenta_inexistente_responde_404(client: TestClient) -> None:
    response = _call(client, "/mcp/nadie@corp.example.com", TOKEN)
    assert response.status_code == 404


def test_una_ruta_fuera_del_mcp_responde_404(client: TestClient) -> None:
    response = client.post(
        "/otro",
        json={},
        headers={**JSON_HEADERS, "Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 404


def test_una_cuenta_ajena_al_ambito_no_se_puede_usar(client: TestClient) -> None:
    """Aunque la ruta sea la de Ada, no se puede pedir la cuenta de Luis."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "list_folders", "arguments": {"account": LUIS}},
    }
    response = client.post(
        f"/mcp/{ADA}",
        json=payload,
        headers={**JSON_HEADERS, "Authorization": f"Bearer {BEARER_ADA}"},
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert "no está disponible" in result["content"][0]["text"]


def test_tools_list_no_cambia_por_la_ruta(client: TestClient) -> None:
    """Las tools son las mismas; lo que cambia es el ámbito."""
    todo = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={**JSON_HEADERS, "Authorization": f"Bearer {TOKEN}"},
    )
    uno = client.post(
        f"/mcp/{ADA}",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={**JSON_HEADERS, "Authorization": f"Bearer {BEARER_ADA}"},
    )
    assert todo.status_code == uno.status_code == 200
    assert todo.json()["result"]["tools"] == uno.json()["result"]["tools"]


def test_el_indice_cero_no_es_una_ruta(client: TestClient) -> None:
    """El 0 es el centinela de las cuentas del TOML: no enruta a ninguna."""
    response = _call(client, "/mcp/0", TOKEN)
    assert response.status_code == 404
