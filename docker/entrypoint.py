"""Prepara accounts.toml y ejecuta el proceso. No guarda secretos en la imagen.

Tres orígenes, en este orden:

1. Un `accounts.toml` montado (volumen, bind o config de Docker).
2. El texto de `MCP_ACCOUNTS_TOML_B64` o `MCP_ACCOUNTS_TOML`.
3. Nada: la configuración va por variables de entorno (`MCP_ACCOUNTS` y
   `MCP_ACCOUNT_<CLAVE>_<CAMPO>`). En ese caso no se genera ningún fichero.

El fichero generado vive en tmpfs con modo 0600 y no queda en la imagen.
"""

from __future__ import annotations

import base64
import binascii
import os
import sys
import tomllib
from pathlib import Path

ACCOUNTS_LIST = "MCP_ACCOUNTS"
DEFAULT_CONFIG_PATHS = ("/config/accounts.toml", "accounts.toml")


def resolve_accounts_file() -> str | None:
    """Ruta del TOML a usar, o None si la configuración va solo por entorno."""
    configured = os.environ.get("MCP_CONFIG", "").strip()
    explicit = Path(configured) if configured else None

    # 1. Fichero montado o ruta explícita.
    if explicit is not None and explicit.is_file():
        os.environ["MCP_CONFIG"] = str(explicit)
        print(f"Usando accounts.toml en {explicit}", file=sys.stderr)
        return str(explicit)

    # 2. Fichero en la ruta por defecto del contenedor.
    for candidate in DEFAULT_CONFIG_PATHS:
        path = Path(candidate)
        if path.is_file():
            os.environ["MCP_CONFIG"] = str(path)
            print(f"Usando accounts.toml en {path}", file=sys.stderr)
            return str(path)

    # 3. Texto en base64 o plano. El fichero generado vive en tmpfs.
    text = _inline_toml()
    if text is not None:
        _reject_inline_password(text)
        _validate_toml(text)
        target = Path(os.environ.get("MCP_GENERATED_CONFIG", "/tmp/accounts.toml"))
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")
        os.environ["MCP_CONFIG"] = str(target)
        print(f"accounts.toml generado en {target} (no queda en la imagen)", file=sys.stderr)
        return str(target)

    # 4. Cuentas por variables de entorno: no hace falta TOML.
    if _accounts_from_env():
        if explicit is not None:
            print(
                f"{explicit} no existe. La configuración va por variables de entorno.",
                file=sys.stderr,
            )
        os.environ.pop("MCP_CONFIG", None)
        print(
            f"Configuración por variables de entorno ({ACCOUNTS_LIST}). "
            "No hace falta accounts.toml.",
            file=sys.stderr,
        )
        return None

    if explicit is not None:
        raise SystemExit(f"No se encuentra la configuración: {explicit}")
    raise SystemExit(
        "Falta la configuración. Define "
        f"{ACCOUNTS_LIST} con la lista de cuentas y una variable por campo "
        "(MCP_ACCOUNT_<CLAVE>_<CAMPO>), o monta un accounts.toml en "
        "/config/accounts.toml, o define MCP_ACCOUNTS_TOML_B64 o MCP_ACCOUNTS_TOML. "
        "La contraseña no va en ese texto: solo password_env."
    )


def main() -> None:
    resolve_accounts_file()
    if len(sys.argv) < 2:
        raise SystemExit("Falta el comando a ejecutar")
    os.execvp(sys.argv[1], sys.argv[1:])


def _accounts_from_env() -> bool:
    raw = os.environ.get(ACCOUNTS_LIST, "").strip()
    return bool(raw)


def _inline_toml() -> str | None:
    encoded = os.environ.get("MCP_ACCOUNTS_TOML_B64", "").strip()
    if encoded:
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SystemExit("MCP_ACCOUNTS_TOML_B64 no es base64 válido") from exc
        return raw.decode("utf-8")
    text = os.environ.get("MCP_ACCOUNTS_TOML", "")
    if not text.strip():
        return None
    if "\n" not in text and "\\n" in text:
        text = text.replace("\\n", "\n")
    return text


def _reject_inline_password(text: str) -> None:
    for line in text.splitlines():
        code = line.split("#", 1)[0].strip()
        key = code.split("=", 1)[0].strip()
        if key == "password":
            raise SystemExit(
                "La configuración trae una contraseña. Usa solo password_env "
                "y pasa el secreto como variable de entorno."
            )


def _validate_toml(text: str) -> None:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"La configuración generada no es TOML válido: {exc}") from None


if __name__ == "__main__":
    main()
