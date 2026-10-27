"""El contrato del proceso: token obligatorio y secretos fuera de las trazas."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import Account, require_bearer_token

ROOT = Path(__file__).resolve().parents[1]


def test_token_obligatorio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="MCP_BEARER_TOKEN"):
        require_bearer_token()
    monkeypatch.setenv("MCP_BEARER_TOKEN", "   ")
    with pytest.raises(SystemExit, match="MCP_BEARER_TOKEN"):
        require_bearer_token()
    monkeypatch.setenv("MCP_BEARER_TOKEN", "corto")
    with pytest.raises(SystemExit, match="demasiado corto"):
        require_bearer_token()


def test_repr_de_la_cuenta_oculta_el_secreto() -> None:
    account = Account(
        key="principal",
        label="Prueba",
        imap_host="mail.example.com",
        imap_port=993,
        username="ada@example.com",
        password="super-secreto-no-loguear",
    )
    try:
        raise RuntimeError(f"falló {account!r}")
    except RuntimeError as exc:
        assert "super-secreto-no-loguear" not in str(exc)


def test_el_proceso_no_arranca_sin_token() -> None:
    from tests.fakes import entorno_de_subproceso

    env = entorno_de_subproceso(ROOT)
    env.pop("MCP_BEARER_TOKEN", None)
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-c", "import server"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "MCP_BEARER_TOKEN" in completed.stderr
