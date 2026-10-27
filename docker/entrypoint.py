"""Prepara accounts.toml y ejecuta el proceso. No guarda secretos en la imagen.

Tres orígenes para el fichero, en este orden:

1. Un `accounts.toml` montado (volumen, bind o config de Docker).
2. El texto de `MCP_ACCOUNTS_TOML_B64` o `MCP_ACCOUNTS_TOML`.

Si no hay ninguno, no se genera nada y el proceso sigue: la configuración
puede venir entera por variables de entorno (`MCP_ACCOUNT_<CAMPO>_<N>`).

Esta función solo prepara el fichero. Si no hay cuentas, o no son válidas, es
cosa de `config.py`, que es quien sabe qué es una cuenta y puede dar el
mensaje que toca. Aquí no se decide eso, para que las dos piezas no puedan
discrepar.

El fichero generado vive en tmpfs con modo 0600 y no queda en la imagen.
"""

from __future__ import annotations

import base64
import binascii
import os
import sys
import tomllib
from pathlib import Path

DEFAULT_CONFIG_PATHS = ("/config/accounts.toml", "accounts.toml")


def resolve_accounts_file() -> str | None:
    """Ruta del accounts.toml a usar, o None si la configuración va por entorno."""
    configured = os.environ.get("MCP_CONFIG", "").strip()

    # 1. Fichero montado o ruta explícita.
    if configured:
        path = Path(configured)
        if path.is_file():
            os.environ["MCP_CONFIG"] = str(path)
            print(f"Usando accounts.toml en {path}", file=sys.stderr)
            return str(path)

    # 2. Fichero en una ruta por defecto.
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

    # 4. No hay TOML. Si la configuración va por entorno, sigue; si no,
    # config.py avisará de que faltan las cuentas.
    if configured:
        print(f"{configured} no existe.", file=sys.stderr)
        os.environ.pop("MCP_CONFIG", None)
    return None


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
    """Ninguna clave de contraseña, ni entrecomillada ni con espacios alrededor."""
    for line in text.splitlines():
        code = line.split("#", 1)[0].strip()
        key = code.split("=", 1)[0].strip()
        # La clave puede venir entrecomillada: "password" = "secreto"
        if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
            key = key[1:-1].strip()
        if key.lower() == "password":
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
