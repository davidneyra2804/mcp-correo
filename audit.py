"""Auditoría JSONL: una línea por tool, sin cuerpos ni credenciales."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REDACT_KEYS = frozenset(
    {
        "password",
        "token",
        "confirmation_id",
        "authorization",
        "body",
        "body_preview",
        "content",
        "content_base64",
        "attachments",
        "raw",
        "raw_message",
        "secret",
    }
)
_MAX_ARG_CHARS = 300


class AuditError(Exception):
    """No se pudo escribir la auditoría. El mensaje no incluye secretos."""


class AuditLog:
    def __init__(self, path: str | Path, secrets: list[str] | None = None) -> None:
        self.path = Path(path)
        self._secrets: set[str] = {item for item in (secrets or []) if item}
        self._lock = threading.Lock()
        self._secrets_lock = threading.Lock()

    def ensure(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o640)
        except OSError as exc:
            raise SystemExit(
                f"No se puede crear el registro de auditoría en {self.path}: {exc.strerror}"
            ) from None
        else:
            os.close(fd)

    def add_secrets(self, secrets: Iterable[str]) -> None:
        """Da de alta secretos que hay que tapar.

        Con cuentas dinámicas, los secretos cambian: una cuenta creada en
        el panel trae una contraseña y un token que no estaban al arrancar.
        """
        nuevos = {item for item in secrets if item}
        if not nuevos:
            return
        with self._secrets_lock:
            self._secrets |= nuevos

    def _snapshot_secrets(self) -> list[str]:
        with self._secrets_lock:
            return list(self._secrets)

    def record(self, tool: str, account: str, args: dict[str, Any]) -> None:
        secrets = self._snapshot_secrets()
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "tool": tool,
            "account": account,
            "args": _sanitize(args, secrets),
        }
        line = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
        line = _scrub(line, secrets)
        try:
            with self._lock:
                fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o640)
                with os.fdopen(fd, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError as exc:
            raise AuditError(f"No se pudo escribir la auditoría ({exc.strerror})") from None


def _sanitize(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _REDACT_KEYS:
                clean[str(key)] = "[redactado]"
            else:
                clean[str(key)] = _sanitize(item, secrets)
        return clean
    if isinstance(value, list | tuple):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        return _scrub(value[:_MAX_ARG_CHARS], secrets)
    if isinstance(value, bytes):
        return "[bytes]"
    return value


def _scrub(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret and secret in text:
            text = text.replace(secret, "***")
    return text
