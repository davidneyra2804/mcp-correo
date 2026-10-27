"""La base de datos: conexión, esquema y migraciones.

Un fichero SQLite. WAL, claves foráneas y una conexión por hilo: el panel
escribe desde su hilo y el servidor lee desde el suyo, y una conexión de
SQLite no se comparte entre hilos.

El esquema tiene versión. Las migraciones se aplican al arrancar, cada una
en su transacción, y si una falla el proceso para: una base a medio
migrar es peor que no tener base.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

#: La versión del esquema que este código entiende.
SCHEMA_VERSION = 1

#: Clave de la fila de metadatos con la versión del esquema.
META_VERSION = "schema_version"
#: Clave de la fila de metadatos con el contador de revisiones.
META_REVISION = "revision"
#: Clave de la fila de metadatos con la comprobación de la clave.
META_KEY_CHECK = "key_check"

#: Lo que se guarda en la fila de comprobación de la clave. Si se descifra
#: con la clave del operador, la clave es la correcta.
KEY_CHECK_PLAINTEXT = "mcp-correo-clave-ok"

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS domains (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    label         TEXT    NOT NULL DEFAULT '',
    is_default    INTEGER NOT NULL DEFAULT 0,
    bearer        TEXT,
    allow_send    INTEGER,
    allow_mark    INTEGER,
    allow_delete  INTEGER,
    allow_drafts  INTEGER,
    imap_host     TEXT    NOT NULL DEFAULT '',
    imap_port     INTEGER,
    imap_ssl      INTEGER,
    smtp_host     TEXT    NOT NULL DEFAULT '',
    smtp_port     INTEGER,
    smtp_security TEXT,
    created_at    TEXT    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS un_dominio_por_defecto
    ON domains(is_default) WHERE is_default = 1;

CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id       INTEGER NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL UNIQUE,
    label           TEXT    NOT NULL DEFAULT '',
    sender          TEXT    NOT NULL DEFAULT '',
    username        TEXT    NOT NULL UNIQUE,
    password        BLOB    NOT NULL,
    imap_host       TEXT    NOT NULL DEFAULT '',
    imap_port       INTEGER,
    imap_ssl        INTEGER,
    smtp_host       TEXT    NOT NULL DEFAULT '',
    smtp_port       INTEGER,
    smtp_security   TEXT,
    drafts_folder   TEXT    NOT NULL DEFAULT '',
    sent_folder     TEXT    NOT NULL DEFAULT '',
    trash_folder    TEXT    NOT NULL DEFAULT '',
    allow_send      INTEGER,
    allow_mark      INTEGER,
    allow_delete    INTEGER,
    allow_drafts    INTEGER,
    bearer          TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    """El fichero SQLite. Una conexión por hilo, una revisión por cambio."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._local = threading.local()
        self._write_lock = threading.Lock()

    # --- conexión ------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        """La conexión de este hilo. Se abre la primera vez que se pide."""
        con: sqlite3.Connection | None = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.path, isolation_level=None, timeout=5.0)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA busy_timeout=5000")
            self._local.con = con
        return con

    def close(self) -> None:
        """Cierra la conexión de este hilo, si la hay."""
        con: sqlite3.Connection | None = getattr(self._local, "con", None)
        if con is not None:
            con.close()
            self._local.con = None

    # --- escritura -----------------------------------------------------------

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Una transacción de escritura.

        Al terminar bien, sube el contador de revisiones: es lo que lee el
        servidor para saber que tiene que recargar las cuentas.
        """
        con = self.connect()
        with self._write_lock:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
                con.execute(
                    "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
                    f"WHERE key = '{META_REVISION}'"
                )
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")

    # --- lectura -------------------------------------------------------------

    def revision(self) -> int:
        """El contador de revisiones. Cambia con cada escritura."""
        con = self.connect()
        fila = con.execute(f"SELECT value FROM meta WHERE key = '{META_REVISION}'").fetchone()
        if fila is None:
            return 0
        try:
            return int(fila["value"])
        except (TypeError, ValueError):  # pragma: no cover - datos corruptos
            return 0

    def meta(self, key: str) -> str | None:
        """Un valor de la tabla de metadatos."""
        con = self.connect()
        fila = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if fila is None else str(fila["value"])

    def set_meta(self, con: sqlite3.Connection, key: str, value: str) -> None:
        """Escribe un valor de metadatos, dentro de una transacción."""
        con.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # --- esquema -------------------------------------------------------------

    def prepare(self) -> int:
        """Crea el esquema y aplica las migraciones pendientes.

        Devuelve la versión del esquema que hay en la base.
        """
        con = self.connect()
        # La tabla de metadatos es lo primero: sin ella no se sabe qué
        # versión tiene la base, y por tanto qué migraciones faltan.
        con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        actual = self.meta(META_VERSION)
        version = int(actual) if actual is not None else 0
        if version > SCHEMA_VERSION:
            raise SystemExit(
                f"La base de datos es de la versión {version} y este código solo "
                f"entiende hasta la {SCHEMA_VERSION}. Actualiza el servidor."
            )
        if version < 1:
            con.executescript(_SCHEMA_V1)
        with self.write() as wcon:
            if self.meta(META_VERSION) is None:
                self.set_meta(wcon, META_VERSION, str(SCHEMA_VERSION))
            if self.meta(META_REVISION) is None:
                self.set_meta(wcon, META_REVISION, "0")
        return SCHEMA_VERSION
