"""Prepara accounts.toml y ejecuta el proceso. No guarda secretos en la imagen."""

from __future__ import annotations

import base64
import binascii
import os
import sys
import tomllib
from pathlib import Path


def resolve_accounts_file() -> str:
    """El fichero montado gana. Si no hay fichero, se genera desde el entorno."""
    configured = os.environ.get("MCP_CONFIG", "/config/accounts.toml")
    path = Path(configured)
    if path.is_file():
        print(f"Usando accounts.toml montado en {path}", file=sys.stderr)
        return str(path)
    text = _inline_toml()
    if text is None:
        raise SystemExit(
            "Falta accounts.toml. Monta el fichero en /config/accounts.toml "
            "(volumen, bind o config de Docker) o define MCP_ACCOUNTS_TOML_B64 "
            "o MCP_ACCOUNTS_TOML. La contraseña no va en ese texto: solo password_env."
        )
    _reject_inline_password(text)
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"La configuración generada no es TOML válido: {exc}") from None
    target = Path(os.environ.get("MCP_GENERATED_CONFIG", "/tmp/accounts.toml"))
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text if text.endswith("\n") else text + "\n")
    os.environ["MCP_CONFIG"] = str(target)
    print(f"accounts.toml generado en {target} (no queda en la imagen)", file=sys.stderr)
    return str(target)


def main() -> None:
    resolve_accounts_file()
    if len(sys.argv) < 2:
        raise SystemExit("Falta el comando a ejecutar")
    os.execvp(sys.argv[1], sys.argv[1:])


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


if __name__ == "__main__":
    main()
