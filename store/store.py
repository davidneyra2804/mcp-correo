"""Las operaciones sobre la base: dominios y cuentas.

Es lo que usa el panel. Cada escritura sube el contador de revisiones, que
es lo que lee el servidor para recargar las cuentas sin reiniciar.

Los mensajes de error son accionables: dicen qué corregir, no solo qué
falló.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime

from config import ServerSettings
from store.crypto import Cipher, CipherError
from store.db import META_KEY_CHECK, Database
from store.models import AccountRecord, DomainRecord

#: Lo que se guarda en la fila de comprobación de la clave. Si se descifra
#: con la clave del operador, la clave es la correcta.
KEY_CHECK_PLAINTEXT = "mcp-correo-clave-ok"

#: Un nombre de cuenta va en una ruta: /mcp/<nombre>. Solo letras, números
#: y los signos que se usan en un correo. Nada de espacios ni de barras.
NAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,120}$")
#: Un nombre de dominio: etiquetas separadas por puntos.
DOMAIN_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$"
)
#: Longitud mínima de un token propio.
MIN_TOKEN_LENGTH = 16


class StoreError(Exception):
    """La operación no se puede hacer. El mensaje dice qué corregir."""


def ahora() -> str:
    """La hora, en el formato que se guarda."""
    return datetime.now(UTC).isoformat()


def nuevo_token() -> str:
    """Un token aleatorio, para una cuenta o un dominio."""
    return secrets.token_urlsafe(32)


def _texto(valor: object) -> str:
    return "" if valor is None else str(valor).strip()


def _booleano(valor: object, donde: str) -> bool | None:
    """El tri-estado: None = sin definir, True/False = decidido."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int) and valor in (0, 1):
        return bool(valor)
    if isinstance(valor, str) and valor.lower() in {"true", "1", "yes"}:
        return True
    if isinstance(valor, str) and valor.lower() in {"false", "0", "no"}:
        return False
    raise StoreError(f"{donde} tiene que ser true o false, no {valor!r}.")


def _entero(valor: object, donde: str) -> int | None:
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise StoreError(f"{donde} tiene que ser un número entero, no {valor!r}.") from None


def _sin_saltos(valor: str, donde: str, maximo: int = 200) -> str:
    """Un texto que no puede llevar saltos de línea.

    Acaba en una cabecera o en una URL: un salto de línea dejaría inyectar
    cabeceras, y una barra partiría la ruta.
    """
    texto = valor.strip()
    if any(char in texto for char in "\r\n\x00"):
        raise StoreError(f"{donde} no puede llevar saltos de línea.")
    if len(texto) > maximo:
        raise StoreError(f"{donde} es demasiado largo (máximo {maximo} caracteres).")
    return texto


class Store:
    """Los dominios y las cuentas, en la base de datos."""

    def __init__(self, database: Database, cipher: Cipher, settings: ServerSettings) -> None:
        self.db = database
        self.cipher = cipher
        self.settings = settings

    # --- lecturas ------------------------------------------------------------

    def dominios(self) -> list[DomainRecord]:
        filas = self.db.connect().execute("SELECT * FROM domains ORDER BY name").fetchall()
        return [DomainRecord.from_row(fila) for fila in filas]

    def cuentas(self) -> list[AccountRecord]:
        filas = self.db.connect().execute("SELECT * FROM accounts ORDER BY name").fetchall()
        return [AccountRecord.from_row(fila) for fila in filas]

    def dominio(self, identificador: int) -> DomainRecord | None:
        fila = (
            self.db.connect()
            .execute("SELECT * FROM domains WHERE id = ?", (identificador,))
            .fetchone()
        )
        return None if fila is None else DomainRecord.from_row(fila)

    def cuenta(self, identificador: int) -> AccountRecord | None:
        fila = (
            self.db.connect()
            .execute("SELECT * FROM accounts WHERE id = ?", (identificador,))
            .fetchone()
        )
        return None if fila is None else AccountRecord.from_row(fila)

    def dominio_por_nombre(self, nombre: str) -> DomainRecord | None:
        fila = (
            self.db.connect()
            .execute("SELECT * FROM domains WHERE name = ?", (nombre.strip().lower(),))
            .fetchone()
        )
        return None if fila is None else DomainRecord.from_row(fila)

    def cuentas_del_dominio(self, identificador: int) -> list[AccountRecord]:
        filas = (
            self.db.connect()
            .execute("SELECT * FROM accounts WHERE domain_id = ? ORDER BY name", (identificador,))
            .fetchall()
        )
        return [AccountRecord.from_row(fila) for fila in filas]

    def dominio_por_defecto(self) -> DomainRecord | None:
        fila = (
            self.db.connect()
            .execute("SELECT * FROM domains WHERE is_default = 1 LIMIT 1")
            .fetchone()
        )
        return None if fila is None else DomainRecord.from_row(fila)

    def hay_cuentas(self) -> bool:
        fila = self.db.connect().execute("SELECT 1 FROM accounts LIMIT 1").fetchone()
        return fila is not None

    # --- dominios ------------------------------------------------------------

    def crear_dominio(self, datos: Mapping[str, object]) -> int:
        nombre = self._nombre_dominio(datos.get("name"))
        etiqueta = _sin_saltos(_texto(datos.get("label")), "La etiqueta del dominio", 100)
        if self.dominio_por_nombre(nombre) is not None:
            raise StoreError(f"Ya existe un dominio llamado {nombre}.")
        with self.db.write() as con:
            cur = con.execute(
                "INSERT INTO domains(name, label, is_default, bearer, allow_send, allow_mark, "
                "allow_delete, allow_drafts, allow_direct_send, imap_host, imap_port, "
                "imap_ssl, smtp_host, smtp_port, smtp_security, created_at) "
                "VALUES(?,?,0,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    nombre,
                    etiqueta,
                    _texto(datos.get("bearer")) or None,
                    _booleano(datos.get("allow_send"), "allow_send"),
                    _booleano(datos.get("allow_mark"), "allow_mark"),
                    _booleano(datos.get("allow_delete"), "allow_delete"),
                    _booleano(datos.get("allow_drafts"), "allow_drafts"),
                    _booleano(datos.get("allow_direct_send"), "allow_direct_send"),
                    _sin_saltos(
                        _texto(datos.get("imap_host")), "El servidor IMAP del dominio", 200
                    ),
                    _entero(datos.get("imap_port"), "El puerto IMAP del dominio"),
                    _booleano(datos.get("imap_ssl"), "imap_ssl"),
                    _sin_saltos(
                        _texto(datos.get("smtp_host")), "El servidor SMTP del dominio", 200
                    ),
                    _entero(datos.get("smtp_port"), "El puerto SMTP del dominio"),
                    _sin_saltos(_texto(datos.get("smtp_security")), "El modo SMTP del dominio", 20),
                    ahora(),
                ),
            )
            return int(cur.lastrowid or 0)

    def cambiar_dominio(self, identificador: int, datos: Mapping[str, object]) -> None:
        if self.dominio(identificador) is None:
            raise StoreError(f"No existe el dominio {identificador}.")
        campos: dict[str, object] = {}
        if "name" in datos:
            nombre = self._nombre_dominio(datos.get("name"))
            otro = self.dominio_por_nombre(nombre)
            if otro is not None and otro.id != identificador:
                raise StoreError(f"Ya existe un dominio llamado {nombre}.")
            campos["name"] = nombre
        if "label" in datos:
            campos["label"] = _sin_saltos(
                _texto(datos.get("label")), "La etiqueta del dominio", 100
            )
        if "bearer" in datos:
            token = _texto(datos.get("bearer"))
            if token:
                self._comprobar_token(token, excluir_dominio=identificador)
            campos["bearer"] = token or None
        for permiso in (
            "allow_send",
            "allow_mark",
            "allow_delete",
            "allow_drafts",
            "allow_direct_send",
        ):
            if permiso in datos:
                campos[permiso] = _booleano(datos.get(permiso), permiso)
        for campo, donde in (
            ("imap_host", "El servidor IMAP del dominio"),
            ("smtp_host", "El servidor SMTP del dominio"),
            ("smtp_security", "El modo SMTP del dominio"),
        ):
            if campo in datos:
                campos[campo] = _sin_saltos(_texto(datos.get(campo)), donde, 200)
        for campo, donde in (("imap_port", "El puerto IMAP"), ("smtp_port", "El puerto SMTP")):
            if campo in datos:
                campos[campo] = _entero(datos.get(campo), f"{donde} del dominio")
        if "imap_ssl" in datos:
            campos["imap_ssl"] = _booleano(datos.get("imap_ssl"), "imap_ssl")
        if not campos:
            return
        with self.db.write() as con:
            self._actualizar(con, "domains", identificador, campos)

    def borrar_dominio(self, identificador: int) -> None:
        if self.dominio(identificador) is None:
            raise StoreError(f"No existe el dominio {identificador}.")
        with self.db.write() as con:
            con.execute("DELETE FROM accounts WHERE domain_id = ?", (identificador,))
            con.execute("DELETE FROM domains WHERE id = ?", (identificador,))

    def marcar_por_defecto(self, identificador: int | None) -> None:
        """Marca un dominio como el que abre /mcp. Solo puede haber uno."""
        with self.db.write() as con:
            if identificador is None:
                con.execute("UPDATE domains SET is_default = 0")
                return
            if self.dominio(identificador) is None:
                raise StoreError(f"No existe el dominio {identificador}.")
            con.execute("UPDATE domains SET is_default = 0")
            con.execute("UPDATE domains SET is_default = 1 WHERE id = ?", (identificador,))

    # --- cuentas -------------------------------------------------------------

    def crear_cuenta(self, datos: Mapping[str, object]) -> tuple[int, str]:
        """Crea una cuenta. Devuelve su identificador y su token.

        El token se genera si no viene dado: el modelo de seguridad es a
        nivel de cuenta, y una cuenta sin credencial propia solo se abre
        con el bearer general.
        """
        nombre = self._nombre_cuenta(datos.get("name"))
        usuario = _sin_saltos(_texto(datos.get("username")), "El usuario de la cuenta", 200)
        if not usuario:
            raise StoreError("La cuenta necesita un usuario.")
        dominio_id = _entero(datos.get("domain_id"), "El dominio de la cuenta")
        if dominio_id is None:
            raise StoreError("La cuenta necesita un dominio.")
        if self.dominio(dominio_id) is None:
            raise StoreError(f"No existe el dominio {dominio_id}.")
        contrasena = _texto(datos.get("password"))
        if not contrasena:
            raise StoreError("La cuenta necesita la contraseña del correo.")
        if self.cuenta_por_nombre(nombre) is not None:
            raise StoreError(f"Ya existe una cuenta llamada {nombre}.")
        if self.cuenta_por_usuario(usuario) is not None:
            raise StoreError(f"Ya existe una cuenta con el usuario {usuario}.")
        self._comprobar_nombre_del_dominio(nombre)
        token = _texto(datos.get("bearer")) or nuevo_token()
        self._comprobar_token(token)
        with self.db.write() as con:
            cur = con.execute(
                "INSERT INTO accounts(domain_id, name, label, sender, username, password, "
                "imap_host, imap_port, imap_ssl, smtp_host, smtp_port, smtp_security, "
                "drafts_folder, sent_folder, trash_folder, allow_send, allow_mark, "
                "allow_delete, allow_drafts, allow_direct_send, bearer, enabled, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    dominio_id,
                    nombre,
                    _sin_saltos(_texto(datos.get("label")), "La etiqueta de la cuenta", 100),
                    _sin_saltos(
                        _texto(datos.get("sender")), "El nombre visible del remitente", 100
                    ),
                    usuario,
                    self.cipher.encrypt(contrasena),
                    _sin_saltos(
                        _texto(datos.get("imap_host")), "El servidor IMAP de la cuenta", 200
                    ),
                    _entero(datos.get("imap_port"), "El puerto IMAP de la cuenta"),
                    _booleano(datos.get("imap_ssl"), "imap_ssl"),
                    _sin_saltos(
                        _texto(datos.get("smtp_host")), "El servidor SMTP de la cuenta", 200
                    ),
                    _entero(datos.get("smtp_port"), "El puerto SMTP de la cuenta"),
                    _sin_saltos(
                        _texto(datos.get("smtp_security")), "El modo SMTP de la cuenta", 20
                    ),
                    _sin_saltos(
                        _texto(datos.get("drafts_folder")), "La carpeta de borradores", 200
                    ),
                    _sin_saltos(_texto(datos.get("sent_folder")), "La carpeta de enviados", 200),
                    _sin_saltos(_texto(datos.get("trash_folder")), "La carpeta de papelera", 200),
                    _booleano(datos.get("allow_send"), "allow_send"),
                    _booleano(datos.get("allow_mark"), "allow_mark"),
                    _booleano(datos.get("allow_delete"), "allow_delete"),
                    _booleano(datos.get("allow_drafts"), "allow_drafts"),
                    _booleano(datos.get("allow_direct_send"), "allow_direct_send"),
                    token,
                    1,
                    ahora(),
                ),
            )
            return int(cur.lastrowid or 0), token

    def cambiar_cuenta(self, identificador: int, datos: Mapping[str, object]) -> None:
        registro = self.cuenta(identificador)
        if registro is None:
            raise StoreError(f"No existe la cuenta {identificador}.")
        campos: dict[str, object] = {}
        if "name" in datos:
            nombre = self._nombre_cuenta(datos.get("name"))
            otro = self.cuenta_por_nombre(nombre)
            if otro is not None and otro.id != identificador:
                raise StoreError(f"Ya existe una cuenta llamada {nombre}.")
            self._comprobar_nombre_del_dominio(nombre)
            campos["name"] = nombre
        if "username" in datos:
            usuario = _sin_saltos(_texto(datos.get("username")), "El usuario de la cuenta", 200)
            if not usuario:
                raise StoreError("La cuenta necesita un usuario.")
            otro = self.cuenta_por_usuario(usuario)
            if otro is not None and otro.id != identificador:
                raise StoreError(f"Ya existe una cuenta con el usuario {usuario}.")
            campos["username"] = usuario
        if "domain_id" in datos:
            dominio_id = _entero(datos.get("domain_id"), "El dominio de la cuenta")
            if dominio_id is None or self.dominio(dominio_id) is None:
                raise StoreError("El dominio de la cuenta no existe.")
            campos["domain_id"] = dominio_id
        if "label" in datos:
            campos["label"] = _sin_saltos(
                _texto(datos.get("label")), "La etiqueta de la cuenta", 100
            )
        if "sender" in datos:
            campos["sender"] = _sin_saltos(
                _texto(datos.get("sender")), "El nombre visible del remitente", 100
            )
        if "bearer" in datos:
            token = _texto(datos.get("bearer"))
            if token:
                self._comprobar_token(token, excluir_cuenta=identificador)
            campos["bearer"] = token or None
        if "enabled" in datos:
            campos["enabled"] = 1 if _booleano(datos.get("enabled"), "enabled") else 0
        for permiso in (
            "allow_send",
            "allow_mark",
            "allow_delete",
            "allow_drafts",
            "allow_direct_send",
        ):
            if permiso in datos:
                campos[permiso] = _booleano(datos.get(permiso), permiso)
        for campo, donde in (
            ("imap_host", "El servidor IMAP de la cuenta"),
            ("smtp_host", "El servidor SMTP de la cuenta"),
            ("smtp_security", "El modo SMTP de la cuenta"),
            ("drafts_folder", "La carpeta de borradores"),
            ("sent_folder", "La carpeta de enviados"),
            ("trash_folder", "La carpeta de papelera"),
        ):
            if campo in datos:
                campos[campo] = _sin_saltos(_texto(datos.get(campo)), donde, 200)
        for campo, donde in (("imap_port", "El puerto IMAP"), ("smtp_port", "El puerto SMTP")):
            if campo in datos:
                campos[campo] = _entero(datos.get(campo), f"{donde} de la cuenta")
        if "imap_ssl" in datos:
            campos["imap_ssl"] = _booleano(datos.get("imap_ssl"), "imap_ssl")
        contrasena = _texto(datos.get("password"))
        if contrasena:
            campos["password"] = self.cipher.encrypt(contrasena)
        if not campos:
            return
        with self.db.write() as con:
            self._actualizar(con, "accounts", identificador, campos)

    def borrar_cuenta(self, identificador: int) -> None:
        if self.cuenta(identificador) is None:
            raise StoreError(f"No existe la cuenta {identificador}.")
        with self.db.write() as con:
            con.execute("DELETE FROM accounts WHERE id = ?", (identificador,))

    def rotar_token(self, nivel: str, identificador: int) -> str:
        """Un token nuevo para una cuenta o un dominio.

        El token viejo deja de valer en cuanto se escribe el nuevo.
        """
        if nivel == "cuenta":
            if self.cuenta(identificador) is None:
                raise StoreError(f"No existe la cuenta {identificador}.")
            token = nuevo_token()
            with self.db.write() as con:
                self._actualizar(con, "accounts", identificador, {"bearer": token})
            return token
        if nivel == "dominio":
            if self.dominio(identificador) is None:
                raise StoreError(f"No existe el dominio {identificador}.")
            token = nuevo_token()
            with self.db.write() as con:
                self._actualizar(con, "domains", identificador, {"bearer": token})
            return token
        raise StoreError("Nivel desconocido: solo hay cuentas y dominios.")

    # --- ayudas --------------------------------------------------------------

    def comprobar_clave(self) -> None:
        """Comprueba que la clave es la de esta base de datos.

        Se guarda una fila conocida, cifrada con la clave. Si no se
        descifra, la clave es de otra base, y el arranque para: sin la
        clave correcta las contraseñas no se pueden leer, y el síntoma
        sería "las cuentas no funcionan" sin más pista.
        """
        valor = self.db.meta(META_KEY_CHECK)
        if valor is None:
            with self.db.write() as con:
                self.db.set_meta(
                    con, META_KEY_CHECK, self.cipher.encrypt(KEY_CHECK_PLAINTEXT).hex()
                )
            return
        try:
            self.cipher.decrypt(bytes.fromhex(valor))
        except (CipherError, ValueError):
            raise SystemExit(
                "La clave no corresponde a esta base de datos. MCP_DASHBOARD_KEY es la de "
                "otra instalación, o la base es de otra. Sin la clave correcta no se "
                "pueden descifrar las contraseñas."
            ) from None

    def cuenta_por_nombre(self, nombre: str) -> AccountRecord | None:
        fila = (
            self.db.connect()
            .execute("SELECT * FROM accounts WHERE name = ?", (nombre.strip(),))
            .fetchone()
        )
        return None if fila is None else AccountRecord.from_row(fila)

    def cuenta_por_usuario(self, usuario: str) -> AccountRecord | None:
        fila = (
            self.db.connect()
            .execute("SELECT * FROM accounts WHERE username = ?", (usuario.strip(),))
            .fetchone()
        )
        return None if fila is None else AccountRecord.from_row(fila)

    def _nombre_cuenta(self, valor: object) -> str:
        nombre = _texto(valor)
        if not nombre:
            raise StoreError("La cuenta necesita un nombre: es el identificador de la ruta.")
        if not NAME_RE.fullmatch(nombre):
            raise StoreError(
                "El nombre de la cuenta solo admite letras, números y los signos "
                "'.', '-', '_' y '@'. Va en una ruta: /mcp/<nombre>."
            )
        return nombre

    def _nombre_dominio(self, valor: object) -> str:
        nombre = _texto(valor).lower()
        if not nombre:
            raise StoreError("El dominio necesita un nombre.")
        if len(nombre) > 120 or not DOMAIN_RE.fullmatch(nombre):
            raise StoreError(
                "El nombre del dominio no vale: tiene que ser un dominio, como corp.example.com."
            )
        return nombre

    def _comprobar_nombre_del_dominio(self, nombre: str) -> None:
        """Una cuenta no puede llamarse como un dominio.

        Las dos rutas tienen la misma forma. Si los dos nombres existieran,
        la cuenta ganaría y el dominio no tendría ruta propia.
        """
        dominio = self.dominio_por_nombre(nombre)
        if dominio is not None:
            raise StoreError(
                f"Ya existe un dominio llamado {nombre}. El nombre de una cuenta "
                "no puede ser el de un dominio: las dos van en la misma ruta."
            )

    def _comprobar_token(
        self,
        token: str,
        excluir_cuenta: int | None = None,
        excluir_dominio: int | None = None,
    ) -> None:
        """Un token no puede repetirse en ningún nivel.

        Un token repetido hace que la ruta no aísle nada: la credencial
        de una cuenta abriría la de otra.
        """
        if not token:
            return
        for cuenta in self.cuentas():
            if cuenta.id == excluir_cuenta:
                continue
            if cuenta.bearer and cuenta.bearer == token:
                raise StoreError(f"Ese token ya lo usa la cuenta {cuenta.name}.")
        for dominio in self.dominios():
            if dominio.id == excluir_dominio:
                continue
            if dominio.bearer and dominio.bearer == token:
                raise StoreError(f"Ese token ya lo usa el dominio {dominio.name}.")

    def _actualizar(
        self, con: sqlite3.Connection, tabla: str, identificador: int, campos: Mapping[str, object]
    ) -> None:
        if not campos:
            return
        asignaciones = ", ".join(f"{campo} = ?" for campo in campos)
        valores = list(campos.values()) + [identificador]
        con.execute(f"UPDATE {tabla} SET {asignaciones} WHERE id = ?", valores)
