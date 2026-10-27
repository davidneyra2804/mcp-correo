"""El nombre visible del remitente.

Va en la cabecera From, así que además de ser bonito tiene que estar bien
escapado y no poder inyectar cabeceras.
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

import pytest

from mail.compose import format_sender, without_bcc


def test_el_from_lleva_el_nombre_visible() -> None:
    assert format_sender("Ada Lovelace", "ada@corp.example.com") == (
        "Ada Lovelace <ada@corp.example.com>"
    )


def test_sin_nombre_el_from_es_solo_la_direccion() -> None:
    assert format_sender("", "ada@corp.example.com") == "ada@corp.example.com"


@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [
        ("Neyra, David", '"Neyra, David" <ada@corp.example.com>'),
        ('El "Jefe"', '"El \\"Jefe\\"" <ada@corp.example.com>'),
    ],
)
def test_un_nombre_con_caracteres_especiales_se_entrecomilla(nombre: str, esperado: str) -> None:
    """Si no se escapa, la coma parte la dirección en dos."""
    assert format_sender(nombre, "ada@corp.example.com") == esperado
    # Y lo que se parsesa sigue siendo la dirección correcta.
    assert parseaddr(format_sender(nombre, "ada@corp.example.com"))[1] == ("ada@corp.example.com")


def test_un_salto_de_linea_no_se_cuela() -> None:
    """Un nombre con CRLF podría inyectar un Bcc de verdad."""
    from config import _display_name

    with pytest.raises(SystemExit, match="saltos de línea"):
        _display_name("Jefe\r\nBcc: victima@example.com", "sender")


def test_un_nombre_con_nulo_no_se_cuela() -> None:
    from config import _display_name

    with pytest.raises(SystemExit, match="saltos de línea"):
        _display_name("Jefe\x00", "sender")


def test_un_nombre_muy_largo_no_se_cuela() -> None:
    from config import _display_name

    with pytest.raises(SystemExit, match="demasiado largo"):
        _display_name("a" * 101, "sender")


def test_la_cuenta_toma_el_sender_de_la_base() -> None:
    """El nombre visible llega con la cuenta, desde el panel."""
    from config import Account

    cuenta = Account(
        key="ada@corp.example.com",
        label="Ada",
        imap_host="imap.corp.example.com",
        imap_port=993,
        username="ada@corp.example.com",
        password="clave",
        sender="Ada Lovelace",
    )
    assert cuenta.sender == "Ada Lovelace"


def test_el_from_del_mensaje_lleva_el_nombre() -> None:
    """El mensaje que sale por SMTP, con nombre visible."""
    from config import ServerSettings
    from mail.compose import build_outgoing

    settings = ServerSettings(
        public_host="mcp.example.com",
        bind_host="127.0.0.1",
        bind_port=8765,
        max_results=100,
        max_chars=20000,
        max_attachment_bytes=5_000_000,
        max_message_bytes=15_000_000,
        imap_timeout=20,
        sent_scan_limit=300,
        allowed_hosts=("mcp.example.com",),
        allowed_origins=("https://mcp.example.com",),
        allowed_attachment_types=("text/plain",),
        audit_log="audit.jsonl",
    )
    raw, _public, _preview = build_outgoing(
        sender="ada@corp.example.com",
        sender_name="Ada Lovelace",
        to=["ana@example.com"],
        cc=None,
        bcc=None,
        subject="Hola",
        body="Cuerpo",
        in_reply_to=None,
        references=None,
        attachments=None,
        settings=settings,
    )
    mensaje = EmailMessage()
    mensaje["From"] = "x"
    from email import message_from_bytes
    from email.policy import default as default_policy

    parsed = message_from_bytes(raw, policy=default_policy)
    assert parsed["From"] == "Ada Lovelace <ada@corp.example.com>"
    # El sobre SMTP sigue llevando la dirección pelada: es lo que usa
    # smtplib.send_message con getaddresses.
    assert getaddresses([parsed["From"]])[0][1] == "ada@corp.example.com"


def test_la_copia_de_enviados_tiene_el_nombre() -> None:
    """La copia en Enviados también lleva el nombre visible."""
    raw = b"From: Ada Lovelace <ada@corp.example.com>\r\nTo: ana@example.com\r\n\r\nhola\r\n"
    assert b"Ada Lovelace" in without_bcc(raw)
