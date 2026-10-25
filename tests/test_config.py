from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import Account, load_config, require_bearer_token

ROOT = Path(__file__).resolve().parents[1]


def test_ejemplo_carga_sin_mostrar_la_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "clave-ficticia-principal")
    monkeypatch.setenv("MAIL_ARCHIVO_PASSWORD", "clave-ficticia-archivo")
    monkeypatch.delenv("MCP_PUBLIC_HOST", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)
    settings, accounts = load_config(ROOT / "accounts.example.toml")
    assert settings.bind_host == "127.0.0.1"
    assert "mcp.example.com" in settings.allowed_hosts
    assert settings.enable_send is False
    assert settings.enable_mark is False
    assert settings.enable_delete is False
    assert settings.enable_drafts is False
    assert settings.smtp_security == "ssl"
    assert settings.confirm_ttl_seconds == 600
    assert settings.max_sends_per_day == 30
    assert accounts["principal"].allow_send is False
    assert accounts["principal"].allow_mark is False
    assert accounts["principal"].allow_delete is False
    assert accounts["principal"].allow_drafts is False
    assert set(accounts) == {"principal", "archivo"}
    assert "clave-ficticia-principal" not in repr(accounts["principal"])
    assert accounts["principal"].password == "clave-ficticia-principal"
    assert accounts["principal"].imap_ssl is True


def test_rechaza_contraseña_en_el_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "accounts.toml"
    path.write_text(
        """
        [server]
        bind_host = "127.0.0.1"
        [accounts.principal]
        imap_host = "mail.example.com"
        username = "ada@example.com"
        password = "no-va-aqui"
        password_env = "MAIL_PRINCIPAL_PASSWORD"
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "clave-ficticia-principal")
    with pytest.raises(SystemExit, match="contraseña"):
        load_config(path)


def test_falta_variable_de_la_cuenta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "accounts.toml"
    path.write_text(
        """
        [accounts.principal]
        imap_host = "mail.example.com"
        username = "ada@example.com"
        password_env = "MAIL_PRINCIPAL_PASSWORD"
        """,
        encoding="utf-8",
    )
    monkeypatch.delenv("MAIL_PRINCIPAL_PASSWORD", raising=False)
    with pytest.raises(SystemExit, match="MAIL_PRINCIPAL_PASSWORD"):
        load_config(path)


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


def test_un_texto_no_enciende_un_interruptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "accounts.toml"
    path.write_text(
        """
        [accounts.principal]
        imap_host = "mail.example.com"
        username = "ada@example.com"
        password_env = "MAIL_PRINCIPAL_PASSWORD"
        allow_send = "false"
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "clave-ficticia-principal")
    with pytest.raises(SystemExit, match="true o false"):
        load_config(path)


def _toml_minimo(path: Path) -> None:
    path.write_text(
        """
        [server]
        public_host = "mcp.example.com"
        allowed_hosts = ["otro.example.com"]
        allowed_origins = ["https://otro.example.com"]
        [accounts.principal]
        imap_host = "mail.example.com"
        username = "ada@example.com"
        password_env = "MAIL_PRINCIPAL_PASSWORD"
        """,
        encoding="utf-8",
    )


def test_el_dominio_publico_viene_del_entorno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "accounts.toml"
    _toml_minimo(path)
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "clave-ficticia-principal")
    monkeypatch.setenv("MCP_PUBLIC_HOST", "mcp.example.com")
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)
    settings, _accounts = load_config(path)
    assert settings.public_host == "mcp.example.com"
    assert "mcp.example.com" in settings.allowed_hosts
    assert "127.0.0.1:*" in settings.allowed_hosts
    assert "https://mcp.example.com" in settings.allowed_origins
    assert "otro.example.com" not in settings.allowed_hosts


def test_las_listas_explicitas_tapan_al_dominio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "accounts.toml"
    _toml_minimo(path)
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "clave-ficticia-principal")
    monkeypatch.setenv("MCP_PUBLIC_HOST", "mcp.example.com")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.example.com, mcp.example.com:*")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://mcp.example.com")
    settings, _accounts = load_config(path)
    assert settings.allowed_hosts == ("mcp.example.com", "mcp.example.com:*")
    assert settings.allowed_origins == ("https://mcp.example.com",)


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
    env = os.environ.copy()
    env.pop("MCP_BEARER_TOKEN", None)
    # PYTHONSAFEPATH (Actions) no añade el cwd. PYTHONPATH sí entra en sys.path.
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else os.pathsep.join((str(ROOT), previous))
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
