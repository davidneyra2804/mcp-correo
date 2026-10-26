"""Empaquetado Docker: config generada, rotación y el compose sin secretos."""

from __future__ import annotations

import base64
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_el_fichero_montado_tiene_prioridad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _load("entrypoint", "docker/entrypoint.py")
    mounted = tmp_path / "accounts.toml"
    mounted.write_text("[server]\npublic_host='x'\n", encoding="utf-8")
    monkeypatch.setenv("MCP_CONFIG", str(mounted))
    monkeypatch.setenv("MCP_ACCOUNTS_TOML", "[server]\npublic_host='no'\n")
    assert entry.resolve_accounts_file() == str(mounted)


def test_genera_toml_desde_base64(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _load("entrypoint", "docker/entrypoint.py")
    text = '[server]\npublic_host = "mcp.example.com"\n'
    monkeypatch.setenv("MCP_CONFIG", str(tmp_path / "no-existe.toml"))
    monkeypatch.setenv("MCP_ACCOUNTS_TOML_B64", base64.b64encode(text.encode()).decode())
    monkeypatch.setenv("MCP_GENERATED_CONFIG", str(tmp_path / "generado.toml"))
    monkeypatch.delenv("MCP_ACCOUNTS_TOML", raising=False)
    path = entry.resolve_accounts_file()
    assert Path(path).read_text(encoding="utf-8") == text
    assert oct(Path(path).stat().st_mode & 0o777) == "0o600"


def test_rechaza_una_contraseña_en_el_texto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _load("entrypoint", "docker/entrypoint.py")
    monkeypatch.setenv("MCP_CONFIG", str(tmp_path / "no-existe.toml"))
    monkeypatch.setenv("MCP_ACCOUNTS_TOML_B64", "")
    monkeypatch.setenv(
        "MCP_ACCOUNTS_TOML",
        '[accounts.principal]\npassword = "no-va-aqui"\npassword_env = "MAIL_PRINCIPAL_PASSWORD"\n',
    )
    with pytest.raises(SystemExit, match="contraseña"):
        entry.resolve_accounts_file()


def test_sin_config_no_arranca(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _load("entrypoint", "docker/entrypoint.py")
    monkeypatch.delenv("MCP_CONFIG", raising=False)
    monkeypatch.setenv("MCP_ACCOUNTS_TOML_B64", "")
    monkeypatch.setenv("MCP_ACCOUNTS_TOML", "   ")
    monkeypatch.delenv("MCP_ACCOUNTS", raising=False)
    with pytest.raises(SystemExit, match="Falta la configuración"):
        entry.resolve_accounts_file()


def test_mcp_config_inexistente_sin_cuentas_no_arranca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _load("entrypoint", "docker/entrypoint.py")
    monkeypatch.setenv("MCP_CONFIG", str(tmp_path / "no-existe.toml"))
    monkeypatch.setenv("MCP_ACCOUNTS_TOML_B64", "")
    monkeypatch.setenv("MCP_ACCOUNTS_TOML", "   ")
    monkeypatch.delenv("MCP_ACCOUNTS", raising=False)
    with pytest.raises(SystemExit, match="No se encuentra la configuración"):
        entry.resolve_accounts_file()


def test_las_cuentas_por_entorno_no_necesitan_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _load("entrypoint", "docker/entrypoint.py")
    monkeypatch.setenv("MCP_CONFIG", str(tmp_path / "no-existe.toml"))
    monkeypatch.setenv("MCP_ACCOUNTS", "principal")
    monkeypatch.setenv("MCP_ACCOUNTS_TOML_B64", "")
    monkeypatch.setenv("MCP_ACCOUNTS_TOML", "   ")
    assert entry.resolve_accounts_file() is None
    assert "MCP_CONFIG" not in os.environ


def test_el_toml_montado_gana_a_las_cuentas_por_entorno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _load("entrypoint", "docker/entrypoint.py")
    mounted = tmp_path / "accounts.toml"
    mounted.write_text("[server]\npublic_host='x'\n", encoding="utf-8")
    monkeypatch.setenv("MCP_CONFIG", str(mounted))
    monkeypatch.setenv("MCP_ACCOUNTS", "principal")
    assert entry.resolve_accounts_file() == str(mounted)


def test_la_rotacion_conserva_el_numero_pedido(tmp_path: Path) -> None:
    rotate = _load("rotate_audit", "docker/rotate_audit.py")
    path = tmp_path / "audit.jsonl"
    path.write_text("uno\n", encoding="utf-8")
    assert rotate.rotate_once(path, max_bytes=1, keep=2) is True
    assert not path.exists()
    assert (tmp_path / "audit.jsonl.1").read_text(encoding="utf-8") == "uno\n"
    path.write_text("dos\n", encoding="utf-8")
    assert rotate.rotate_once(path, max_bytes=1, keep=2) is True
    path.write_text("tres\n", encoding="utf-8")
    assert rotate.rotate_once(path, max_bytes=1, keep=2) is True
    assert (tmp_path / "audit.jsonl.1").read_text(encoding="utf-8") == "tres\n"
    assert (tmp_path / "audit.jsonl.2").read_text(encoding="utf-8") == "dos\n"
    assert not (tmp_path / "audit.jsonl.3").exists()
    assert rotate.rotate_once(path, max_bytes=10_000, keep=2) is False


def test_el_compose_publica_solo_loopback_y_no_lleva_secretos() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "127.0.0.1" in text
    assert "cap_drop:" in text
    assert "no-new-privileges:true" in text
    assert "read_only: true" in text
    assert "unless-stopped" in text
    assert "MCP_BEARER_TOKEN:" in text
    assert "password =" not in text
    # Ningún secreto con valor literal: todo sale de ${VAR}.
    for line in text.splitlines():
        if "PASSWORD" not in line or ":" not in line:
            continue
        value = line.split(":", 1)[1].strip()
        assert value.startswith("${") or not value, f"Secreto con valor literal: {line}"
    assert "profiles:" in text
    assert "caddy:2-alpine" in text
    assert "traefik.enable" in text
    assert "mcp-correo:local" in text
    assert "pull_policy: ${MCP_PULL_POLICY:-build}" in text
    assert "pull_policy: ${MCP_PULL_POLICY:-never}" in text
    assert text.count("dockerfile: Dockerfile") == 1
    assert "depends_on:" in text
    assert "USER mcp" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "python:3.12-slim" in dockerfile
    assert "workers=1" in (ROOT / "server.py").read_text(encoding="utf-8")


def test_el_compose_base_no_necesita_ningun_fichero_de_configuracion() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "MCP_CONFIG" not in text
    assert "MCP_ACCOUNTS_TOML" not in text
    assert "accounts.toml" not in text
    # Portainer deja aquí las variables del stack, incluidas las de cuenta.
    assert "stack.env" in text
    assert "required: false" in text


def test_el_compose_declara_todas_las_variables_fijas_del_servidor() -> None:
    from config import _SERVER_ENV

    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    missing = sorted(name for name in _SERVER_ENV.values() if f"{name}:" not in text)
    assert not missing, f"El compose no declara: {', '.join(missing)}"


def test_el_ejemplo_de_env_documenta_todas_las_variables() -> None:
    from config import _ACCOUNT_ENV_BASES, _SERVER_ENV

    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    missing = sorted(name for name in _SERVER_ENV.values() if name not in text)
    assert not missing, f"El ejemplo no documenta: {', '.join(missing)}"
    missing_fields = sorted(base for base in _ACCOUNT_ENV_BASES if base not in text)
    assert not missing_fields, f"El ejemplo no documenta: {', '.join(missing_fields)}"
    assert "MCP_ACCOUNT_USERNAME_1=" in text


def test_el_overlay_del_tunel_no_lleva_el_token_dentro() -> None:
    text = (ROOT / "docker-compose.tunnel.yml").read_text(encoding="utf-8")
    assert "cloudflare/cloudflared" in text
    assert "${CLOUDFLARE_TUNNEL_TOKEN:?" in text
    assert "depends_on:" in text
    assert "cap_drop:" in text
    assert "no-new-privileges:true" in text
    # El token solo puede venir del entorno.
    assert "eyJh" not in text


def test_el_compose_local_no_necesita_el_toml() -> None:
    text = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
    assert "MCP_ACCOUNT_USERNAME_1:" in text
    assert "MCP_ACCOUNT_INBOX_HOST_1:" in text
    assert "MCP_ACCOUNT_PASSWORD_2:" in text
    assert "accounts.toml" not in text


def test_ningun_compose_declara_una_contrasena_como_clave_de_cuenta() -> None:
    for name in (
        "docker-compose.yml",
        "docker-compose.tunnel.yml",
        "docker-compose.local.yml",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "MCP_ACCOUNT_PRINCIPAL_PASSWORD:" not in text or "local" in name
