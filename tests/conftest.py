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
os.environ.setdefault("MCP_AUDIT_LOG", "/tmp/vyr-mail-mcp-test-audit.jsonl")
os.environ.setdefault("MAIL_VYRTS_PASSWORD", "clave-ficticia-vyrts")
os.environ.setdefault("MAIL_CARBONIO_PASSWORD", "clave-ficticia-carbonio")
os.environ.setdefault("MCP_BIND_HOST", "127.0.0.1")
