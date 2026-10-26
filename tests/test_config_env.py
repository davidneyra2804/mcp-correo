"""Configuración por variables de entorno: contrato, precedencia y fail-fast."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import load_config

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _sin_toml_ni_cuentas_globales(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cada test arranca sin TOML y sin cuentas heredadas del conftest."""
    monkeypatch.delenv("MCP_CONFIG", raising=False)
    for name in list(os.environ):
        if name.startswith("MCP_ACCOUNT_") or name == "MCP_ACCOUNTS":
            monkeypatch.delenv(name, raising=False)


def _cuenta_principal(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    monkeypatch.setenv("MCP_ACCOUNTS", "principal")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_USERNAME", "ada@corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_IMAP_HOST", "imap.corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_PASSWORD", "clave-secreta")
    for name, value in extra.items():
        monkeypatch.setenv(name, value)


def test_el_servidor_se_configura_solo_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(
        monkeypatch,
        MCP_BIND_HOST="0.0.0.0",
        MCP_BIND_PORT="9999",
        MCP_ENABLE_SEND="true",
        MCP_MAX_CHARS="1234",
        MCP_SMTP_SECURITY="starttls",
        MCP_PUBLIC_HOST="mcp.example.com",
    )
    settings, accounts = load_config()
    assert settings.bind_host == "0.0.0.0"
    assert settings.bind_port == 9999
    assert settings.enable_send is True
    assert settings.enable_mark is False
    assert settings.enable_delete is False
    assert settings.enable_drafts is False
    assert settings.max_chars == 1234
    assert settings.smtp_security == "starttls"
    assert settings.public_host == "mcp.example.com"
    assert settings.config_source == "env"
    assert set(accounts) == {"principal"}


def test_una_cuenta_completa_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(
        monkeypatch,
        MCP_ACCOUNT_PRINCIPAL_LABEL="Correo principal",
        MCP_ACCOUNT_PRINCIPAL_IMAP_PORT="1993",
        MCP_ACCOUNT_PRINCIPAL_IMAP_SSL="false",
        MCP_ACCOUNT_PRINCIPAL_SMTP_HOST="smtp.corp.example.com",
        MCP_ACCOUNT_PRINCIPAL_SMTP_PORT="587",
        MCP_ACCOUNT_PRINCIPAL_SMTP_SECURITY="starttls",
        MCP_ACCOUNT_PRINCIPAL_DRAFTS_FOLDER="Borradores",
        MCP_ACCOUNT_PRINCIPAL_SENT_FOLDER="Enviados",
        MCP_ACCOUNT_PRINCIPAL_TRASH_FOLDER="Papelera",
        MCP_ACCOUNT_PRINCIPAL_ALLOW_SEND="true",
        MCP_ACCOUNT_PRINCIPAL_ALLOW_MARK="true",
        MCP_ACCOUNT_PRINCIPAL_ALLOW_DELETE="false",
        MCP_ACCOUNT_PRINCIPAL_ALLOW_DRAFTS="1",
    )
    _settings, accounts = load_config()
    account = accounts["principal"]
    assert account.label == "Correo principal"
    assert account.imap_host == "imap.corp.example.com"
    assert account.imap_port == 1993
    assert account.imap_ssl is False
    assert account.smtp_host == "smtp.corp.example.com"
    assert account.smtp_port == 587
    assert account.smtp_security == "starttls"
    assert account.drafts_folder == "Borradores"
    assert account.sent_folder == "Enviados"
    assert account.trash_folder == "Papelera"
    assert account.allow_send is True
    assert account.allow_mark is True
    assert account.allow_delete is False
    assert account.allow_drafts is True
    assert account.password == "clave-secreta"


def test_los_valores_por_defecto_de_una_cuenta(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(monkeypatch)
    _settings, accounts = load_config()
    account = accounts["principal"]
    assert account.label == "principal"
    assert account.imap_port == 993
    assert account.imap_ssl is True
    assert account.smtp_host == "imap.corp.example.com"
    assert account.smtp_port == 465
    assert account.drafts_folder == "Drafts"
    assert account.sent_folder == "Sent"
    assert account.trash_folder == ""
    assert account.allow_send is False


def test_la_contraseña_puede_venir_de_otra_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ACCOUNTS", "principal")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_USERNAME", "ada@corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_IMAP_HOST", "imap.corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_PASSWORD_ENV", "MAIL_PRINCIPAL_PASSWORD")
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "clave-indirecta")
    _settings, accounts = load_config()
    assert accounts["principal"].password == "clave-indirecta"


def test_no_se_aceptan_las_dos_contraseñas(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(monkeypatch, MCP_ACCOUNT_PRINCIPAL_PASSWORD_ENV="MAIL_PRINCIPAL_PASSWORD")
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "otra")
    with pytest.raises(SystemExit, match="PASSWORD"):
        load_config()


def test_una_cuenta_sin_contraseña_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ACCOUNTS", "principal")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_USERNAME", "ada@corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_IMAP_HOST", "imap.corp.example.com")
    with pytest.raises(SystemExit, match="contraseña"):
        load_config()


def test_el_password_env_apunta_a_una_variable_inexistente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ACCOUNTS", "principal")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_USERNAME", "ada@corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_IMAP_HOST", "imap.corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_PASSWORD_ENV", "MAIL_PRINCIPAL_PASSWORD")
    monkeypatch.delenv("MAIL_PRINCIPAL_PASSWORD", raising=False)
    with pytest.raises(SystemExit, match="MAIL_PRINCIPAL_PASSWORD"):
        load_config()


def test_un_texto_no_enciende_un_interruptor(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(monkeypatch, MCP_ENABLE_SEND="yes")
    with pytest.raises(SystemExit, match="true, false, 1 o 0"):
        load_config()


def test_los_interruptores_aceptan_uno_y_cero(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(monkeypatch, MCP_ENABLE_SEND="1", MCP_ENABLE_MARK="0")
    settings, _accounts = load_config()
    assert settings.enable_send is True
    assert settings.enable_mark is False


def test_un_typo_en_un_campo_de_cuenta_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(monkeypatch, MCP_ACCOUNT_PRINCIPAL_SENT_FOLDR="Enviados")
    with pytest.raises(SystemExit, match="SENT_FOLDR"):
        load_config()


def test_una_cuenta_no_declarada_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(monkeypatch, MCP_ACCOUNT_ARCHIVO_USERNAME="ada@archivo.example.com")
    with pytest.raises(SystemExit, match="MCP_ACCOUNTS"):
        load_config()


def test_campos_de_cuenta_sin_la_lista_de_cuentas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ACCOUNT_PRINCIPAL_USERNAME", "ada@corp.example.com")
    with pytest.raises(SystemExit, match="MCP_ACCOUNTS"):
        load_config()


def test_una_cuenta_repetida_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ACCOUNTS", "principal,principal")
    with pytest.raises(SystemExit, match="repite"):
        load_config()


def test_dos_cuentas_iguales_en_mayusculas_no_arrancan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ACCOUNTS", "principal,PRINCIPAL")
    with pytest.raises(SystemExit, match="mayúsculas"):
        load_config()


def test_una_clave_de_cuenta_invalida_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ACCOUNTS", "con espacio")
    with pytest.raises(SystemExit, match="inválida"):
        load_config()


def test_varias_cuentas_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(monkeypatch)
    monkeypatch.setenv("MCP_ACCOUNTS", "principal,archivo")
    monkeypatch.setenv("MCP_ACCOUNT_ARCHIVO_USERNAME", "ada@archivo.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_ARCHIVO_IMAP_HOST", "imap.archivo.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_ARCHIVO_PASSWORD", "clave-archivo")
    _settings, accounts = load_config()
    assert set(accounts) == {"principal", "archivo"}
    assert accounts["archivo"].imap_host == "imap.archivo.example.com"


def test_el_entorno_manda_sobre_el_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "accounts.toml"
    path.write_text(
        """
        [server]
        bind_port = 1111
        max_chars = 111
        enable_send = false
        [accounts.principal]
        imap_host = "toml.example.com"
        username = "ada@toml.example.com"
        password_env = "MAIL_PRINCIPAL_PASSWORD"
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "clave-toml")
    _cuenta_principal(
        monkeypatch,
        MCP_BIND_PORT="2222",
        MCP_MAX_CHARS="222",
        MCP_ENABLE_SEND="true",
    )
    settings, accounts = load_config(path)
    assert settings.bind_port == 2222
    assert settings.max_chars == 222
    assert settings.enable_send is True
    # Las cuentas vienen del entorno, no del TOML.
    assert accounts["principal"].imap_host == "imap.corp.example.com"
    assert settings.config_source == "env"


def test_el_toml_alimenta_el_servidor_cuando_el_entorno_no_cuenta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "accounts.toml"
    path.write_text(
        """
        [server]
        max_chars = 333
        [accounts.principal]
        imap_host = "mail.example.com"
        username = "ada@example.com"
        password_env = "MAIL_PRINCIPAL_PASSWORD"
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "clave-ficticia")
    settings, accounts = load_config(path)
    assert settings.max_chars == 333
    assert settings.config_source == "toml"
    assert accounts["principal"].imap_host == "mail.example.com"


def test_sin_ninguna_fuente_no_hay_cuentas(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit, match="No hay cuentas"):
        load_config()


def test_las_listas_del_entorno_son_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(
        monkeypatch,
        MCP_ALLOWED_HOSTS="mcp.example.com, mcp.example.com:*",
        MCP_ALLOWED_ORIGINS="https://mcp.example.com",
        MCP_ALLOWED_RECIPIENT_DOMAINS="corp.example.com, partner.example.com",
    )
    settings, _accounts = load_config()
    assert settings.allowed_hosts == ("mcp.example.com", "mcp.example.com:*")
    assert settings.allowed_origins == ("https://mcp.example.com",)
    assert settings.allowed_recipient_domains == ("corp.example.com", "partner.example.com")


def test_el_dominio_publico_deriva_los_hosts_permitidos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cuenta_principal(monkeypatch, MCP_PUBLIC_HOST="mcp.example.com")
    settings, _accounts = load_config()
    assert "mcp.example.com" in settings.allowed_hosts
    assert "127.0.0.1:*" in settings.allowed_hosts
    assert "https://mcp.example.com" in settings.allowed_origins


def test_un_numero_mal_escrito_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(monkeypatch, MCP_MAX_CHARS="muchos")
    with pytest.raises(SystemExit, match="entero"):
        load_config()


def test_un_limite_de_cero_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta_principal(monkeypatch, MCP_MAX_CHARS="0")
    with pytest.raises(SystemExit, match="mayor o igual que 1"):
        load_config()


def _leer_env_ejemplo() -> dict[str, str]:
    """Un .env de verdad: líneas KEY=VALOR, con comentarios y comillas."""
    env: dict[str, str] = {}
    for raw in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def test_el_ejemplo_de_env_arranca_el_servidor(monkeypatch: pytest.MonkeyPatch) -> None:
    """El .env.example tiene que ser pegable tal cual en Portainer."""
    for name, value in _leer_env_ejemplo().items():
        monkeypatch.setenv(name, value)
    settings, accounts = load_config()
    assert settings.config_source == "env"
    assert set(accounts) == {"principal", "archivo"}
    # La escritura sale apagada: el ejemplo no habilita nada por accidente.
    assert settings.enable_send is False
    assert settings.enable_mark is False
    assert settings.enable_delete is False
    assert settings.enable_drafts is False
    assert all(not account.allow_send for account in accounts.values())
    assert len(settings.allowed_hosts) > 0
    assert len(settings.allowed_origins) > 0
