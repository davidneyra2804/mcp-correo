"""Entorno ficticio. Tiene que ejecutarse antes de importar `server`."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault(
    "MCP_BEARER_TOKEN",
    "token-de-prueba-no-real-0123456789abcdef",
)
os.environ.setdefault("MCP_CONFIG", str(ROOT / "accounts.example.toml"))
os.environ.setdefault("MCP_AUDIT_LOG", "/tmp/mcp-correo-test-audit.jsonl")
os.environ.setdefault("MAIL_PRINCIPAL_PASSWORD", "clave-ficticia-principal")
os.environ.setdefault("MAIL_ARCHIVO_PASSWORD", "clave-ficticia-archivo")
os.environ.setdefault("MCP_BIND_HOST", "127.0.0.1")
