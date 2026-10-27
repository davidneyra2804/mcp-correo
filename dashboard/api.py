"""La API del panel: dominios, cuentas y pruebas de conexión.

Todo lo que cambia algo queda auditado en el mismo JSONL que las tools
del MCP, con su propio nombre de tool. La auditoría es el sitio donde ya
se mira qué ha pasado.

Las contraseñas nunca salen: al leer una cuenta se ve si tiene
contraseña, no cuál es. Y al editarla, la contraseña solo se cambia si se
manda una nueva.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import Account, ServerSettings
from mail.errors import MailError
from mail.imap import probar_imap
from mail.smtp_out import probar_smtp
from store.models import AccountRecord, DomainRecord, to_account
from store.store import Store, StoreError

logger = logging.getLogger("mcp_correo.panel")


async def _en_hilo(func: Callable[..., Any], *args: Any) -> Any:
    """Ejecuta un bloque que bloquea en el hilo, no en el bucle de eventos."""
    return await anyio.to_thread.run_sync(functools.partial(func, *args))


async def _cuerpo(request: Request) -> dict[str, Any]:
    """El cuerpo de la petición, como diccionario."""
    try:
        datos = await request.json()
    except Exception:
        return {}
    return datos if isinstance(datos, dict) else {}


def _error(exc: Exception) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


def _cuenta_publica(cuenta: AccountRecord) -> dict[str, Any]:
    """La cuenta, sin la contraseña."""
    return {
        "id": cuenta.id,
        "name": cuenta.name,
        "label": cuenta.label,
        "user": cuenta.username,
        "sender": cuenta.sender,
        "domain_id": cuenta.domain_id,
        "route": f"/mcp/{cuenta.name}",
        "imap_host": cuenta.imap_host,
        "imap_port": cuenta.imap_port,
        "imap_ssl": cuenta.imap_ssl,
        "smtp_host": cuenta.smtp_host,
        "smtp_port": cuenta.smtp_port,
        "smtp_security": cuenta.smtp_security,
        "drafts_folder": cuenta.drafts_folder,
        "sent_folder": cuenta.sent_folder,
        "trash_folder": cuenta.trash_folder,
        "allow_send": cuenta.allow_send,
        "allow_mark": cuenta.allow_mark,
        "allow_delete": cuenta.allow_delete,
        "allow_drafts": cuenta.allow_drafts,
        "has_credential": bool(cuenta.bearer),
        "enabled": cuenta.enabled,
        "password_set": bool(cuenta.password),
    }


def _dominio_publico(dominio: DomainRecord, cuentas: list[AccountRecord]) -> dict[str, Any]:
    return {
        "id": dominio.id,
        "name": dominio.name,
        "label": dominio.label,
        "default": dominio.is_default,
        "has_credential": bool(dominio.bearer),
        "imap_host": dominio.imap_host,
        "imap_port": dominio.imap_port,
        "imap_ssl": dominio.imap_ssl,
        "smtp_host": dominio.smtp_host,
        "smtp_port": dominio.smtp_port,
        "smtp_security": dominio.smtp_security,
        "allow_send": dominio.allow_send,
        "allow_mark": dominio.allow_mark,
        "allow_delete": dominio.allow_delete,
        "allow_drafts": dominio.allow_drafts,
        "accounts": [_cuenta_publica(cuenta) for cuenta in cuentas],
    }


def _auditar(request: Request, tool: str, cuenta: str, args: dict[str, Any]) -> None:
    audit = getattr(request.app.state, "audit", None)
    if audit is None:
        return
    try:
        audit.record(tool, cuenta, args)
    except Exception:  # pragma: no cover - la auditoría no puede tumbar el panel
        logger.warning("No se pudo auditar la operación del panel %s", tool)


# --- lectura -------------------------------------------------------------------


async def listar_dominios(request: Request) -> JSONResponse:
    store: Store = request.app.state.store

    def _leer() -> dict[str, Any]:
        dominios = store.dominios()
        cuentas = store.cuentas()
        por_dominio: dict[int, list[AccountRecord]] = {}
        for cuenta in cuentas:
            por_dominio.setdefault(cuenta.domain_id, []).append(cuenta)
        return {
            "ok": True,
            "domains": [
                _dominio_publico(dominio, por_dominio.get(dominio.id, [])) for dominio in dominios
            ],
        }

    return JSONResponse(await _en_hilo(_leer))


# --- dominios ------------------------------------------------------------------


async def crear_dominio(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    datos = await _cuerpo(request)

    def _crear() -> int:
        return store.crear_dominio(datos)

    try:
        identificador = await _en_hilo(_crear)
    except StoreError as exc:
        return _error(exc)
    _auditar(request, "dashboard_add_domain", str(datos.get("name", "")), {})
    return JSONResponse({"ok": True, "id": identificador})


async def cambiar_dominio(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    identificador = int(request.path_params["id"])
    datos = await _cuerpo(request)

    def _cambiar() -> None:
        store.cambiar_dominio(identificador, datos)

    try:
        await _en_hilo(_cambiar)
    except StoreError as exc:
        return _error(exc)
    _auditar(request, "dashboard_update_domain", str(identificador), {})
    return JSONResponse({"ok": True})


async def borrar_dominio(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    identificador = int(request.path_params["id"])

    def _borrar() -> None:
        store.borrar_dominio(identificador)

    try:
        await _en_hilo(_borrar)
    except StoreError as exc:
        return _error(exc)
    _auditar(request, "dashboard_delete_domain", str(identificador), {})
    return JSONResponse({"ok": True})


async def marcar_por_defecto(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    identificador = int(request.path_params["id"])

    def _marcar() -> None:
        store.marcar_por_defecto(identificador)

    try:
        await _en_hilo(_marcar)
    except StoreError as exc:
        return _error(exc)
    _auditar(request, "dashboard_default_domain", str(identificador), {})
    return JSONResponse({"ok": True})


async def token_dominio(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    identificador = int(request.path_params["id"])

    def _rotar() -> str:
        return store.rotar_token("dominio", identificador)

    try:
        token = await _en_hilo(_rotar)
    except StoreError as exc:
        return _error(exc)
    _auditar(request, "dashboard_rotate_domain_token", str(identificador), {})
    return JSONResponse({"ok": True, "token": token})


# --- cuentas -------------------------------------------------------------------


async def crear_cuenta(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    datos = await _cuerpo(request)

    def _crear() -> tuple[int, str]:
        return store.crear_cuenta(datos)

    try:
        identificador, token = await _en_hilo(_crear)
    except StoreError as exc:
        return _error(exc)
    _auditar(request, "dashboard_add_account", str(datos.get("name", "")), {})
    # El token se devuelve aquí y no se vuelve a mostrar: la API solo dice
    # que la cuenta tiene credencial propia.
    return JSONResponse({"ok": True, "id": identificador, "token": token})


async def cambiar_cuenta(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    identificador = int(request.path_params["id"])
    datos = await _cuerpo(request)

    def _cambiar() -> None:
        store.cambiar_cuenta(identificador, datos)

    try:
        await _en_hilo(_cambiar)
    except StoreError as exc:
        return _error(exc)
    _auditar(request, "dashboard_update_account", str(identificador), {})
    return JSONResponse({"ok": True})


async def borrar_cuenta(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    identificador = int(request.path_params["id"])

    def _borrar() -> None:
        store.borrar_cuenta(identificador)

    try:
        await _en_hilo(_borrar)
    except StoreError as exc:
        return _error(exc)
    _auditar(request, "dashboard_delete_account", str(identificador), {})
    return JSONResponse({"ok": True})


async def token_cuenta(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    identificador = int(request.path_params["id"])

    def _rotar() -> str:
        return store.rotar_token("cuenta", identificador)

    try:
        token = await _en_hilo(_rotar)
    except StoreError as exc:
        return _error(exc)
    _auditar(request, "dashboard_rotate_account_token", str(identificador), {})
    return JSONResponse({"ok": True, "token": token})


# --- pruebas de conexión -------------------------------------------------------


def _cuenta_de_prueba(store: Store, settings: ServerSettings, datos: dict[str, Any]) -> Account:
    """La cuenta que se va a probar, con los defaults del dominio puestos."""
    dominio: DomainRecord | None = None
    dominio_id = datos.get("domain_id")
    if dominio_id not in (None, ""):
        try:
            dominio = store.dominio(int(dominio_id))
        except (TypeError, ValueError):
            dominio = None
    if dominio is None:
        dominio = DomainRecord(id=0, name="")
    registro = AccountRecord(
        id=0,
        domain_id=dominio.id,
        name=str(datos.get("name") or "prueba"),
        label="",
        sender="",
        username=str(datos.get("username") or ""),
        password=b"",
        imap_host=str(datos.get("imap_host") or ""),
        imap_port=datos.get("imap_port"),
        imap_ssl=datos.get("imap_ssl"),
        smtp_host=str(datos.get("smtp_host") or ""),
        smtp_port=datos.get("smtp_port"),
        smtp_security=str(datos.get("smtp_security") or ""),
        drafts_folder=str(datos.get("drafts_folder") or ""),
        sent_folder=str(datos.get("sent_folder") or ""),
        trash_folder=str(datos.get("trash_folder") or ""),
    )
    return to_account(registro, dominio, str(datos.get("password") or ""), settings)


async def probar_conexion_imap(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    settings: ServerSettings = request.app.state.settings
    datos = await _cuerpo(request)
    if not datos.get("username"):
        return JSONResponse({"ok": False, "error": "Falta el usuario."}, status_code=400)

    def _probar() -> dict[str, Any]:
        cuenta = _cuenta_de_prueba(store, settings, datos)
        return probar_imap(cuenta, settings, getattr(request.app.state, "imap_factory", None))

    try:
        resultado = await _en_hilo(_probar)
    except MailError as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    _auditar(request, "dashboard_test_imap", str(datos.get("name", "")), {})
    return JSONResponse(resultado)


async def probar_conexion_smtp(request: Request) -> JSONResponse:
    store: Store = request.app.state.store
    settings: ServerSettings = request.app.state.settings
    datos = await _cuerpo(request)
    if not datos.get("username"):
        return JSONResponse({"ok": False, "error": "Falta el usuario."}, status_code=400)

    def _probar() -> dict[str, Any]:
        cuenta = _cuenta_de_prueba(store, settings, datos)
        return probar_smtp(cuenta, settings, getattr(request.app.state, "smtp_factory", None))

    try:
        resultado = await _en_hilo(_probar)
    except MailError as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    _auditar(request, "dashboard_test_smtp", str(datos.get("name", "")), {})
    return JSONResponse(resultado)
