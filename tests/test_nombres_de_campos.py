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
