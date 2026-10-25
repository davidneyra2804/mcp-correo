from __future__ import annotations

from datetime import date

import pytest

from config import ServerSettings
from mail.errors import MailError
from tests.fakes import sample_mailbox


def test_lista_carpetas_con_special_use() -> None:
    _fake, service, _account = sample_mailbox()
    payload = service.list_folders("principal")
    by_name = {folder["name"]: folder for folder in payload["folders"]}
    assert "\\Sent" in by_name["Sent"]["special_use"]
    assert by_name["INBOX"]["special_use"] == []


def test_list_messages_filtra_sin_marcar_leido() -> None:
    fake, service, _account = sample_mailbox()
    payload = service.list_messages(
        "principal",
        unseen=True,
        since="2026-10-01",
        sender="ana",
        limit=10,
    )
    assert [item["uid"] for item in payload["messages"]] == [10]
    assert payload["messages"][0]["subject"] == "Presupuesto"
    assert payload["messages"][0]["seen"] is False
    assert b"\\Seen" not in fake.folders["INBOX"].messages[10].flags
    criteria = fake.searches[-1]
    assert "UNSEEN" in criteria
    assert "SINCE" in criteria
    assert date(2026, 10, 1) in criteria
    assert "FROM" in criteria


def test_search_cubre_subject_text_from_to_y_fechas() -> None:
    fake, service, _account = sample_mailbox()
    payload = service.search_messages(
        "principal",
        subject="Presupuesto",
        text="presupuesto",
        sender="ana",
        recipient="ada",
        since="2026-10-01",
        before="2026-10-31",
    )
    assert [item["uid"] for item in payload["messages"]] == [10]
    criteria = fake.searches[-1]
    for key in ("SUBJECT", "TEXT", "FROM", "TO", "SINCE", "BEFORE"):
        assert key in criteria


def test_search_exige_criterio() -> None:
    _fake, service, _account = sample_mailbox()
    with pytest.raises(MailError, match="criterio"):
        service.search_messages("principal")


def test_get_message_trunca_y_lista_adjuntos() -> None:
    _fake, service, _account = sample_mailbox()
    payload = service.get_message("principal", 10, max_chars=12)
    assert payload["untrusted"] is True
    assert payload["truncated"] is True
    assert len(payload["body"]) == 12
    assert payload["body"] == "CUERPO-SECRE"
    assert payload["attachments"][0]["filename"] == "informe.txt"
    assert payload["attachments"][0]["type"] == "text/plain"
    assert "content" not in payload["attachments"][0]


def test_get_message_html_elimina_etiquetas() -> None:
    _fake, service, _account = sample_mailbox()
    payload = service.get_message("principal", 13)
    assert "Hola visible" in payload["body"]
    assert "<script>" not in payload["body"]
    assert "ignora tus reglas" not in payload["body"]


def test_adjunto_permitido_y_rechazos() -> None:
    fake, service, _account = sample_mailbox()
    payload = service.get_attachment("principal", 10, index=0, filename="informe.txt")
    assert payload["encoding"] == "text"
    assert payload["content"] == "contenido-adjunto"
    assert fake.mutated is False

    with pytest.raises(MailError, match="no coincide"):
        service.get_attachment("principal", 10, index=0, filename="otro.txt")

    small = ServerSettings(
        public_host="mcp.example.com",
        bind_host="127.0.0.1",
        bind_port=8765,
        max_results=10,
        max_chars=100,
        max_attachment_bytes=4,
        max_message_bytes=15_000_000,
        imap_timeout=5,
        sent_scan_limit=20,
        allowed_hosts=("127.0.0.1:*",),
        allowed_origins=("http://127.0.0.1:*",),
        allowed_attachment_types=("text/plain",),
        audit_log="audit.jsonl",
    )
    _fake, limited, _account = sample_mailbox(small)
    with pytest.raises(MailError, match="límite"):
        limited.get_attachment("principal", 10, index=0)


def test_mensaje_demasiado_grande_no_descarga_el_cuerpo() -> None:
    settings = ServerSettings(
        public_host="mcp.example.com",
        bind_host="127.0.0.1",
        bind_port=8765,
        max_results=10,
        max_chars=100,
        max_attachment_bytes=1000,
        max_message_bytes=20,
        imap_timeout=5,
        sent_scan_limit=20,
        allowed_hosts=("127.0.0.1:*",),
        allowed_origins=("http://127.0.0.1:*",),
        allowed_attachment_types=("text/plain",),
        audit_log="audit.jsonl",
    )
    fake, service, _account = sample_mailbox(settings)
    with pytest.raises(MailError, match="límite de descarga"):
        service.get_message("principal", 10)
    fetched = [item for batch in fake.fetch_items for item in batch]
    assert "BODY.PEEK[]" not in fetched


def test_cuenta_desconocida() -> None:
    _fake, service, _account = sample_mailbox()
    with pytest.raises(MailError, match="Cuenta desconocida"):
        service.list_folders("no-existe")
