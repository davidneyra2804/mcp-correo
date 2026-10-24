from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from audit import AuditLog
from mail.errors import MailError
from mail.readonly import FORBIDDEN_METHODS, ReadOnlyIMAP, force_peek
from server import TOOL_NAMES, build_mcp
from tests.fakes import sample_mailbox

ROOT = Path(__file__).resolve().parents[1]
_SAFE_FETCH = {"FLAGS", "ENVELOPE", "RFC822.SIZE", "UID", "INTERNALDATE", "BODYSTRUCTURE"}


def test_peek_reemplaza_fetch_que_marcarian_visto() -> None:
    assert force_peek("BODY[]") == "BODY.PEEK[]"
    assert force_peek("RFC822") == "BODY.PEEK[]"
    assert force_peek("BODY[1]") == "BODY.PEEK[1]"
    assert force_peek("BODY.PEEK[HEADER]") == "BODY.PEEK[HEADER]"
    assert force_peek("RFC822.SIZE") == "RFC822.SIZE"
    assert force_peek("FLAGS") == "FLAGS"


def test_el_proxy_no_deja_escribir() -> None:
    fake, _service, _account = sample_mailbox()
    proxy = ReadOnlyIMAP(fake)
    before = fake.flag_snapshot()
    proxy.select_folder("INBOX", readonly=False)
    proxy.fetch([10], ["BODY[]", "RFC822"])
    assert fake.selects[-1] == ("INBOX", True)
    assert fake.fetch_items[-1] == ["BODY.PEEK[]", "BODY.PEEK[]"]
    for name in ("add_flags", "set_flags", "append", "move", "expunge", "delete_messages"):
        with pytest.raises(MailError, match="prohibida"):
            getattr(proxy, name)([10], [b"\\Seen"])
    assert fake.flag_snapshot() == before
    assert fake.mutated is False


def test_ninguna_tool_cambia_flags(tmp_path: Path) -> None:
    fake, service, _account = sample_mailbox()
    audit = AuditLog(tmp_path / "audit.jsonl", secrets=["clave-de-prueba-no-real"])
    mcp = build_mcp(service, audit)
    before = fake.flag_snapshot()

    calls = {
        "list_accounts": {},
        "list_folders": {"account": "vyrts"},
        "list_messages": {
            "account": "vyrts",
            "folder": "INBOX",
            "unseen": True,
            "since": "2026-10-01",
            "sender": "ana",
            "limit": 10,
        },
        "search_messages": {
            "account": "vyrts",
            "subject": "Presupuesto",
            "text": "presupuesto",
            "sender": "ana",
            "recipient": "david",
            "since": "2026-10-01",
            "before": "2026-10-31",
        },
        "get_message": {"account": "vyrts", "uid": 10, "folder": "INBOX"},
        "get_attachment": {"account": "vyrts", "uid": 10, "index": 0},
        "find_unanswered": {"account": "vyrts", "since": "2026-10-01"},
        "list_threads": {"account": "vyrts", "limit": 20},
    }
    assert set(calls) == set(TOOL_NAMES)

    async def exercise() -> None:
        listed = await mcp.list_tools()
        names = {tool.name for tool in listed}
        assert names == set(TOOL_NAMES)
        for tool in listed:
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.destructive_hint is False
        for name, arguments in calls.items():
            result = await mcp.call_tool(name, arguments)
            assert result.is_error is False

    asyncio.run(exercise())

    assert fake.flag_snapshot() == before
    assert fake.mutated is False
    assert fake.selects
    assert all(readonly for _folder, readonly in fake.selects)
    for batch in fake.fetch_items:
        for item in batch:
            upper = item.upper()
            assert "PEEK" in upper or upper in _SAFE_FETCH


def test_el_codigo_de_lectura_no_invoca_comandos_de_escritura() -> None:
    roots = [
        ROOT / "mail" / "imap.py",
        ROOT / "mail" / "threads.py",
        ROOT / "mail" / "mime.py",
        ROOT / "server.py",
    ]
    # `append` también es list.append; el proxy sí bloquea el append de IMAP.
    forbidden = (FORBIDDEN_METHODS - {"append"}) | {"smtplib", "sendmail", "send_message"}
    for path in roots:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                raise AssertionError(f"{path.name} llama a {node.attr}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "smtplib"
            if isinstance(node, ast.ImportFrom) and node.module == "smtplib":
                raise AssertionError(path.name)


def test_select_siempre_es_examine() -> None:
    sources = [
        (ROOT / "mail" / "imap.py").read_text(encoding="utf-8"),
        (ROOT / "mail" / "readonly.py").read_text(encoding="utf-8"),
        (ROOT / "server.py").read_text(encoding="utf-8"),
    ]
    for source in sources:
        assert "readonly=False" not in source
        assert "readonly = False" not in source
