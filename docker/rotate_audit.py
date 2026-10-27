"""Rota el JSONL de auditoría en el volumen. El servidor abre el fichero en cada línea."""

from __future__ import annotations

import os
import time
from pathlib import Path


def rotate_once(path: Path, max_bytes: int, keep: int) -> bool:
    """Renombra audit.jsonl cuando supera el tamaño. Devuelve si rotó."""
    if keep < 1 or max_bytes < 1 or not path.is_file():
        return False
    if path.stat().st_size < max_bytes:
        return False
    oldest = path.with_name(f"{path.name}.{keep}")
    if oldest.exists():
        oldest.unlink()
    for index in range(keep - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        if source.exists():
            source.rename(path.with_name(f"{path.name}.{index + 1}"))
    path.rename(path.with_name(f"{path.name}.1"))
    return True


def _entero(nombre: str, defecto: int) -> int:
    """Un entero del entorno, con un mensaje claro si no lo es."""
    raw = os.environ.get(nombre, str(defecto)).strip()
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"{nombre} debe ser un entero (no {raw!r}).") from None


def main() -> None:
    path = Path(os.environ.get("MCP_AUDIT_LOG", "/var/log/mcp-correo/audit.jsonl"))
    max_bytes = _entero("MCP_AUDIT_MAX_BYTES", 10485760)
    keep = _entero("MCP_AUDIT_KEEP", 12)
    interval = _entero("MCP_AUDIT_ROTATE_SECONDS", 3600)
    # Un servicio que no dice nada parece muerto. Se dice qué está vigilando.
    print(
        f"Rotador de auditoría: {path} (cada {interval}s, desde {max_bytes} bytes, {keep} copias)",
        flush=True,
    )
    while True:
        try:
            if rotate_once(path, max_bytes, keep):
                print(f"Auditoría rotada: {path}", flush=True)
        except OSError as exc:
            print(f"No se pudo rotar la auditoría: {exc.strerror}", flush=True)
        time.sleep(max(interval, 1))


if __name__ == "__main__":
    main()
