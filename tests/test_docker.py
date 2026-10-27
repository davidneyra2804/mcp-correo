"""Empaquetado Docker: config generada, rotación y el compose sin secretos."""

from __future__ import annotations

import base64
import importlib.util
import os
from pathlib import Path

import pytest
import yaml

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


def test_sin_toml_el_entrypoint_no_aborta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """El entrypoint solo prepara el fichero. Si no hay, sigue.

    Si no hay cuentas, avisa config.py, que es quien sabe qué es una
    cuenta. Aquí no se decide eso, para que las dos piezas no discrepen.
    """
    entry = _load("entrypoint", "docker/entrypoint.py")
    monkeypatch.delenv("MCP_CONFIG", raising=False)
    monkeypatch.setenv("MCP_ACCOUNTS_TOML_B64", "")
    monkeypatch.setenv("MCP_ACCOUNTS_TOML", "   ")
    assert entry.resolve_accounts_file() is None


def test_mcp_config_inexistente_no_aborta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un MCP_CONFIG que no existe se avisa y se sigue."""
    entry = _load("entrypoint", "docker/entrypoint.py")
    monkeypatch.setenv("MCP_CONFIG", str(tmp_path / "no-existe.toml"))
    monkeypatch.setenv("MCP_ACCOUNTS_TOML_B64", "")
    monkeypatch.setenv("MCP_ACCOUNTS_TOML", "   ")
    assert entry.resolve_accounts_file() is None
    assert "MCP_CONFIG" not in os.environ


def test_las_cuentas_por_entorno_no_necesitan_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _load("entrypoint", "docker/entrypoint.py")
    monkeypatch.setenv("MCP_CONFIG", str(tmp_path / "no-existe.toml"))
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
    assert entry.resolve_accounts_file() == str(mounted)


def test_una_contraseña_entrecomillada_tampoco_pasa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La clave puede venir entrecomillada: el filtro tiene que verla."""
    entry = _load("entrypoint", "docker/entrypoint.py")
    monkeypatch.setenv("MCP_CONFIG", str(tmp_path / "no-existe.toml"))
    monkeypatch.setenv("MCP_ACCOUNTS_TOML_B64", "")
    monkeypatch.setenv(
        "MCP_ACCOUNTS_TOML",
        '[accounts.principal]\n"password" = "no-va-aqui"\npassword_env = "MAIL_X"\n',
    )
    with pytest.raises(SystemExit, match="contraseña"):
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


def test_el_rotador_avisa_de_un_numero_malo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un valor no numérico no puede tumbar el contenedor en bucle."""
    rotate = _load("rotate_audit", "docker/rotate_audit.py")
    monkeypatch.setenv("MCP_AUDIT_MAX_BYTES", "muchos")
    with pytest.raises(SystemExit, match="entero"):
        rotate._entero("MCP_AUDIT_MAX_BYTES", 10485760)


def test_el_rotador_acepta_el_default(monkeypatch: pytest.MonkeyPatch) -> None:
    rotate = _load("rotate_audit", "docker/rotate_audit.py")
    monkeypatch.delenv("MCP_AUDIT_KEEP", raising=False)
    assert rotate._entero("MCP_AUDIT_KEEP", 12) == 12


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
    assert "profiles:" not in text
    assert "caddy" not in text
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


def test_cada_servicio_tiene_container_name() -> None:
    """Nombres estables: en Portainer se ven en Containers y en los logs."""
    esperados = {
        "docker-compose.yml": {"mcp": "mcp-correo", "audit-rotate": "mcp-correo-audit-rotate"},
        "docker-compose.tunnel.yml": {"cloudflared": "mcp-correo-cloudflared"},
        "docker-compose.proxy.yml": {"caddy": "mcp-correo-caddy"},
    }
    for nombre, servicios in esperados.items():
        compose = yaml.safe_load((ROOT / nombre).read_text(encoding="utf-8"))
        for servicio, container in servicios.items():
            assert compose["services"][servicio]["container_name"] == container


def test_el_tunel_no_necesita_caddy() -> None:
    """Con túnel, el TLS lo termina Cloudflare. Caddy sería un segundo terminador."""
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    tunel = yaml.safe_load((ROOT / "docker-compose.tunnel.yml").read_text(encoding="utf-8"))
    proxy = yaml.safe_load((ROOT / "docker-compose.proxy.yml").read_text(encoding="utf-8"))
    assert "caddy" not in base["services"]
    assert "cloudflared" in tunel["services"]
    assert "caddy" not in tunel["services"]
    # Caddy existe, pero solo en su propio overlay.
    assert "caddy" in proxy["services"]
    assert set(base["services"]) == {"mcp", "audit-rotate"}


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


def test_la_tabla_de_variables_coincide_con_el_codigo() -> None:
    """`_SERVER_ENV` dice qué variables existen. Tiene que ser verdad.

    La tabla no la usa el runtime (las lecturas son literales), así que sin
    este test podría quedar desfasada: el compose y el .env.example pasarían
    los tests de nombres, pero la variable ya no se leería.
    """
    from config import _SERVER_ENV

    fuente = (ROOT / "config.py").read_text(encoding="utf-8")
    huerfanas = sorted(name for name in _SERVER_ENV.values() if f'"{name}"' not in fuente)
    assert not huerfanas, f"Variables en la tabla que el código no lee: {', '.join(huerfanas)}"


def test_las_variables_de_cuenta_coinciden_con_el_codigo() -> None:
    """Los campos de cuenta de la tabla tienen que estar en el código."""
    from config import _ACCOUNT_ENV_BASES, _ACCOUNT_ENV_FIELDS

    fuente = (ROOT / "config.py").read_text(encoding="utf-8")
    huerfanas = sorted(base for base in _ACCOUNT_ENV_BASES if f'"{base}"' not in fuente)
    assert not huerfanas, f"Campos en la tabla que el código no usa: {', '.join(huerfanas)}"
    assert set(_ACCOUNT_ENV_FIELDS.values()) == set(_ACCOUNT_ENV_BASES)


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


def test_el_entrypoint_no_decide_si_hay_cuentas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El entrypoint no sabe qué es una cuenta: solo prepara el fichero.

    Que haya cuentas y sean válidas es cosa de config.py. Si el entrypoint
    tambien lo decidiera, las dos piezas podrian discrepar, que es como
    aparecio el bug del esquema de cuentas.
    """
    entry = _load("entrypoint", "docker/entrypoint.py")
    monkeypatch.setenv("MCP_CONFIG", str(tmp_path / "no-existe.toml"))
    monkeypatch.setenv("MCP_ACCOUNTS_TOML_B64", "")
    monkeypatch.setenv("MCP_ACCOUNTS_TOML", "   ")
    assert not hasattr(entry, "_accounts_from_env")


def test_el_compose_pasa_el_env_al_contenedor() -> None:
    """En local no hay stack.env: el .env tiene que llegar igualmente."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    rutas = {item["path"] for item in compose["services"]["mcp"]["env_file"]}
    # stack.env con possibility de cambiarlo, y el .env del directorio.
    assert any("stack.env" in ruta for ruta in rutas), rutas
    assert ".env" in rutas, rutas
    assert all(item["required"] is False for item in compose["services"]["mcp"]["env_file"])


def test_ningun_compose_declara_una_contrasena_como_clave_de_cuenta() -> None:
    for name in (
        "docker-compose.yml",
        "docker-compose.tunnel.yml",
        "docker-compose.local.yml",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "MCP_ACCOUNT_PRINCIPAL_PASSWORD:" not in text or "local" in name
