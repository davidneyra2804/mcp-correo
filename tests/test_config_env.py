"""Configuración por variables de entorno: contrato, precedencia y fail-fast.

Las cuentas se declaran por índice: MCP_ACCOUNT_<CAMPO>_<N>. La 1 es la
primera, la 2 la segunda.
"""

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


def _cuenta(
    monkeypatch: pytest.MonkeyPatch,
    index: int = 1,
    username: str = "ada@corp.example.com",
    **extra: str,
) -> None:
    monkeypatch.setenv(f"MCP_ACCOUNT_USERNAME_{index}", username)
    monkeypatch.setenv(f"MCP_ACCOUNT_INBOX_HOST_{index}", "imap.corp.example.com")
    monkeypatch.setenv(f"MCP_ACCOUNT_PASSWORD_{index}", "clave-secreta")
    for name, value in extra.items():
        monkeypatch.setenv(name, value)


def test_el_servidor_se_configura_solo_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(
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
    # La clave de la cuenta es su correo si no se le da nombre.
    assert set(accounts) == {"ada@corp.example.com"}


def test_una_cuenta_completa_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(
        monkeypatch,
        MCP_ACCOUNT_NAME_1="principal",
        MCP_ACCOUNT_LABEL_1="Correo principal",
        MCP_ACCOUNT_INBOX_TYPE_1="imap",
        MCP_ACCOUNT_INBOX_PORT_1="1993",
        MCP_ACCOUNT_INBOX_USE_SSL_1="false",
        MCP_ACCOUNT_SMTP_HOST_1="smtp.corp.example.com",
        MCP_ACCOUNT_SMTP_PORT_1="587",
        MCP_ACCOUNT_SMTP_USE_SSL_1="false",
        MCP_ACCOUNT_DRAFTS_FOLDER_1="Borradores",
        MCP_ACCOUNT_SENT_FOLDER_1="Enviados",
        MCP_ACCOUNT_TRASH_FOLDER_1="Papelera",
        MCP_ACCOUNT_ALLOW_SEND_1="true",
        MCP_ACCOUNT_ALLOW_MARK_1="true",
        MCP_ACCOUNT_ALLOW_DELETE_1="false",
        MCP_ACCOUNT_ALLOW_DRAFTS_1="1",
    )
    _settings, accounts = load_config()
    account = accounts["principal"]
    assert account.label == "Correo principal"
    assert account.imap_host == "imap.corp.example.com"
    assert account.imap_port == 1993
    assert account.imap_ssl is False
    assert account.smtp_host == "smtp.corp.example.com"
    assert account.smtp_port == 587
    # SMTP_USE_SSL false es STARTTLS.
    assert account.smtp_security == "starttls"
    assert account.drafts_folder == "Borradores"
    assert account.sent_folder == "Enviados"
    assert account.trash_folder == "Papelera"
    assert account.allow_send is True
    assert account.allow_mark is True
    assert account.allow_delete is False
    assert account.allow_drafts is True
    assert account.password == "clave-secreta"
    assert account.index == 1


def test_los_valores_por_defecto_de_una_cuenta(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch)
    _settings, accounts = load_config()
    account = accounts["ada@corp.example.com"]
    assert account.label == "ada@corp.example.com"
    assert account.imap_port == 993
    assert account.imap_ssl is True
    assert account.smtp_host == "imap.corp.example.com"
    assert account.smtp_port == 465
    # La cuenta no fija el modo SMTP si no lo dice: manda el global.
    assert account.smtp_security == ""
    assert account.drafts_folder == "Drafts"
    assert account.sent_folder == "Sent"
    assert account.trash_folder == ""
    assert account.allow_send is False
    assert account.bearer == ""


def test_el_modo_smtp_global_aplica_si_la_cuenta_no_lo_fija(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP_SMTP_SECURITY tiene que mandar cuando la cuenta no dice nada."""
    _cuenta(monkeypatch, MCP_SMTP_SECURITY="starttls")
    settings, accounts = load_config()
    account = accounts["ada@corp.example.com"]
    assert settings.smtp_security == "starttls"
    assert account.smtp_security == ""
    # El puerto por defecto acompaña al modo: 587 es STARTTLS, no 465.
    assert account.smtp_port == 587
    from mail.smtp_out import open_smtp  # noqa: F401

    effective = account.smtp_security or settings.smtp_security
    assert effective == "starttls"


def test_la_cuenta_puede_fijar_su_propio_modo_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, MCP_SMTP_SECURITY="starttls", MCP_ACCOUNT_SMTP_USE_SSL_1="true")
    _settings, accounts = load_config()
    assert accounts["ada@corp.example.com"].smtp_security == "ssl"


def test_la_cuenta_puede_pedir_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, MCP_ACCOUNT_SMTP_USE_SSL_1="false")
    _settings, accounts = load_config()
    assert accounts["ada@corp.example.com"].smtp_security == "starttls"
    # El puerto por defecto acompaña al modo: STARTTLS es el 587.
    assert accounts["ada@corp.example.com"].smtp_port == 587


def test_el_puerto_explicito_manda_sobre_el_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, MCP_ACCOUNT_SMTP_USE_SSL_1="false", MCP_ACCOUNT_SMTP_PORT_1="2525")
    _settings, accounts = load_config()
    assert accounts["ada@corp.example.com"].smtp_port == 2525


def test_varias_cuentas_por_indice(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1)
    _cuenta(monkeypatch, 2, username="ada@archivo.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_INBOX_HOST_2", "imap.archivo.example.com")
    _settings, accounts = load_config()
    assert set(accounts) == {"ada@corp.example.com", "ada@archivo.example.com"}
    assert accounts["ada@archivo.example.com"].index == 2


def test_mcp_accounts_es_una_comprobacion_cruzada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si se declara, tiene que coincidir con las cuentas que existen."""
    _cuenta(monkeypatch, 1)
    _cuenta(monkeypatch, 2, username="ada@archivo.example.com")
    monkeypatch.setenv("MCP_ACCOUNTS", "1,2")
    _settings, accounts = load_config()
    assert set(accounts) == {"ada@corp.example.com", "ada@archivo.example.com"}


def test_mcp_accounts_no_puede_omitir_una_cuenta(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1)
    _cuenta(monkeypatch, 2, username="ada@archivo.example.com")
    monkeypatch.setenv("MCP_ACCOUNTS", "1")
    with pytest.raises(SystemExit, match="no lista la cuenta 2"):
        load_config()


def test_mcp_accounts_no_puede_listar_una_cuenta_inexistente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cuenta(monkeypatch, 1)
    monkeypatch.setenv("MCP_ACCOUNTS", "1,3")
    with pytest.raises(SystemExit, match="no tiene ninguna variable"):
        load_config()


def test_un_indice_invalido_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1)
    monkeypatch.setenv("MCP_ACCOUNTS", "uno")
    with pytest.raises(SystemExit, match="índice de cuenta inválido"):
        load_config()


def test_una_variable_de_cuenta_sin_indice_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ACCOUNT_USERNAME", "ada@corp.example.com")
    with pytest.raises(SystemExit, match="Variable de cuenta desconocida"):
        load_config()


def test_un_campo_de_cuenta_desconocido_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1, MCP_ACCOUNT_INBOX_HOSTNAME_1="x")
    with pytest.raises(SystemExit, match="INBOX_HOSTNAME"):
        load_config()


def test_la_contraseña_puede_venir_de_otra_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ACCOUNT_USERNAME_1", "ada@corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_INBOX_HOST_1", "imap.corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_PASSWORD_ENV_1", "MAIL_PRINCIPAL_PASSWORD")
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "clave-indirecta")
    _settings, accounts = load_config()
    assert accounts["ada@corp.example.com"].password == "clave-indirecta"


def test_no_se_aceptan_las_dos_contraseñas(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1, MCP_ACCOUNT_PASSWORD_ENV_1="MAIL_PRINCIPAL_PASSWORD")
    monkeypatch.setenv("MAIL_PRINCIPAL_PASSWORD", "otra")
    with pytest.raises(SystemExit, match="PASSWORD"):
        load_config()


def test_una_cuenta_sin_contraseña_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ACCOUNT_USERNAME_1", "ada@corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_INBOX_HOST_1", "imap.corp.example.com")
    with pytest.raises(SystemExit, match="contraseña"):
        load_config()


def test_un_texto_no_enciende_un_interruptor(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1, MCP_ENABLE_SEND="yes")
    with pytest.raises(SystemExit, match="true, false, 1 o 0"):
        load_config()


def test_los_interruptores_aceptan_uno_y_cero(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1, MCP_ENABLE_SEND="1", MCP_ENABLE_MARK="0")
    settings, _accounts = load_config()
    assert settings.enable_send is True
    assert settings.enable_mark is False


def test_un_numero_mal_escrito_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1, MCP_MAX_CHARS="muchos")
    with pytest.raises(SystemExit, match="entero"):
        load_config()


def test_un_limite_de_cero_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1, MCP_MAX_CHARS="0")
    with pytest.raises(SystemExit, match="mayor o igual que 1"):
        load_config()


def test_dos_cuentas_con_el_mismo_nombre_no_arrancan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cuenta(monkeypatch, 1)
    _cuenta(monkeypatch, 2)
    with pytest.raises(SystemExit, match="comparten el nombre"):
        load_config()


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
    _cuenta(monkeypatch, 1, MCP_BIND_PORT="2222", MCP_MAX_CHARS="222", MCP_ENABLE_SEND="true")
    settings, accounts = load_config(path)
    assert settings.bind_port == 2222
    assert settings.max_chars == 222
    assert settings.enable_send is True
    # Las cuentas vienen del entorno, no del TOML.
    assert accounts["ada@corp.example.com"].imap_host == "imap.corp.example.com"
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
    _cuenta(
        monkeypatch,
        1,
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
    _cuenta(monkeypatch, 1, MCP_PUBLIC_HOST="mcp.example.com")
    settings, _accounts = load_config()
    assert "mcp.example.com" in settings.allowed_hosts
    assert "127.0.0.1:*" in settings.allowed_hosts
    assert "https://mcp.example.com" in settings.allowed_origins


def test_el_bearer_de_cuenta_se_guarda(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1, MCP_ACCOUNT_BEARER_1="bearer-propio-de-la-cuenta-01")
    _settings, accounts = load_config()
    assert accounts["ada@corp.example.com"].bearer == "bearer-propio-de-la-cuenta-01"


def test_un_bearer_de_cuenta_corto_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1, MCP_ACCOUNT_BEARER_1="corto")
    with pytest.raises(SystemExit, match="demasiado corto"):
        load_config()


def test_un_bearer_repetido_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    _cuenta(monkeypatch, 1, MCP_ACCOUNT_BEARER_1="bearer-compartido-0123456789")
    _cuenta(
        monkeypatch,
        2,
        username="ada@archivo.example.com",
        MCP_ACCOUNT_BEARER_2="bearer-compartido-0123456789",
    )
    with pytest.raises(SystemExit, match="comparten el mismo bearer"):
        load_config()


def test_un_bearer_igual_al_global_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_BEARER_TOKEN", "token-global-de-prueba-0123456789")
    _cuenta(monkeypatch, 1, MCP_ACCOUNT_BEARER_1="token-global-de-prueba-0123456789")
    with pytest.raises(SystemExit, match="no aísla nada"):
        load_config()


def test_avisa_si_el_host_publico_no_esta_en_la_lista(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """La causa del 421 con un túnel: la lista explícita deja fuera al dominio."""
    import logging

    _cuenta(
        monkeypatch,
        1,
        MCP_PUBLIC_HOST="mailproxy.example.com",
        MCP_ALLOWED_HOSTS="127.0.0.1:*,localhost:*",
    )
    with caplog.at_level(logging.WARNING):
        load_config()
    avisos = " ".join(record.getMessage() for record in caplog.records)
    assert "MCP_PUBLIC_HOST" in avisos
    assert "no está en allowed_hosts" in avisos


def test_no_avisa_si_el_host_publico_esta_permitido(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    _cuenta(monkeypatch, 1, MCP_PUBLIC_HOST="mailproxy.example.com")
    with caplog.at_level(logging.WARNING):
        settings, _accounts = load_config()
    avisos = " ".join(record.getMessage() for record in caplog.records)
    assert "no está en allowed_hosts" not in avisos
    assert "mailproxy.example.com" in settings.allowed_hosts
