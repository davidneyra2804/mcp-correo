from __future__ import annotations

import asyncio
import json
from pathlib import Path

from audit import AuditLog
from server import build_mcp
from tests.fakes import sample_mailbox


def test_la_auditoria_no_guarda_cuerpos_ni_claves(tmp_path: Path) -> None:
    _fake, service, account = sample_mailbox()
    audit = AuditLog(
        tmp_path / "audit.jsonl",
        secrets=[account.password, "token-de-prueba-no-real-0123456789abcdef"],
    )
    mcp = build_mcp(service, audit)

    async def run() -> None:
        await mcp.call_tool("get_message", {"account": "vyrts", "uid": 10})
        await mcp.call_tool(
            "search_messages",
            {"account": "vyrts", "subject": account.password},
        )

    asyncio.run(run())
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    blob = "\n".join(lines)
    assert "CUERPO-SECRETO-DE-PRUEBA" not in blob
    assert account.password not in blob
    assert "contenido-adjunto" not in blob
    first = json.loads(lines[0])
    assert first["tool"] == "get_message"
    assert first["account"] == "vyrts"
    assert first["args"]["uid"] == 10
    assert "body" not in first["args"]
    second = json.loads(lines[1])
    assert second["args"]["subject"] == "***"
