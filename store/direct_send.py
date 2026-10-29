"""Idempotencia del envío directo.

El envío directo no pasa por la preparación con ``confirmation_id``: el
agente entrega el mensaje entero y el servidor lo envía en la misma
llamada. Eso obliga a resolver una pregunta que el flujo de dos pasos no
tenía: **qué pasa si la misma llamada se repite**.

La respuesta es una clave de idempotencia. El agente la elige y la reutiliza
para la misma operación. La primera llamada reserva la clave y envía; las
siguientes devuelven el resultado guardado, sin volver a enviar. Si la
clave se reutiliza con otro contenido, la llamada se rechaza.

La tabla vive en SQLite porque el reinicio del servidor no puede olvidar
una clave: si se olvidara, un reintento tras el reinicio volvería a
enviar el correo.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

#: Estados de una clave reservada.
#:
#: ``pending``: reservada, el envío está en curso.
#: ``sent``: el SMTP aceptó el mensaje y el resultado está guardado.
#: ``failed``: falló antes de completarse; la clave se libera para reintentar.
#: ``uncertain``: el SMTP pudo aceptarlo y se perdió la respuesta. La clave
#: no se libera: reenviar con ella podría duplicar el correo.
PENDING = "pending"
SENT = "sent"
FAILED = "failed"
UNCERTAIN = "uncertain"

#: Longitud máxima de la clave que elige el agente.
MAX_KEY_LENGTH = 200

_RESERVED = (PENDING, SENT, FAILED, UNCERTAIN)


class DirectSendError(Exception):
    """La operación no se puede hacer. El mensaje dice qué corregir."""


@dataclass(frozen=True)
class DirectSendRecord:
    """Lo que se guarda de una clave de idempotencia."""

    account: str
    fingerprint: str
    status: str
    result: dict[str, Any]
    message_id: str = ""


def fingerprint(
    *,
    to: list[str],
    cc: list[str] | None,
    bcc: list[str] | None,
    subject: str,
    body: str,
    in_reply_to: str | None,
    references: str | None,
    attachments: list[dict[str, str]] | None,
) -> str:
    """La huella del contenido del mensaje.

    No guarda el mensaje: guarda su huella. Dos llamadas con la misma
    clave tienen que ser **exactamente** el mismo mensaje; si cambia una
    letra, cambia la huella y la segunda llamada se rechaza.
    """
    datos = {
        "to": list(to),
        "cc": list(cc or []),
        "bcc": list(bcc or []),
        "subject": subject,
        "body": body,
        "in_reply_to": in_reply_to or "",
        "references": references or "",
        "attachments": [
            {
                "filename": str(item.get("filename") or ""),
                "content_type": str(item.get("content_type") or "").strip().lower(),
                "content_base64": str(item.get("content_base64") or ""),
            }
            for item in (attachments or [])
            if isinstance(item, dict)
        ],
    }
    bruto = json.dumps(datos, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def normalizar_clave(clave: object) -> str:
    """La clave de idempotencia, recortada y con la forma exigida.

    No es una credencial: solo identifica una operación dentro de una
    cuenta. Aun así no puede traer saltos de línea, porque acaba en
    cabeceras de un log y en una tabla.
    """
    if not isinstance(clave, str):
        raise DirectSendError("idempotency_key debe ser texto.")
    texto = clave.strip()
    if not texto:
        raise DirectSendError(
            "Falta idempotency_key. Usa una clave estable por envío: "
            "por ejemplo, el identificador del pendiente de origen."
        )
    if any(char in texto for char in "\r\n\x00"):
        raise DirectSendError("idempotency_key contiene caracteres no permitidos.")
    if len(texto) > MAX_KEY_LENGTH:
        raise DirectSendError(
            f"idempotency_key es demasiado larga (máximo {MAX_KEY_LENGTH} caracteres)."
        )
    return texto


class DirectSendStore:
    """Las claves de idempotencia del envío directo, en SQLite."""

    def __init__(self, database: Any) -> None:
        self.db = database
        self._lock = threading.Lock()

    def reservar(self, account: str, key: str, huella: str) -> DirectSendRecord | None:
        """Reserva la clave para este contenido.

        Devuelve ``None`` si la reserva es nueva y hay que enviar. Si la
        clave ya existía, devuelve lo que había: el registro anterior, para
        devolver su resultado sin volver a enviar.

        La reserva es atómica: dos llamadas simultáneas con la misma clave
        no pueden salir las dos como nuevas. La clave es única en toda la
        base, así que el INSERT que gane es el único que envía.
        """
        with self._lock:
            con = self.db.connect()
            try:
                con.execute(
                    "INSERT INTO direct_sends(key, account, fingerprint, status, result, "
                    "created_at) VALUES(?,?,?,?,?,datetime('now'))",
                    (key, account, huella, PENDING, "{}"),
                )
            except sqlite3.IntegrityError:
                fila = con.execute(
                    "SELECT account, fingerprint, status, result, message_id "
                    "FROM direct_sends WHERE key = ?",
                    (key,),
                ).fetchone()
                if fila is None:  # pragma: no cover - no puede pasar
                    raise
                return _record(fila)
            return None

    def comprobar(self, record: DirectSendRecord, account: str, huella: str) -> None:
        """Comprueba que el registro anterior es de esta cuenta y este mensaje."""
        if record.account != account:
            raise DirectSendError(
                "idempotency_key ya usada en otra cuenta. Usa una clave distinta por cuenta."
            )
        if record.fingerprint != huella:
            raise DirectSendError(
                "idempotency_key ya usada con otro contenido. "
                "Usa una clave distinta para cada envío."
            )

    def guardar(
        self,
        key: str,
        account: str,
        huella: str,
        status: str,
        result: dict[str, Any],
        message_id: str = "",
    ) -> None:
        """Guarda el resultado de un envío ya intentado."""
        if status not in _RESERVED:
            raise DirectSendError(f"Estado de envío desconocido: {status}.")
        with self._lock:
            con = self.db.connect()
            con.execute(
                "UPDATE direct_sends SET status = ?, result = ?, message_id = ? WHERE key = ?",
                (status, json.dumps(result, ensure_ascii=False), message_id, key),
            )

    def marcar_incierto(self, key: str, account: str, huella: str) -> None:
        """Deja la clave en estado incierto: no se puede reenviar con ella.

        Se usa cuando el SMTP pudo aceptar el mensaje y se perdió la
        respuesta. Reintentar con la misma clave podría duplicar el
        correo, así que el servidor se niega a hacerlo y obliga a
        comprobar la carpeta de Enviados.
        """
        with self._lock:
            con = self.db.connect()
            con.execute(
                "UPDATE direct_sends SET status = ? WHERE key = ? AND status = ?",
                (UNCERTAIN, key, PENDING),
            )

    def borrar_si_pending(self, key: str) -> None:
        """Libera una clave que no llegó a intentar el envío.

        Solo se usa cuando el fallo es anterior al contacto con el SMTP:
        si el servidor pudo haber aceptado el correo, la clave se queda
        como incierta y no se puede reutilizar.
        """
        with self._lock:
            con = self.db.connect()
            con.execute("DELETE FROM direct_sends WHERE key = ? AND status = ?", (key, PENDING))


def _record(fila: sqlite3.Row) -> DirectSendRecord:
    try:
        resultado = json.loads(str(fila["result"] or "{}"))
    except (TypeError, ValueError):  # pragma: no cover - datos corruptos
        resultado = {}
    if not isinstance(resultado, dict):
        resultado = {}
    return DirectSendRecord(
        account=str(fila["account"]),
        fingerprint=str(fila["fingerprint"]),
        status=str(fila["status"]),
        result=resultado,
        message_id=str(fila["message_id"] or ""),
    )
