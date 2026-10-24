from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import Account, load_config, require_bearer_token

ROOT = Path(__file__).resolve().parents[1]


def test_ejemplo_carga_sin_mostrar_la_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIL_VYRTS_PASSWORD", "clave-ficticia-vyrts")
    monkeypatch.setenv("MAIL_CARBONIO_PASSWORD", "clave-ficticia-carbonio")
    monkeypatch.delenv("MCP_PUBLIC_HOST", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)
    settings, accounts = load_config(ROOT / "accounts.example.toml")
    assert settings.bind_host == "127.0.0.1"
    assert "mcp.ejemplo.test" in settings.allowed_hosts
    assert settings.enable_send is False
    assert settings.enable_mark is False
    assert settings.enable_delete is False
    assert settings.enable_drafts is False
    assert settings.smtp_security == "ssl"
    assert settings.confirm_ttl_seconds == 600
    assert settings.max_sends_per_day == 30
    assert accounts["vyrts"].allow_send is False
    assert accounts["vyrts"].allow_mark is False
    assert accounts["vyrts"].allow_delete is False
    assert accounts["vyrts"].allow_drafts is False
    assert set(accounts) == {"vyrts", "carbonio"}
    assert "clave-ficticia-vyrts" not in repr(accounts["vyrts"])
    assert accounts["vyrts"].password == "clave-ficticia-vyrts"
    assert accounts["vyrts"].imap_ssl is True


def test_rechaza_contraseña_en_el_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "accounts.toml"
    path.write_text(
        """
        [server]
        bind_host = "127.0.0.1"
        [accounts.vyrts]
        imap_host = "mail.ejemplo.test"
        username = "david.neyra@ejemplo.test"
        password = "no-va-aqui"
        password_env = "MAIL_VYRTS_PASSWORD"
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIL_VYRTS_PASSWORD", "clave-ficticia-vyrts")
    with pytest.raises(SystemExit, match="contraseña"):
        load_config(path)


def test_falta_variable_de_la_cuenta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "accounts.toml"
    path.write_text(
        """
        [accounts.vyrts]
        imap_host = "mail.ejemplo.test"
        username = "david.neyra@ejemplo.test"
        password_env = "MAIL_VYRTS_PASSWORD"
        """,
        encoding="utf-8",
    )
    monkeypatch.delenv("MAIL_VYRTS_PASSWORD", raising=False)
    with pytest.raises(SystemExit, match="MAIL_VYRTS_PASSWORD"):
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
        [accounts.vyrts]
        imap_host = "mail.ejemplo.test"
        username = "david.neyra@ejemplo.test"
        password_env = "MAIL_VYRTS_PASSWORD"
        allow_send = "false"
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIL_VYRTS_PASSWORD", "clave-ficticia-vyrts")
    with pytest.raises(SystemExit, match="true o false"):
        load_config(path)


def _toml_minimo(path: Path) -> None:
    path.write_text(
        """
        [server]
        public_host = "mcp.ejemplo.test"
        allowed_hosts = ["otro.ejemplo.test"]
        allowed_origins = ["https://otro.ejemplo.test"]
        [accounts.vyrts]
        imap_host = "mail.ejemplo.test"
        username = "david.neyra@ejemplo.test"
        password_env = "MAIL_VYRTS_PASSWORD"
        """,
        encoding="utf-8",
    )


def test_el_dominio_publico_viene_del_entorno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "accounts.toml"
    _toml_minimo(path)
    monkeypatch.setenv("MAIL_VYRTS_PASSWORD", "clave-ficticia-vyrts")
    monkeypatch.setenv("MCP_PUBLIC_HOST", "mcp.vyrts.com")
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)
    settings, _accounts = load_config(path)
    assert settings.public_host == "mcp.vyrts.com"
    assert "mcp.vyrts.com" in settings.allowed_hosts
    assert "127.0.0.1:*" in settings.allowed_hosts
    assert "https://mcp.vyrts.com" in settings.allowed_origins
    assert "otro.ejemplo.test" not in settings.allowed_hosts


def test_las_listas_explicitas_tapan_al_dominio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "accounts.toml"
    _toml_minimo(path)
    monkeypatch.setenv("MAIL_VYRTS_PASSWORD", "clave-ficticia-vyrts")
    monkeypatch.setenv("MCP_PUBLIC_HOST", "mcp.vyrts.com")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.vyrts.com, mcp.vyrts.com:*")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://mcp.vyrts.com")
    settings, _accounts = load_config(path)
    assert settings.allowed_hosts == ("mcp.vyrts.com", "mcp.vyrts.com:*")
    assert settings.allowed_origins == ("https://mcp.vyrts.com",)


def test_repr_de_la_cuenta_oculta_el_secreto() -> None:
    account = Account(
        key="vyrts",
        label="Prueba",
        imap_host="mail.ejemplo.test",
        imap_port=993,
        username="david.neyra@ejemplo.test",
        password="super-secreto-no-loguear",
    )
    try:
        raise RuntimeError(f"falló {account!r}")
    except RuntimeError as exc:
        assert "super-secreto-no-loguear" not in str(exc)


def test_el_proceso_no_arranca_sin_token() -> None:
    env = os.environ.copy()
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
