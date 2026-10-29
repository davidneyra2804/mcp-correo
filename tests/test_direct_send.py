"""El envío directo: una llamada, sin confirmación por mensaje.

Lo que se vigila aquí:

- Apagado por defecto, y con su propio permiso, independiente del envío
  normal.
- La idempotencia: la misma clave no vuelve a enviar; la misma clave con
  otro contenido se rechaza.
- La clave sobrevive a un reinicio del servidor (vive en la base).
- Un fallo del SMTP libera la clave: se puede reintentar.
- La tool no existe si el permiso no está dado, y `list_accounts` dice
  qué puede hacer cada cuenta.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mail.confirm import ConfirmationStore, SendQuota
from mail.mutate import MailboxWriter
from server import build_mcp
from store.db import Database
from store.direct_send import DirectSendStore
from tests.fakes import FakeSMTP, sample_mailbox


def _json(result: object) -> dict:
    assert getattr(result, "is_error", False) is False
    return json.loads(result.content[0].text)  # type: ignore[attr-defined]


class DirectRig:
    """Un servidor con envío directo habilitado y su base de datos."""

    def __init__(self, tmp_path: Path, *, enabled: bool = True, allowed: bool = True) -> None:
        self.fake, service, account = sample_mailbox(with_trash=True, with_drafts=True)
        self.account = replace(account, allow_direct_send=allowed)
        self.service = service
        self.service.settings = replace(
            service.settings,
            enable_direct_send=enabled,
            enable_send=False,
            max_sends_per_day=5,
            max_recipients=5,
        )
        self.service.accounts = {"principal": self.account}
        self.db = Database(tmp_path / "cuentas.db")
        self.db.prepare()
        self.smtp = FakeSMTP()
        self.writer = MailboxWriter(
            service,
            ConfirmationStore(600),
            SendQuota(5),
            smtp_factory=lambda _a, _s: self.smtp,
            direct_store=DirectSendStore(self.db),
        )
        from audit import AuditLog

        self.audit = AuditLog(tmp_path / "audit.jsonl", secrets=[account.password])
        self.mcp = build_mcp(service, self.audit, self.writer)

    def _send(self, **extra: object) -> dict:
        payload: dict = {
            "account": "principal",
            "to": ["ana@example.com"],
            "subject": "Pendiente de Trello",
            "body": "Contenido del correo",
            "idempotency_key": "trello-tarea-42",
        }
        payload.update(extra)
        return payload

    def _sin_clave(self) -> dict:
        payload = self._send()
        payload.pop("idempotency_key")
        return payload

    async def call(self, name: str, **extra: object) -> dict:
        return _json(await self.mcp.call_tool(name, self._send(**extra)))


# --- el interruptor -------------------------------------------------------------


def test_apagado_por_defecto_la_tool_no_existe(tmp_path: Path) -> None:
    rig = DirectRig(tmp_path, enabled=False)

    async def run() -> None:
        names = {tool.name for tool in await rig.mcp.list_tools()}
        assert "send_message_direct" not in names

    asyncio.run(run())


def test_encendido_pero_sin_permiso_por_cuenta_no_se_puede_usar(tmp_path: Path) -> None:
    """Con cuentas estáticas, la tool no se registra si nadie la permite."""
    rig = DirectRig(tmp_path, enabled=True, allowed=False)

    async def run() -> None:
        names = {tool.name for tool in await rig.mcp.list_tools()}
        assert "send_message_direct" not in names

    asyncio.run(run())
    assert rig.smtp.sent == []


def test_el_permiso_directo_no_hereda_del_envio_normal(tmp_path: Path) -> None:
    """`allow_send` no habilita el envío directo, y al revés."""
    rig = DirectRig(tmp_path, enabled=True, allowed=False)
    rig.account = replace(rig.account, allow_send=True)
    rig.service.accounts = {"principal": rig.account}

    async def run() -> None:
        names = {tool.name for tool in await rig.mcp.list_tools()}
        assert "send_message_direct" not in names

    asyncio.run(run())


def test_list_accounts_dice_si_la_cuenta_puede_enviar_directo(tmp_path: Path) -> None:
    rig = DirectRig(tmp_path, enabled=True, allowed=True)

    async def run() -> None:
        cuentas = _json(await rig.mcp.call_tool("list_accounts", {}))
        assert cuentas["accounts"][0]["can_send_direct"] is True

    asyncio.run(run())


def test_con_cuentas_del_panel_el_permiso_se_comprueba_en_cada_llamada(tmp_path: Path) -> None:
    """Con cuentas dinámicas, la tool existe y el permiso se comprueba al llamar.

    Es el caso del despliegue real: el panel añade cuentas y las activa o
    las apaga sin reiniciar, así que el catálogo de tools no puede depender
    de lo que hay en un momento dado.
    """
    from config import write_capabilities

    rig = DirectRig(tmp_path, enabled=True, allowed=False)
    # Con cuentas dinámicas, el registro depende solo del interruptor global.
    caps = write_capabilities(rig.service.settings, rig.service.accounts, dynamic=True)
    assert caps["direct_send"] is True
    rig.mcp = build_mcp(rig.service, rig.audit, rig.writer, dynamic=True)

    async def run() -> None:
        with pytest.raises(ToolError, match="directo"):
            await rig.mcp.call_tool("send_message_direct", rig._send())

    asyncio.run(run())
    assert rig.smtp.sent == []


# --- el envío en una sola llamada -----------------------------------------------


def test_una_sola_llamada_envia(tmp_path: Path) -> None:
    rig = DirectRig(tmp_path)

    async def run() -> None:
        resultado = await rig.call("send_message_direct")
        assert resultado["sent"] is True
        assert resultado["status"] == "sent"
        assert resultado["duplicate"] is False
        assert resultado["message_id"]
        assert resultado["sent_uid"] is not None

    asyncio.run(run())
    assert len(rig.smtp.sent) == 1


def test_no_hace_falta_ninguna_confirmacion_por_mensaje(tmp_path: Path) -> None:
    """La tool no pide confirmation_id ni vista previa: envía ya."""
    rig = DirectRig(tmp_path)

    async def run() -> None:
        await rig.call("send_message_direct")
        nombres = {tool.name for tool in await rig.mcp.list_tools()}
        # El flujo de dos pasos sigue ahí, pero el directo no lo necesita.
        assert "prepare_send" not in nombres
        assert "send_message_direct" in nombres

    asyncio.run(run())


def test_el_argumento_de_idempotencia_es_obligatorio(tmp_path: Path) -> None:
    rig = DirectRig(tmp_path)

    async def run() -> None:
        with pytest.raises(ToolError, match="idempotency_key"):
            await rig.mcp.call_tool("send_message_direct", rig._sin_clave())

    asyncio.run(run())
    assert rig.smtp.sent == []


def test_una_clave_vacia_se_rechaza(tmp_path: Path) -> None:
    rig = DirectRig(tmp_path)

    async def run() -> None:
        with pytest.raises(ToolError, match="idempotency_key"):
            await rig.mcp.call_tool("send_message_direct", rig._send(idempotency_key="   "))

    asyncio.run(run())
    assert rig.smtp.sent == []


def test_el_nombre_del_argumento_no_parece_como_secreto(tmp_path: Path) -> None:
    """`idempotency_key` acabaría en el patrón de redacción de Paperclip."""
    from tests.test_nombres_de_campos import SECRET_KEY_RE

    rig = DirectRig(tmp_path)

    async def run() -> None:
        by_name = {tool.name: tool for tool in await rig.mcp.list_tools()}
        esquema = by_name["send_message_direct"].input_schema
        assert "idempotency_key" in esquema["properties"]
        assert not SECRET_KEY_RE.match("idempotency_key")

    asyncio.run(run())


# --- la idempotencia ------------------------------------------------------------


def test_la_misma_clave_no_vuelve_a_enviar(tmp_path: Path) -> None:
    rig = DirectRig(tmp_path)

    async def run() -> None:
        primero = await rig.call("send_message_direct")
        segundo = await rig.call("send_message_direct")
        assert primero["sent"] is True
        assert segundo["sent"] is True
        assert segundo["duplicate"] is True
        assert segundo["message_id"] == primero["message_id"]

    asyncio.run(run())
    assert len(rig.smtp.sent) == 1


def test_la_misma_clave_con_otro_contenido_se_rechaza(tmp_path: Path) -> None:
    rig = DirectRig(tmp_path)

    async def run() -> None:
        await rig.call("send_message_direct")
        with pytest.raises(ToolError, match="otro contenido"):
            await rig.call("send_message_direct", subject="Otro asunto")

    asyncio.run(run())
    assert len(rig.smtp.sent) == 1


def test_una_clave_distinta_envia_de_nuevo(tmp_path: Path) -> None:
    rig = DirectRig(tmp_path)

    async def run() -> None:
        await rig.call("send_message_direct")
        await rig.call("send_message_direct", idempotency_key="trello-tarea-43")

    asyncio.run(run())
    assert len(rig.smtp.sent) == 2


def test_la_clave_sobrevive_a_un_reinicio(tmp_path: Path) -> None:
    """El registro está en la base: un reinicio no puede duplicar el envío."""
    rig = DirectRig(tmp_path)

    async def run() -> None:
        await rig.call("send_message_direct")

    asyncio.run(run())
    # Un "reinicio": otro store sobre la misma base.
    otro = DirectRig(tmp_path)
    otro.db = rig.db

    async def run2() -> None:
        segundo = await otro.call("send_message_direct")
        assert segundo["duplicate"] is True

    asyncio.run(run2())
    assert len(rig.smtp.sent) == 1


def test_un_fallo_del_smtp_libera_la_clave(tmp_path: Path) -> None:
    """Si el SMTP rechaza el envío, se puede reintentar con la misma clave."""
    rig = DirectRig(tmp_path)
    rig.smtp.fail_send = True

    async def run() -> None:
        with pytest.raises(ToolError, match="rechazó"):
            await rig.call("send_message_direct")
        # La clave se liberó: la segunda llamada intenta enviar otra vez.
        with pytest.raises(ToolError, match="rechazó"):
            await rig.call("send_message_direct")

    asyncio.run(run())


def test_un_sin_respuesta_deja_el_envio_incierto(tmp_path: Path) -> None:
    """Si el SMTP no responde, la clave queda reservada: no se reenvía.

    El correo pudo salir. Reintentar con la misma clave podría duplicarlo,
    así que el servidor se niega y obliga a comprobar Enviados.
    """
    rig = DirectRig(tmp_path)

    class SinRespuestaSMTP(FakeSMTP):
        def send_message(self, message, from_addr=None, to_addrs=None):  # type: ignore[no-untyped-def]
            raise TimeoutError("se cayó la conexión")

    rig.smtp = SinRespuestaSMTP()
    rig.writer.smtp_factory = lambda _a, _s: rig.smtp

    async def run() -> None:
        with pytest.raises(ToolError, match="no se sabe|incierto|no respondió"):
            await rig.call("send_message_direct")
        # La segunda llamada no vuelve a enviar: dice que está incierto.
        with pytest.raises(ToolError, match="incierto"):
            await rig.call("send_message_direct")

    asyncio.run(run())


def test_el_envio_directo_cuenta_en_el_tope_diario(tmp_path: Path) -> None:
    rig = DirectRig(tmp_path)
    rig.writer.quota = SendQuota(1)

    async def run() -> None:
        await rig.call("send_message_direct")
        with pytest.raises(ToolError, match="Tope diario"):
            await rig.call("send_message_direct", idempotency_key="otra-clave")

    asyncio.run(run())


# --- la auditoría ---------------------------------------------------------------


def test_la_auditoria_no_lleva_el_cuerpo_ni_la_clave(tmp_path: Path) -> None:
    rig = DirectRig(tmp_path)

    async def run() -> None:
        await rig.call("send_message_direct")

    asyncio.run(run())
    log = rig.audit.path.read_text(encoding="utf-8")
    assert "send_message_direct" in log
    assert "Contenido del correo" not in log
    assert "trello-tarea-42" not in log
