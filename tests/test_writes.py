"""Escritura con mocks: sin red, sin credenciales reales."""

from __future__ import annotations

import asyncio
import base64
import json
import smtplib
from dataclasses import replace
from email import message_from_bytes
from pathlib import Path

import pytest
from imapclient.exceptions import CapabilityError
from mcp.server.mcpserver.exceptions import ToolError

from audit import AuditLog
from config import Account, ServerSettings
from mail.confirm import ConfirmationStore, SendQuota
from mail.errors import MailError
from mail.mutate import MailboxWriter
from mail.readonly import WritableIMAP
from mail.smtp_out import open_smtp
from server import TOOL_NAMES, build_mcp
from tests.fakes import FakeSMTP, sample_mailbox

ROOT = Path(__file__).resolve().parents[1]
_SAFE_FETCH = {"FLAGS", "ENVELOPE", "RFC822.SIZE", "UID", "INTERNALDATE", "BODYSTRUCTURE"}


class Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


class Rig:
    def __init__(self, tmp_path: Path, **options: object) -> None:
        trash = bool(options.pop("trash", True))
        drafts = bool(options.pop("drafts", False))
        send = bool(options.pop("send", True))
        mark = bool(options.pop("mark", True))
        delete = bool(options.pop("delete", True))
        draft = bool(options.pop("draft", False))
        self.fake, service, account = sample_mailbox(with_trash=trash, with_drafts=drafts)
        account = replace(
            account,
            allow_send=send,
            allow_mark=mark,
            allow_delete=delete,
            allow_drafts=draft,
        )
        settings = replace(
            service.settings,
            enable_send=send,
            enable_mark=mark,
            enable_delete=delete,
            enable_drafts=draft,
            confirm_ttl_seconds=600,
            max_recipients=int(options.pop("max_recipients", 5)),  # type: ignore[arg-type]
            max_sends_per_day=int(options.pop("max_sends_per_day", 5)),  # type: ignore[arg-type]
            max_delete_per_call=int(options.pop("max_delete_per_call", 5)),  # type: ignore[arg-type]
            max_mark_per_call=int(options.pop("max_mark_per_call", 5)),  # type: ignore[arg-type]
            **options,  # type: ignore[arg-type]
        )
        service.settings = settings
        service.accounts = {"principal": account}
        self.service = service
        self.account = account
        self.clock = Clock()
        self.smtp = FakeSMTP()
        self.writer = MailboxWriter(
            service,
            ConfirmationStore(settings.confirm_ttl_seconds, clock=self.clock),
            SendQuota(settings.max_sends_per_day, clock=self.clock),
            smtp_factory=lambda _account, _settings: self.smtp,
        )
        self.audit = AuditLog(tmp_path / "audit.jsonl", secrets=[account.password])
        self.mcp = build_mcp(service, self.audit, self.writer)

    def lines(self) -> str:
        return self.audit.path.read_text(encoding="utf-8")


def _json(result: object) -> dict:
    assert getattr(result, "is_error", False) is False
    return json.loads(result.content[0].text)  # type: ignore[attr-defined]


def _send(**extra: object) -> dict:
    payload: dict = {
        "account": "principal",
        "to": ["ana@example.com"],
        "subject": "Hola",
        "body": "CUERPO-SECRETO-DE-ENVIO",
    }
    payload.update(extra)
    return payload


def test_con_interruptores_apagados_la_tool_no_existe(tmp_path: Path) -> None:
    rig = Rig(tmp_path, send=False, mark=False, delete=False, draft=False, trash=False)
    missing = (
        "prepare_send",
        "send_message",
        "mark_read",
        "mark_unread",
        "prepare_delete",
        "delete_message",
        "create_draft",
    )

    async def run() -> None:
        listed = await rig.mcp.list_tools()
        assert {tool.name for tool in listed} == set(TOOL_NAMES)
        for name in missing:
            with pytest.raises(ToolError, match="Unknown tool"):
                await rig.mcp.call_tool(name, {"account": "principal"})

    asyncio.run(run())


def test_sin_cuenta_autorizada_tampoco_se_registra(tmp_path: Path) -> None:
    rig = Rig(tmp_path, send=False, mark=False, delete=False, draft=False)
    rig.service.settings = replace(rig.service.settings, enable_send=True, enable_delete=True)

    async def run() -> None:
        names = {tool.name for tool in await rig.mcp.list_tools()}
        assert "send_message" not in names
        assert "delete_message" not in names

    asyncio.run(run())
    # El MCP ya se construyó con las capacidades apagadas. Se reconstruye.
    rig.mcp = build_mcp(rig.service, rig.audit, rig.writer)

    async def again() -> None:
        names = {tool.name for tool in await rig.mcp.list_tools()}
        assert "send_message" not in names
        assert "prepare_delete" not in names

    asyncio.run(again())


def test_lecturas_siguen_sin_cambiar_flags(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    before = rig.fake.flag_snapshot()
    calls = {
        "list_accounts": {},
        "list_folders": {"account": "principal"},
        "list_messages": {"account": "principal", "unseen": True, "since": "2026-10-01"},
        "search_messages": {"account": "principal", "subject": "Presupuesto"},
        "get_message": {"account": "principal", "uid": 10},
        "get_attachment": {"account": "principal", "uid": 10, "index": 0},
        "find_unanswered": {"account": "principal"},
        "list_threads": {"account": "principal"},
    }

    async def run() -> None:
        listed = await rig.mcp.list_tools()
        by_name = {tool.name: tool for tool in listed}
        assert set(TOOL_NAMES) < set(by_name)
        assert "send_message" in by_name
        for name in TOOL_NAMES:
            assert by_name[name].annotations is not None
            assert by_name[name].annotations.read_only_hint is True
            assert by_name[name].annotations.destructive_hint is False
        assert by_name["prepare_send"].annotations.read_only_hint is True
        assert by_name["send_message"].annotations.read_only_hint is False
        assert by_name["delete_message"].annotations.destructive_hint is True
        assert by_name["mark_read"].annotations.idempotent_hint is True
        for name, arguments in calls.items():
            result = await rig.mcp.call_tool(name, arguments)
            assert result.is_error is False

    asyncio.run(run())
    assert rig.fake.flag_snapshot() == before
    assert rig.fake.mutated is False
    assert rig.fake.selects
    assert all(readonly for _folder, readonly in rig.fake.selects)
    for batch in rig.fake.fetch_items:
        for item in batch:
            upper = item.upper()
            assert "PEEK" in upper or upper in _SAFE_FETCH


def test_el_proxy_de_escritura_sigue_usando_peek() -> None:
    fake, _service, _account = sample_mailbox()
    proxy = WritableIMAP(fake)
    proxy.select_folder("INBOX", readonly=False)
    proxy.fetch([10], ["BODY[]"])
    assert fake.selects[-1] == ("INBOX", False)
    assert fake.fetch_items[-1] == ["BODY.PEEK[]"]
    assert b"\\Seen" not in fake.folders["INBOX"].messages[10].flags
    with pytest.raises(MailError, match="no permitida"):
        proxy.delete_folder("INBOX")


def test_el_agente_sabe_que_preparar_no_envia(tmp_path: Path) -> None:
    """La descripción de la tool y el aviso de la respuesta explican el flujo.

    El fallo que motivó esto: el agente llamaba a prepare_send, creía que el
    correo salía y no sabía que tenía que llamar después a send_message. Las
    tres capas (descripción de la tool, respuesta y notice) tienen que
    decirlo, porque no se puede depender de que el cliente trasmita las
    instrucciones generales del servidor.
    """
    rig = Rig(tmp_path)

    async def run() -> None:
        by_name = {tool.name: tool for tool in await rig.mcp.list_tools()}

        prepare = by_name["prepare_send"].description or ""
        assert "NO envía" in prepare
        assert "send_message" in prepare
        assert "confirm_token" in prepare

        send = by_name["send_message"].description or ""
        assert "prepare_send" in send
        assert "confirm_token" in send
        assert "orden explícita" in send

        prepared = _json(await rig.mcp.call_tool("prepare_send", _send()))
        # El estado no depende de la prosa: hay un campo que lo dice.
        assert prepared["status"] == "prepared"
        assert prepared["sent"] is False
        assert prepared["next_tool"] == "send_message"
        notice = prepared["notice"]
        assert "NO enviado" in notice
        assert "send_message" in notice
        assert "orden explícita" in notice

        sent = _json(
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirm_token": prepared["confirm_token"]},
            )
        )
        assert sent["status"] == "sent"
        assert sent["sent"] is True

    asyncio.run(run())


def test_el_borrado_dice_que_no_borra_y_a_que_tool_segue(tmp_path: Path) -> None:
    """El mismo contrato, en el borrado: preparar no borra y hay un paso dos."""
    rig = Rig(tmp_path)

    async def run() -> None:
        by_name = {tool.name: tool for tool in await rig.mcp.list_tools()}

        prepare = by_name["prepare_delete"].description or ""
        assert "NO borra" in prepare
        assert "delete_message" in prepare

        delete = by_name["delete_message"].description or ""
        assert "prepare_delete" in delete
        assert "orden explícita" in delete

        prepared = _json(
            await rig.mcp.call_tool(
                "prepare_delete", {"account": "principal", "uids": [10], "folder": "INBOX"}
            )
        )
        assert prepared["status"] == "prepared"
        assert prepared["deleted"] is False
        assert prepared["next_tool"] == "delete_message"
        assert "NO borrado" in prepared["notice"]
        assert "delete_message" in prepared["notice"]

        deleted = _json(
            await rig.mcp.call_tool(
                "delete_message",
                {"account": "principal", "confirm_token": prepared["confirm_token"]},
            )
        )
        assert deleted["status"] == "deleted"
        assert deleted["deleted"] is True

    asyncio.run(run())


def test_envio_exige_token_de_un_solo_uso(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    async def run() -> None:
        with pytest.raises(ToolError, match="confirm_token"):
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirm_token": "   "},
            )
        prepared = _json(
            await rig.mcp.call_tool(
                "prepare_send",
                _send(
                    in_reply_to="<factura@example.com>",
                    references="<factura@example.com>",
                ),
            )
        )
        token = prepared["confirm_token"]
        assert prepared["from"] == "ada@example.com"
        assert "CUERPO-SECRETO-DE-ENVIO" in prepared["body_preview"]
        assert prepared["notice"]
        sent = _json(
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirm_token": token},
            )
        )
        assert sent["sent"] is True
        assert sent["copy_in_sent"] is True
        with pytest.raises(ToolError, match="ya usado"):
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirm_token": token},
            )

    asyncio.run(run())
    assert len(rig.smtp.sent) == 1
    assert rig.smtp.quit_called is True
    wire = message_from_bytes(rig.smtp.sent[0])
    assert wire["To"] == "ana@example.com"
    assert wire["In-Reply-To"] == "<factura@example.com>"
    assert wire["References"] == "<factura@example.com>"
    assert wire["From"] == "ada@example.com"
    stored = rig.fake.folders["Sent"].messages[2]
    assert b"\\Seen" in stored.flags
    copied = message_from_bytes(stored.raw)
    assert copied["Subject"] == "Hola"
    assert b"\\Seen" not in rig.fake.folders["INBOX"].messages[10].flags


def test_los_destinatarios_ocultos_no_quedan_en_enviados(tmp_path: Path) -> None:
    """El Bcc sale por SMTP, pero no se guarda en la copia de Enviados.

    Si se guardara, los destinatarios ocultos quedarían a la vista en el
    buzón de enviados, que es justo lo que se ocultaron.
    """
    rig = Rig(tmp_path)

    async def run() -> None:
        preview = _json(
            await rig.mcp.call_tool(
                "prepare_send",
                {
                    "account": "principal",
                    "to": ["ana@example.com"],
                    "bcc": ["oculto@example.com"],
                    "subject": "Hola",
                    "body": "Cuerpo",
                },
            )
        )
        token = preview["confirm_token"]
        await rig.mcp.call_tool(
            "send_message",
            {"account": "principal", "confirm_token": token},
        )

    asyncio.run(run())
    # Lo que sale por SMTP lleva el Bcc: los destinatarios lo reciben.
    wire = message_from_bytes(rig.smtp.sent[0])
    assert wire["Bcc"] == "oculto@example.com"
    # Lo que se guarda en Enviados, no.
    stored = rig.fake.folders["Sent"].messages[2]
    copied = message_from_bytes(stored.raw)
    assert copied["Bcc"] is None
    assert b"oculto@example.com" not in stored.raw


def test_el_token_caduca_y_no_cruza_cuenta_ni_operacion(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.service.accounts["archivo"] = replace(
        rig.account,
        key="archivo",
        username="ada.archivo@example.com",
        allow_send=True,
        allow_delete=True,
    )

    async def run() -> None:
        prepared = _json(await rig.mcp.call_tool("prepare_send", _send()))
        token = prepared["confirm_token"]
        rig.clock.now += 601
        with pytest.raises(ToolError, match="caducado"):
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirm_token": token},
            )
        rig.clock.now -= 601
        fresh = _json(await rig.mcp.call_tool("prepare_send", _send(subject="Otro")))
        other = fresh["confirm_token"]
        with pytest.raises(ToolError, match="no corresponde"):
            await rig.mcp.call_tool("send_message", {"account": "archivo", "confirm_token": other})
        with pytest.raises(ToolError, match="no corresponde"):
            await rig.mcp.call_tool(
                "delete_message",
                {"account": "principal", "confirm_token": other},
            )
        sent = _json(
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirm_token": other},
            )
        )
        assert sent["sent"] is True

    asyncio.run(run())
    assert len(rig.smtp.sent) == 1


def test_borrado_va_a_la_papelera_y_el_definitivo_es_aparte(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    before = rig.fake.flag_snapshot()

    async def run() -> None:
        prepared = _json(
            await rig.mcp.call_tool(
                "prepare_delete", {"account": "principal", "uids": [10], "folder": "INBOX"}
            )
        )
        assert prepared["permanent"] is False
        assert prepared["trash_folder"] == "Trash"
        assert prepared["subjects"] == ["Presupuesto"]
        assert rig.fake.flag_snapshot() == before
        assert all(readonly for _folder, readonly in rig.fake.selects)
        deleted = _json(
            await rig.mcp.call_tool(
                "delete_message",
                {"account": "principal", "confirm_token": prepared["confirm_token"]},
            )
        )
        assert deleted["permanent"] is False
        assert deleted["trash_folder"] == "Trash"
        with pytest.raises(ToolError, match="ya usado"):
            await rig.mcp.call_tool(
                "delete_message",
                {"account": "principal", "confirm_token": prepared["confirm_token"]},
            )

    asyncio.run(run())
    assert 10 not in rig.fake.folders["INBOX"].messages
    assert b"\\Seen" in rig.fake.folders["INBOX"].messages[11].flags
    assert b"\\Answered" in rig.fake.folders["INBOX"].messages[11].flags
    assert b"\\Seen" not in rig.fake.folders["INBOX"].messages[13].flags
    trash = next(iter(rig.fake.folders["Trash"].messages.values()))
    assert b"Presupuesto" in trash.raw

    rig.fake.folders["INBOX"].messages[12].flags.add(b"\\Deleted")

    async def definitive() -> None:
        prepared = _json(
            await rig.mcp.call_tool(
                "prepare_delete",
                {"account": "principal", "uids": [13], "permanent": True},
            )
        )
        assert prepared["permanent"] is True
        assert prepared["trash_folder"] == ""
        await rig.mcp.call_tool(
            "delete_message",
            {"account": "principal", "confirm_token": prepared["confirm_token"]},
        )

    asyncio.run(definitive())
    assert 13 not in rig.fake.folders["INBOX"].messages
    assert 12 in rig.fake.folders["INBOX"].messages
    assert b"\\Deleted" in rig.fake.folders["INBOX"].messages[12].flags
    assert all(b"Presupuesto" in item.raw for item in rig.fake.folders["Trash"].messages.values())
    assert not any(
        b"Aviso HTML" in item.raw for item in rig.fake.folders["Trash"].messages.values()
    )


def test_sin_papelera_no_hay_borrado_salvo_permanent(tmp_path: Path) -> None:
    rig = Rig(tmp_path, trash=False)

    async def run() -> None:
        with pytest.raises(ToolError, match="Papelera"):
            await rig.mcp.call_tool("prepare_delete", {"account": "principal", "uids": [10]})
        prepared = _json(
            await rig.mcp.call_tool(
                "prepare_delete",
                {"account": "principal", "uids": [10], "permanent": True},
            )
        )
        await rig.mcp.call_tool(
            "delete_message",
            {"account": "principal", "confirm_token": prepared["confirm_token"]},
        )

    asyncio.run(run())
    assert 10 not in rig.fake.folders["INBOX"].messages
    assert rig.fake.mutated is True


def test_si_no_hay_move_copia_y_expunge_solo_esos_uid(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.fake.folders["INBOX"].messages[11].flags.add(b"\\Deleted")

    def no_move(*_args: object, **_kwargs: object) -> None:
        raise CapabilityError("sin MOVE")

    rig.fake.move = no_move  # type: ignore[method-assign]

    async def run() -> None:
        prepared = _json(
            await rig.mcp.call_tool("prepare_delete", {"account": "principal", "uids": [10]})
        )
        await rig.mcp.call_tool(
            "delete_message",
            {"account": "principal", "confirm_token": prepared["confirm_token"]},
        )

    asyncio.run(run())
    assert 10 not in rig.fake.folders["INBOX"].messages
    assert 11 in rig.fake.folders["INBOX"].messages
    assert b"\\Deleted" in rig.fake.folders["INBOX"].messages[11].flags
    assert any(b"Presupuesto" in item.raw for item in rig.fake.folders["Trash"].messages.values())
    assert "copy" in rig.fake.calls
    assert "expunge" in rig.fake.calls


def test_marcar_leido_y_no_leido(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    async def run() -> None:
        read = _json(
            await rig.mcp.call_tool("mark_read", {"account": "principal", "uids": [10, 13]})
        )
        assert read["action"] == "add"
        unread = _json(
            await rig.mcp.call_tool(
                "mark_unread", {"account": "principal", "uids": [11], "folder": "INBOX"}
            )
        )
        assert unread["action"] == "remove"

    asyncio.run(run())
    inbox = rig.fake.folders["INBOX"].messages
    assert b"\\Seen" in inbox[10].flags
    assert b"\\Seen" in inbox[13].flags
    assert b"\\Seen" not in inbox[11].flags
    assert b"\\Answered" in inbox[11].flags
    assert b"\\Seen" not in inbox[12].flags
    rw = [folder for folder, readonly in rig.fake.selects if not readonly]
    assert rw == ["INBOX", "INBOX"]
    blob = rig.lines()
    assert "mark_read" in blob
    assert "mark_unread" in blob
    assert "CUERPO-SECRETO-DE-PRUEBA" not in blob


def test_auditoria_de_escritura_sin_cuerpo_ni_token(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    secret = base64.b64encode(b"contenido-secreto-adjunto").decode()
    subject = f"Aviso {rig.account.password}"

    async def run() -> str:
        prepared = _json(
            await rig.mcp.call_tool(
                "prepare_send",
                _send(
                    subject=subject,
                    attachments=[
                        {
                            "filename": "nota.txt",
                            "content_type": "text/plain",
                            "content_base64": secret,
                        }
                    ],
                ),
            )
        )
        await rig.mcp.call_tool(
            "send_message",
            {"account": "principal", "confirm_token": prepared["confirm_token"]},
        )
        return prepared["confirm_token"]

    token = asyncio.run(run())
    blob = rig.lines()
    assert "CUERPO-SECRETO-DE-ENVIO" not in blob
    assert secret not in blob
    assert "contenido-secreto-adjunto" not in blob
    assert rig.account.password not in blob
    assert token not in blob
    assert "nota.txt" in blob
    assert "filenames" in blob
    assert "Aviso ***" in blob
    parsed = [json.loads(line) for line in blob.splitlines()]
    assert {line["tool"] for line in parsed} >= {"prepare_send", "send_message"}
    assert all("body" not in line["args"] for line in parsed)
    assert all("confirm_token" not in line["args"] for line in parsed)


def test_limites_cupo_dominio_y_adjunto(tmp_path: Path) -> None:
    rig = Rig(
        tmp_path,
        max_recipients=2,
        max_sends_per_day=1,
        max_attachment_bytes=4,
        allowed_recipient_domains=("example.com",),
    )

    async def run() -> None:
        with pytest.raises(ToolError, match="destinatarios"):
            await rig.mcp.call_tool(
                "prepare_send",
                _send(to=["ana@example.com", "luis@example.com", "bea@example.com"]),
            )
        with pytest.raises(ToolError, match="dominio"):
            await rig.mcp.call_tool("prepare_send", _send(to=["ana@otro.test"]))
        encoded = base64.b64encode(b"12345").decode()
        with pytest.raises(ToolError, match="límite"):
            await rig.mcp.call_tool(
                "prepare_send",
                _send(
                    attachments=[
                        {
                            "filename": "grande.txt",
                            "content_type": "text/plain",
                            "content_base64": encoded,
                        }
                    ]
                ),
            )
        first = _json(await rig.mcp.call_tool("prepare_send", _send(subject="Uno")))
        second = _json(await rig.mcp.call_tool("prepare_send", _send(subject="Dos")))
        await rig.mcp.call_tool(
            "send_message", {"account": "principal", "confirm_token": first["confirm_token"]}
        )
        with pytest.raises(ToolError, match="Tope diario"):
            await rig.mcp.call_tool(
                "send_message", {"account": "principal", "confirm_token": second["confirm_token"]}
            )
        with pytest.raises(ToolError, match="ya usado"):
            await rig.mcp.call_tool(
                "send_message", {"account": "principal", "confirm_token": second["confirm_token"]}
            )
        with pytest.raises(ToolError, match="Tope diario"):
            await rig.mcp.call_tool("prepare_send", _send(subject="Tres"))

    asyncio.run(run())
    assert len(rig.smtp.sent) == 1
    assert rig.writer.quota.remaining("principal") == 0


def test_fallo_smtp_gasta_el_token_y_no_el_cupo(tmp_path: Path) -> None:
    rig = Rig(tmp_path, max_sends_per_day=1)
    rig.smtp.fail_send = True

    async def run() -> None:
        prepared = _json(await rig.mcp.call_tool("prepare_send", _send()))
        with pytest.raises(ToolError, match="SMTP") as caught:
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirm_token": prepared["confirm_token"]},
            )
        assert "rechazo de prueba" not in str(caught.value)
        assert rig.account.password not in str(caught.value)
        with pytest.raises(ToolError, match="ya usado"):
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirm_token": prepared["confirm_token"]},
            )
        assert rig.writer.quota.remaining("principal") == 1
        rig.smtp.fail_send = False
        again = _json(await rig.mcp.call_tool("prepare_send", _send(subject="Reintento")))
        sent = _json(
            await rig.mcp.call_tool(
                "send_message", {"account": "principal", "confirm_token": again["confirm_token"]}
            )
        )
        assert sent["sent"] is True

    asyncio.run(run())
    assert len(rig.smtp.sent) == 1


def test_si_falla_la_copia_en_enviados_el_correo_sigue_enviado(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.account = replace(rig.account, sent_folder="NoExiste")
    rig.service.accounts["principal"] = rig.account

    async def run() -> None:
        prepared = _json(await rig.mcp.call_tool("prepare_send", _send()))
        sent = _json(
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirm_token": prepared["confirm_token"]},
            )
        )
        assert sent["sent"] is True
        assert sent["copy_in_sent"] is False

    asyncio.run(run())
    assert len(rig.smtp.sent) == 1
    assert set(rig.fake.folders["Sent"].messages) == {1}


def test_la_cuenta_sin_permiso_no_opera(tmp_path: Path) -> None:
    rig = Rig(tmp_path, send=False, delete=False, mark=False)
    rig.service.accounts["otra"] = replace(
        rig.account,
        key="otra",
        username="otra@example.com",
        allow_send=True,
        allow_delete=True,
        allow_mark=True,
    )
    rig.service.settings = replace(
        rig.service.settings,
        enable_send=True,
        enable_delete=True,
        enable_mark=True,
    )
    rig.mcp = build_mcp(rig.service, rig.audit, rig.writer)

    async def run() -> None:
        names = {tool.name for tool in await rig.mcp.list_tools()}
        assert "send_message" in names
        with pytest.raises(ToolError, match="desactivado"):
            await rig.mcp.call_tool("prepare_send", _send())
        with pytest.raises(ToolError, match="desactivado"):
            await rig.mcp.call_tool("mark_read", {"account": "principal", "uids": [10]})
        with pytest.raises(ToolError, match="desactivado"):
            await rig.mcp.call_tool("prepare_delete", {"account": "principal", "uids": [10]})

    asyncio.run(run())
    assert rig.fake.mutated is False
    assert b"\\Seen" not in rig.fake.folders["INBOX"].messages[10].flags


def test_borrador_hace_append_sin_abrir_en_escritura(tmp_path: Path) -> None:
    rig = Rig(
        tmp_path,
        drafts=True,
        draft=True,
        send=False,
        allowed_recipient_domains=("otro.test",),
    )

    async def run() -> None:
        saved = _json(
            await rig.mcp.call_tool(
                "create_draft",
                {
                    "account": "principal",
                    "to": ["ana@example.com"],
                    "subject": "Borrador",
                    "body": "texto que no debe auditarse",
                },
            )
        )
        assert saved["saved"] is True
        assert saved["folder"] == "Drafts"
        with pytest.raises(ToolError, match="destinatarios"):
            await rig.mcp.call_tool(
                "create_draft",
                {
                    "account": "principal",
                    "to": [
                        "a@example.com",
                        "b@example.com",
                        "c@example.com",
                        "d@example.com",
                        "e@example.com",
                        "f@example.com",
                    ],
                    "subject": "Demasiados",
                    "body": "x",
                },
            )

    asyncio.run(run())
    draft = next(iter(rig.fake.folders["Drafts"].messages.values()))
    assert b"\\Draft" in draft.flags
    assert b"Borrador" in draft.raw
    assert rig.fake.selects == []
    assert "append" in rig.fake.calls
    assert "texto que no debe auditarse" not in rig.lines()
    assert rig.smtp.sent == []


def test_demasiados_mensajes_en_un_borrado(tmp_path: Path) -> None:
    rig = Rig(tmp_path, max_delete_per_call=1)

    async def run() -> None:
        with pytest.raises(ToolError, match="máximo"):
            await rig.mcp.call_tool("prepare_delete", {"account": "principal", "uids": [10, 13]})

    asyncio.run(run())
    assert 10 in rig.fake.folders["INBOX"].messages


def test_smtp_ssl_y_starttls_no_abren_red(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class Dummy:
        def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
            seen["endpoint"] = (host, port, timeout)

        def ehlo(self) -> None:
            seen["ehlo"] = int(seen.get("ehlo", 0)) + 1  # type: ignore[arg-type]

        def starttls(self) -> None:
            seen["starttls"] = True

    monkeypatch.setattr(
        smtplib, "SMTP_SSL", lambda host, port, timeout=None: Dummy(host, port, timeout)
    )
    monkeypatch.setattr(
        smtplib, "SMTP", lambda host, port, timeout=None: Dummy(host, port, timeout)
    )
    account = Account(
        key="principal",
        label="Prueba",
        imap_host="mail.example.com",
        imap_port=993,
        username="ada@example.com",
        password="clave-de-prueba-no-real",
        smtp_host="mail.example.com",
        smtp_port=465,
    )
    settings = ServerSettings(
        public_host="mcp.example.com",
        bind_host="127.0.0.1",
        bind_port=8765,
        max_results=10,
        max_chars=100,
        max_attachment_bytes=100,
        max_message_bytes=1000,
        imap_timeout=5,
        sent_scan_limit=10,
        allowed_hosts=("127.0.0.1",),
        allowed_origins=("http://127.0.0.1:*",),
        allowed_attachment_types=("text/plain",),
        audit_log="audit.jsonl",
        smtp_security="ssl",
        smtp_timeout=12,
    )
    open_smtp(account, settings)
    assert seen["endpoint"] == ("mail.example.com", 465, 12)
    assert "starttls" not in seen
    open_smtp(replace(account, smtp_port=587, smtp_security="starttls"), settings)
    assert seen["endpoint"] == ("mail.example.com", 587, 12)
    assert seen["starttls"] is True
    assert seen["ehlo"] == 2


def test_el_select_de_escritura_no_esta_en_el_codigo_de_lectura() -> None:
    mutate = (ROOT / "mail" / "mutate.py").read_text(encoding="utf-8")
    smtp = (ROOT / "mail" / "smtp_out.py").read_text(encoding="utf-8")
    assert "readonly=False" in mutate
    assert "import smtplib" in smtp
    for relative in ("mail/imap.py", "mail/readonly.py", "server.py", "mail/mime.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "readonly=False" not in source
        assert "import smtplib" not in source
