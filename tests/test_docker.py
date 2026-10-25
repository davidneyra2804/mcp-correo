"""Empaquetado Docker: config generada, rotación y el compose sin secretos."""

from __future__ import annotations

import base64
import importlib.util
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
    monkeypatch.setenv("MCP_CONFIG", str(tmp_path / "no-existe.toml"))
    monkeypatch.setenv("MCP_ACCOUNTS_TOML_B64", "")
    monkeypatch.setenv("MCP_ACCOUNTS_TOML", "   ")
    with pytest.raises(SystemExit, match="Falta accounts.toml"):
        entry.resolve_accounts_file()


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
    assert "clave" not in text.lower()
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
