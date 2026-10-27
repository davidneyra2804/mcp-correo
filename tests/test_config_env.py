"""Configuración por variables de entorno: contrato y fail-fast.

El servidor se configura entero con variables `MCP_*`. Las cuentas ya no se
configuran aquí: las da de alta el panel, y viven en la base de datos.
"""

from __future__ import annotations

import pytest

from config import load_server_settings


@pytest.fixture(autouse=True)
def _sin_cuentas_heredadas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cada test arranca sin las variables de cuenta del conftest."""
    import os

    for name in list(os.environ):
        if name.startswith("MCP_ACCOUNT_"):
            monkeypatch.delenv(name, raising=False)


def test_el_servidor_se_configura_solo_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_BIND_PORT", "9999")
    monkeypatch.setenv("MCP_ENABLE_SEND", "true")
    monkeypatch.setenv("MCP_MAX_CHARS", "1234")
    monkeypatch.setenv("MCP_SMTP_SECURITY", "starttls")
    monkeypatch.setenv("MCP_PUBLIC_HOST", "mcp.example.com")
    settings = load_server_settings()
    assert settings.bind_host == "0.0.0.0"
    assert settings.bind_port == 9999
    assert settings.enable_send is True
    assert settings.enable_mark is False
    assert settings.enable_delete is False
    assert settings.enable_drafts is False
    assert settings.max_chars == 1234
    assert settings.smtp_security == "starttls"
    assert settings.public_host == "mcp.example.com"


def test_los_valores_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    for nombre in (
        "MCP_PUBLIC_HOST",
        "MCP_ALLOWED_HOSTS",
        "MCP_ALLOWED_ORIGINS",
        "MCP_BIND_HOST",
        "MCP_BIND_PORT",
        "MCP_ENABLE_SEND",
        "MCP_ENABLE_MARK",
        "MCP_ENABLE_DELETE",
        "MCP_ENABLE_DRAFTS",
        "MCP_MAX_RESULTS",
        "MCP_MAX_CHARS",
        "MCP_SMTP_SECURITY",
        "MCP_AUDIT_LOG",
    ):
        monkeypatch.delenv(nombre, raising=False)
    settings = load_server_settings()
    assert settings.bind_host == "127.0.0.1"
    assert settings.bind_port == 8765
    assert settings.enable_send is False
    assert settings.enable_mark is False
    assert settings.enable_delete is False
    assert settings.enable_drafts is False
    assert settings.smtp_security == "ssl"
    assert settings.confirm_ttl_seconds == 600
    assert settings.max_sends_per_day == 30
    assert settings.max_chars == 20_000


def test_un_texto_no_enciende_un_interruptor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLE_SEND", "yes")
    with pytest.raises(SystemExit, match="true, false, 1 o 0"):
        load_server_settings()


def test_los_interruptores_aceptan_uno_y_cero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLE_SEND", "1")
    monkeypatch.setenv("MCP_ENABLE_MARK", "0")
    settings = load_server_settings()
    assert settings.enable_send is True
    assert settings.enable_mark is False


def test_un_numero_mal_escrito_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_MAX_CHARS", "muchos")
    with pytest.raises(SystemExit, match="entero"):
        load_server_settings()


def test_un_limite_de_cero_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_MAX_CHARS", "0")
    with pytest.raises(SystemExit, match="mayor o igual que 1"):
        load_server_settings()


def test_un_puerto_fuera_de_rango_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_BIND_PORT", "70000")
    with pytest.raises(SystemExit, match="fuera de rango"):
        load_server_settings()


def test_el_timeout_debe_ser_positivo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_IMAP_TIMEOUT", "0")
    with pytest.raises(SystemExit, match="mayor que 0"):
        load_server_settings()


def test_las_listas_del_entorno_son_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.example.com, mcp.example.com:*")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://mcp.example.com")
    monkeypatch.setenv("MCP_ALLOWED_RECIPIENT_DOMAINS", "corp.example.com, partner.example.com")
    settings = load_server_settings()
    assert settings.allowed_hosts == ("mcp.example.com", "mcp.example.com:*")
    assert settings.allowed_origins == ("https://mcp.example.com",)
    assert settings.allowed_recipient_domains == ("corp.example.com", "partner.example.com")


def test_el_dominio_publico_deriva_los_hosts_permitidos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_PUBLIC_HOST", "mcp.example.com")
    settings = load_server_settings()
    assert "mcp.example.com" in settings.allowed_hosts
    assert "127.0.0.1:*" in settings.allowed_hosts
    assert "https://mcp.example.com" in settings.allowed_origins


def test_avisa_si_el_host_publico_no_esta_en_la_lista(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """La causa del 421 con un túnel: la lista explícita deja fuera al dominio."""
    import logging

    monkeypatch.setenv("MCP_PUBLIC_HOST", "mailproxy.example.com")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*")
    with caplog.at_level(logging.WARNING):
        load_server_settings()
    avisos = " ".join(record.getMessage() for record in caplog.records)
    assert "MCP_PUBLIC_HOST" in avisos
    assert "no está en allowed_hosts" in avisos


def test_no_avisa_si_el_host_publico_esta_permitido(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    monkeypatch.setenv("MCP_PUBLIC_HOST", "mailproxy.example.com")
    with caplog.at_level(logging.WARNING):
        settings = load_server_settings()
    avisos = " ".join(record.getMessage() for record in caplog.records)
    assert "no está en allowed_hosts" not in avisos
    assert "mailproxy.example.com" in settings.allowed_hosts


def test_las_variables_de_cuenta_no_configuran_nada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Las cuentas no se declaran por entorno: el panel las da de alta."""
    monkeypatch.setenv("MCP_ACCOUNT_USERNAME_1", "ada@corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_INBOX_HOST_1", "imap.corp.example.com")
    monkeypatch.setenv("MCP_ACCOUNT_PASSWORD_1", "clave-secreta")
    settings = load_server_settings()
    # La configuración del servidor no se entera: no hay cuentas en el arranque.
    assert settings.max_chars > 0


def test_el_texto_dice_el_global_cuando_eso_es_lo_que_falta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import write_capabilities_detail

    monkeypatch.setenv("MCP_ENABLE_MARK", "false")
    settings = load_server_settings()
    _activas, motivos = write_capabilities_detail(settings, {})
    texto = "; ".join(motivos)
    assert "marcado: falta MCP_ENABLE_MARK=true" in texto
    assert "ALLOW_MARK" not in texto


def test_el_texto_dice_que_ninguna_cuenta_lo_permite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import write_capabilities_detail

    monkeypatch.setenv("MCP_ENABLE_MARK", "true")
    settings = load_server_settings()
    _activas, motivos = write_capabilities_detail(settings, {})
    texto = "; ".join(motivos)
    assert "marcado: ninguna cuenta lo permite; revisa los permisos en el panel" in texto
    assert "falta MCP_ENABLE_MARK" not in texto
