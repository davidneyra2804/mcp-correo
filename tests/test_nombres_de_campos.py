"""Los nombres de campo que ve el agente no pueden parecer secretos.

Por qué: hay plataformas que tapan por nombre los campos de una respuesta de
tool antes de dársela al modelo. Paperclip lo hace con una lista de nombres
que "parecen credenciales", y el valor tapado es lo que recibe el agente:
`validateToolContent` devuelve `redactEventPayload(value)`, y el llamante
devuelve ese valor redactado, no el original.

Con un campo llamado `confirm_token`, el agente recibía `***REDACTED***` en
lugar del valor, no podía completar el envío y no había forma de saber por
qué. El nombre de un campo, no su valor, decide si se tapa.

Este módulo fija la regla: ningún nombre de campo de la superficie MCP puede
caer en un patrón de secreto. Si algún día hay que añadir un campo nuevo,
este test dice por qué no puede llamarse `*token*`, `*secret*` o `*key*`.

Los patrones son los de Paperclip (`server/src/redaction.ts`):
`[A-Za-z0-9_-]*(api[-_]?key|access[-_]?token|auth(?:_?token)?|token|
authorization(?:[-_]?code)?|bearer|secrets?|passwd|passwords?|credentials?|jwt|
private[-_]?key|cookie|connectionstring|browser[-_]?code|login[-_]?url)...`
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from tests.test_writes import Rig

#: El patrón de Paperclip, verbatim. Si ellos lo cambian, esto se queda
#: viejo, pero sigue siendo la mejor aproximación disponible.
SECRET_NAME_PATTERN = (
    r"[A-Za-z0-9_-]*(?:api[-_]?key|access[-_]?token|auth(?:_?token)?|token"
    r"|authorization(?:[-_]?code)?|bearer|secrets?|passwd|passwords?"
    r"|credentials?|jwt|private[-_]?key|cookie|connectionstring"
    r"|browser[-_]?code|login[-_]?url)"
    r"(?:[-_]?(?:value|header|prod(?:uction)?|dev(?:elopment)?|test|staging"
    r"|primary|secondary))*"
)
SECRET_KEY_RE = re.compile(rf"^(?:{SECRET_NAME_PATTERN})(?:_plain|_ref)?$", re.IGNORECASE)

#: La versión de texto, que es la que se aplica a un bloque de texto con
#: JSON dentro. Es la que más falta hizo: la respuesta del MCP es un bloque
#: de texto, no un objeto con campos.
JSON_SECRET_FIELD_TEXT_RE = re.compile(
    rf"((?:\"|')?{SECRET_NAME_PATTERN}(?:\"|')?\s*:\s*(?:\"|'))[^\"'\r\n]+((?:\"|'))",
    re.IGNORECASE,
)

#: Un valor con esta forma tampoco debe aparecer: son las formas que las
#: plataformas reconocen como credenciales de un proveedor concreto.
SECRET_VALUE_RES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
)


def _nombres_de_una_tool(tool: object) -> set[str]:
    """Los nombres de argumento de una tool.

    El SDK expone el esquema como `input_schema` (y en el cable, como
    `inputSchema`). Se leen los dos, y si no hay ninguno se falla: con el
    nombre equivocado, el esquema salía vacío y el test pasaba sin mirar
    nada. Una tool sin argumentos es legítima: esa devuelve una lista vacía.
    """
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
    assert isinstance(schema, dict), (
        f"La tool {getattr(tool, 'name', '?')} no expone el esquema de "
        "argumentos: el test vigilaría una lista vacía y no detectaría nada."
    )
    properties = schema.get("properties") or {}
    assert isinstance(properties, dict)
    return set(properties)


def test_los_argumentos_de_las_tools_no_parecen_secretos(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    async def run() -> None:
        vistos: set[str] = set()
        for tool in await rig.mcp.list_tools():
            for name in _nombres_de_una_tool(tool):
                vistos.add(name)
                assert not SECRET_KEY_RE.match(name), (
                    f"El argumento {name!r} de {tool.name} tiene un nombre que "
                    "las plataformas tapan. Renómbralo: el agente no recibirá "
                    "el valor y no podrá completar la operación."
                )
        # Si esto no se cumple, el test no miró ningún nombre.
        assert len(vistos) >= 5, f"Solo se vigilaron {vistos}"

    asyncio.run(run())


def test_las_claves_de_la_respuesta_no_parecen_secretos(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    async def run() -> None:
        prepared = await rig.mcp.call_tool(
            "prepare_send",
            {
                "account": "principal",
                "to": ["ana@example.com"],
                "subject": "Hola",
                "body": "Cuerpo",
            },
        )
        preview = json.loads(prepared.content[0].text)  # type: ignore[attr-defined]
        for name in preview:
            assert not SECRET_KEY_RE.match(name), (
                f"La clave {name!r} de la respuesta de prepare_send tiene un "
                "nombre que las plataformas tapan: el agente recibiría el valor "
                "sustituido y no podría completar el envío."
            )

    asyncio.run(run())


def test_las_claves_de_las_respuestas_de_escritura_no_parecen_secretos(tmp_path: Path) -> None:
    """Lo mismo para la respuesta del envío y la del borrador.

    Una plataforma que tape la respuesta del envío hide justo lo que hace
    falta para comprobarlo: dónde quedó la copia y con qué identificador.
    """
    rig = Rig(tmp_path, draft=True, drafts=True)

    async def run() -> None:
        prepared = await rig.mcp.call_tool(
            "prepare_send",
            {
                "account": "principal",
                "to": ["ana@example.com"],
                "subject": "Hola",
                "body": "Cuerpo",
            },
        )
        preview = json.loads(prepared.content[0].text)  # type: ignore[attr-defined]
        sent = await rig.mcp.call_tool(
            "send_message",
            {"account": "principal", "confirmation_id": preview["confirmation_id"]},
        )
        resultado = json.loads(sent.content[0].text)  # type: ignore[attr-defined]
        for name in resultado:
            assert not SECRET_KEY_RE.match(name), (
                f"La clave {name!r} de la respuesta de send_message tiene un "
                "nombre que las plataformas tapan."
            )

        draft = await rig.mcp.call_tool(
            "create_draft",
            {
                "account": "principal",
                "to": ["ana@example.com"],
                "subject": "Borrador",
                "body": "Cuerpo",
            },
        )
        borrador = json.loads(draft.content[0].text)  # type: ignore[attr-defined]
        for name in borrador:
            assert not SECRET_KEY_RE.match(name), (
                f"La clave {name!r} de la respuesta de create_draft tiene un "
                "nombre que las plataformas tapan."
            )

    asyncio.run(run())


def test_un_cliente_con_el_catalogo_viejo_recibe_un_error_que_se_puede_seguir(
    tmp_path: Path,
) -> None:
    """Un cliente con el esquema viejo recibe un error accionable.

    Pasó en producción: la conexión tenía el catálogo cacheado con el
    nombre anterior del argumento, y la llamada se rechazó por validación
    local. Lo que importa es que el error dijera qué campo faltaba, para que
    el agente lo corrigiera solo en la siguiente llamada. Y que no fuera el
    error del valor tapado, que no dice qué hacer.
    """
    rig = Rig(tmp_path)

    async def run() -> None:
        prepared = await rig.mcp.call_tool(
            "prepare_send",
            {
                "account": "principal",
                "to": ["ana@example.com"],
                "subject": "Hola",
                "body": "Cuerpo",
            },
        )
        preview = json.loads(prepared.content[0].text)  # type: ignore[attr-defined]

        with pytest.raises(ToolError) as excinfo:
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirm_token": preview["confirmation_id"]},
            )
        error = str(excinfo.value)
        assert "confirmation_id" in error, error
        assert "Field required" in error, error
        # Y no es el error del valor tapado: ese deja al agente sin salida.
        assert "desconocido" not in error, error
        assert "oculto" not in error, error

        # Con el campo correcto, el mismo identificador funciona.
        sent = await rig.mcp.call_tool(
            "send_message",
            {"account": "principal", "confirmation_id": preview["confirmation_id"]},
        )
        resultado = json.loads(sent.content[0].text)  # type: ignore[attr-defined]
        assert resultado["sent"] is True

    asyncio.run(run())


def test_el_valor_del_confirmation_id_no_parece_como_credencial(tmp_path: Path) -> None:
    """El valor tampoco puede tener la forma de una credencial conocida.

    Si el valor pareciera una clave de un proveedor, una plataforma lo taparía
    aunque el nombre del campo no fuera sospechoso.
    """
    rig = Rig(tmp_path)

    async def run() -> None:
        prepared = await rig.mcp.call_tool(
            "prepare_send",
            {
                "account": "principal",
                "to": ["ana@example.com"],
                "subject": "Hola",
                "body": "Cuerpo",
            },
        )
        preview = json.loads(prepared.content[0].text)  # type: ignore[attr-defined]
        value = preview["confirmation_id"]
        for pattern in SECRET_VALUE_RES:
            assert not pattern.search(value), (
                "El confirmation_id tiene la forma de una credencial conocida "
                "y una plataforma podría taparlo."
            )

    asyncio.run(run())


def test_el_confirmation_id_sobrevive_a_la_redaccion_de_la_plataforma(tmp_path: Path) -> None:
    """El valor tiene que llegar al agente entero, después de tapar.

    Esto es lo que pasó en producción: la respuesta de la preparación
    volvió con el valor sustituido y el agente no pudo completar el envío.
    Aquí se aplica a la respuesta real la misma regex que aplica Paperclip,
    y se mira que el confirmation_id siga ahí.
    """
    rig = Rig(tmp_path)

    async def run() -> None:
        prepared = await rig.mcp.call_tool(
            "prepare_send",
            {
                "account": "principal",
                "to": ["ana@example.com"],
                "subject": "Hola",
                "body": "Cuerpo",
            },
        )
        texto = prepared.content[0].text  # type: ignore[attr-defined]
        valor = json.loads(texto)["confirmation_id"]

        # Lo que hace la plataforma: tapar por nombre y por forma de JSON.
        tapado = JSON_SECRET_FIELD_TEXT_RE.sub(r"\1***REDACTED***\2", texto)
        recibido = json.loads(tapado)["confirmation_id"]

        assert recibido == valor, (
            "La plataforma tapó el confirmation_id. El agente recibiría un "
            "valor que no sirve y no podría completar el envío."
        )
        assert "***REDACTED***" not in tapado, tapado

    asyncio.run(run())


def test_un_confirmation_id_tapado_dice_que_llego_oculto(tmp_path: Path) -> None:
    """Si llega un valor tapado, el error lo dice.

    Sin esto, el agente solo ve "desconocido o ya usado" y no sabe que
    tiene que volver a preparar. Es el fallo que se Late mucho tiempo sin
    diagnóstico.
    """
    rig = Rig(tmp_path)

    async def run() -> None:
        with pytest.raises(ToolError, match="oculto"):
            await rig.mcp.call_tool(
                "send_message",
                {"account": "principal", "confirmation_id": "***REDACTED***"},
            )

    asyncio.run(run())


def test_el_nombre_de_la_clave_de_idempotencia_no_parece_como_secreto(tmp_path: Path) -> None:
    """`idempotency_key` tiene que sobrevivir a la redacción de la plataforma.

    El nombre importa, no el valor: una plataforma que tapa por nombre
    dejaría al agente sin la clave y el reintento duplicaría el correo.
    """
    from tests.test_direct_send import DirectRig

    rig = DirectRig(tmp_path)

    async def run() -> None:
        by_name = {tool.name: tool for tool in await rig.mcp.list_tools()}
        esquema = by_name["send_message_direct"].input_schema
        assert "idempotency_key" in esquema["properties"]
        assert not SECRET_KEY_RE.match("idempotency_key"), (
            "El nombre idempotency_key cae en el patrón de secreto: la "
            "plataforma taparía la clave y el agente no podría reintentar."
        )

    asyncio.run(run())
