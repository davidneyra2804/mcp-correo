"""La base de datos: esquema, cifrado, permisos y tiempo real.

La base es la fuente de las cuentas cuando el panel está activo. Estas
pruebas miran las tres cosas que se rompen fácil: que la clave no
corresponda, que los permisos se resuelvan mal, y que el servidor no se
entere de que la base ha cambiado.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from store.accounts import DatabaseAccounts, account_secrets
from store.crypto import Cipher, CipherError
from store.db import Database
from store.store import Store, StoreError
from tests.ayuda import ajustes

ROOT = Path(__file__).resolve().parents[1]
CLAVE = "clave-de-prueba-0123456789abcdef"
OTRA_CLAVE = "otra-clave-de-prueba-0123456789"


@pytest.fixture
def db(tmp_path: Path) -> Database:
    base = Database(tmp_path / "cuentas.db")
    base.prepare()
    return base


@pytest.fixture
def store(db: Database) -> Store:
    settings = ajustes()
    return Store(db, Cipher(CLAVE), settings)


def _dominio(store: Store, nombre: str = "corp.example.com") -> int:
    return store.crear_dominio({"name": nombre, "label": "Corporación"})


def _cuenta(store: Store, dominio: int, **extra: object) -> int:
    datos: dict[str, object] = {
        "domain_id": dominio,
        "name": "ada@corp.example.com",
        "username": "ada@corp.example.com",
        "password": "clave-ficticia",
        "imap_host": "imap.corp.example.com",
    }
    datos.update(extra)
    identificador, _token = store.crear_cuenta(datos)
    return identificador


# --- el cifrado ---------------------------------------------------------------


def test_la_contrasena_va_y_vuelve() -> None:
    cifrador = Cipher(CLAVE)
    blob = cifrador.encrypt("la-clave-del-correo")
    assert b"la-clave-del-correo" not in blob
    assert cifrador.decrypt(blob) == "la-clave-del-correo"


def test_una_clave_corta_no_se_acepta() -> None:
    with pytest.raises(CipherError):
        Cipher("corta")


def test_otra_clave_no_descifra() -> None:
    blob = Cipher(CLAVE).encrypt("secreto")
    with pytest.raises(CipherError):
        Cipher(OTRA_CLAVE).decrypt(blob)


def test_la_contrasena_no_se_guarda_en_claro(store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio)
    fila = store.db.connect().execute("SELECT password FROM accounts").fetchone()
    assert b"clave-ficticia" not in bytes(fila["password"])


def test_una_clave_que_no_es_la_de_la_base_para_el_arranque(store: Store) -> None:
    store.comprobar_clave()
    otra = Store(store.db, Cipher(OTRA_CLAVE), store.settings)
    with pytest.raises(SystemExit, match="no corresponde"):
        otra.comprobar_clave()


# --- el esquema ---------------------------------------------------------------


def test_la_base_nace_con_el_esquema(store: Store) -> None:
    tablas = {
        fila["name"]
        for fila in store.db.connect().execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"domains", "accounts", "meta", "direct_sends"} <= tablas


def test_la_version_del_esquema_queda_registrada(store: Store) -> None:
    from store.db import SCHEMA_VERSION

    assert store.db.meta("schema_version") == str(SCHEMA_VERSION)


def test_preparar_dos_veces_no_rompe_nada(store: Store) -> None:
    from store.db import SCHEMA_VERSION

    store.db.prepare()
    store.db.prepare()
    assert store.db.meta("schema_version") == str(SCHEMA_VERSION)


def test_una_base_de_la_version_anterior_migra(tmp_path: Path) -> None:
    """La migración desde la versión anterior, con datos dentro.

    Esto es lo que se encuentra un despliegue en marcha: la base del
    volumen tiene la versión anterior y hay que migrarla sin perder las
    cuentas. Se arma una base v1 a mano, con sus cuentas, y se prepara.
    """
    import sqlite3

    from store.db import META_REVISION, META_VERSION, SCHEMA_VERSION

    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.executescript(
        """
        CREATE TABLE domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            bearer TEXT,
            allow_send INTEGER,
            allow_mark INTEGER,
            allow_delete INTEGER,
            allow_drafts INTEGER,
            imap_host TEXT NOT NULL DEFAULT '',
            imap_port INTEGER,
            imap_ssl INTEGER,
            smtp_host TEXT NOT NULL DEFAULT '',
            smtp_port INTEGER,
            smtp_security TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain_id INTEGER NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
            name TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL DEFAULT '',
            sender TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL UNIQUE,
            password BLOB NOT NULL,
            imap_host TEXT NOT NULL DEFAULT '',
            imap_port INTEGER,
            imap_ssl INTEGER,
            smtp_host TEXT NOT NULL DEFAULT '',
            smtp_port INTEGER,
            smtp_security TEXT,
            drafts_folder TEXT NOT NULL DEFAULT '',
            sent_folder TEXT NOT NULL DEFAULT '',
            trash_folder TEXT NOT NULL DEFAULT '',
            allow_send INTEGER,
            allow_mark INTEGER,
            allow_delete INTEGER,
            allow_drafts INTEGER,
            bearer TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta(key, value) VALUES('schema_version', '1');
        INSERT INTO meta(key, value) VALUES('revision', '7');
        INSERT INTO domains(name, label, created_at)
            VALUES('corp.example.com', 'Corporación', '2026-10-01T00:00:00+00:00');
        INSERT INTO accounts(domain_id, name, username, password, created_at)
            VALUES(1, 'ada@corp.example.com', 'ada@corp.example.com', X'00',
                   '2026-10-01T00:00:00+00:00');
        """
    )
    con.commit()
    con.close()

    base = Database(ruta)
    assert base.prepare() == SCHEMA_VERSION
    # La cuenta está y la revisión no se ha perdido.
    fila = base.connect().execute("SELECT name FROM accounts").fetchone()
    assert fila["name"] == "ada@corp.example.com"
    # La migración es una escritura: sube el contador de revisiones, como
    # cualquier otra. No se reinicia.
    assert base.revision() == 8
    # Y la tabla nueva está, con el permiso por cuenta.
    assert "direct_sends" in {
        f["name"]
        for f in base.connect().execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert base.meta(META_VERSION) == str(SCHEMA_VERSION)
    assert base.meta(META_REVISION) == "8"


# --- las escrituras -----------------------------------------------------------


def test_cada_escritura_sube_la_revision(store: Store) -> None:
    antes = store.db.revision()
    _dominio(store)
    assert store.db.revision() == antes + 1


def test_leer_no_sube_la_revision(store: Store) -> None:
    _dominio(store)
    antes = store.db.revision()
    store.dominios()
    store.cuentas()
    assert store.db.revision() == antes


# --- dominios y cuentas --------------------------------------------------------


def test_se_crea_un_dominio_una_cuenta(store: Store) -> None:
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio)
    assert store.dominio(dominio) is not None
    assert store.cuenta(cuenta) is not None
    assert store.cuenta(cuenta).username == "ada@corp.example.com"


def test_un_nombre_repetido_se_rechaza(store: Store) -> None:
    _dominio(store)
    with pytest.raises(StoreError, match="Ya existe un dominio"):
        _dominio(store)


def test_un_usuario_repetido_se_rechaza(store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio)
    with pytest.raises(StoreError, match="Ya existe una cuenta con el usuario"):
        _cuenta(store, dominio, name="otro@corp.example.com")


def test_una_cuenta_no_puede_llamarse_como_un_dominio(store: Store) -> None:
    dominio = _dominio(store)
    with pytest.raises(StoreError, match="no puede ser el de un dominio"):
        _cuenta(store, dominio, name="corp.example.com")


def test_un_nombre_con_espacios_se_rechaza(store: Store) -> None:
    dominio = _dominio(store)
    with pytest.raises(StoreError, match="Va en una ruta"):
        _cuenta(store, dominio, name="ada lovelace")


def test_una_cuenta_sin_contrasena_no_se_crea(store: Store) -> None:
    dominio = _dominio(store)
    with pytest.raises(StoreError, match="contraseña"):
        store.crear_cuenta(
            {
                "domain_id": dominio,
                "name": "ada@corp.example.com",
                "username": "ada@corp.example.com",
            }
        )


def test_borrar_un_dominio_borra_sus_cuentas(store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio)
    store.borrar_dominio(dominio)
    assert store.cuentas() == []


def test_solo_hay_un_dominio_por_defecto(store: Store) -> None:
    uno = _dominio(store, "uno.example.com")
    dos = _dominio(store, "dos.example.com")
    store.marcar_por_defecto(uno)
    store.marcar_por_defecto(dos)
    por_defecto = [d for d in store.dominios() if d.is_default]
    assert len(por_defecto) == 1
    assert por_defecto[0].id == dos


def test_quitar_el_dominio_por_defecto(store: Store) -> None:
    dominio = _dominio(store)
    store.marcar_por_defecto(dominio)
    store.marcar_por_defecto(None)
    assert not [d for d in store.dominios() if d.is_default]


def test_rotar_el_token_invalida_el_anterior(store: Store) -> None:
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio)
    antes = store.cuenta(cuenta).bearer
    token = store.rotar_token("cuenta", cuenta)
    assert token != antes
    assert store.cuenta(cuenta).bearer == token


def test_crear_una_cuenta_genera_su_token(store: Store) -> None:
    """El modelo es a nivel de cuenta: la cuenta nace con credencial."""
    dominio = _dominio(store)
    _identificador, token = store.crear_cuenta(
        {
            "domain_id": dominio,
            "name": "ada@corp.example.com",
            "username": "ada@corp.example.com",
            "password": "clave-ficticia",
        }
    )
    assert len(token) >= 16


def test_un_token_repetido_se_rechaza(store: Store) -> None:
    """Un token repetido haría que una credencial abriera dos cuentas."""
    dominio = _dominio(store)
    _cuenta(store, dominio, bearer="token-repetido-0123456789abcdef")
    with pytest.raises(StoreError, match="ya lo usa la cuenta"):
        _cuenta(
            store,
            dominio,
            name="otro@corp.example.com",
            username="otro@corp.example.com",
            bearer="token-repetido-0123456789abcdef",
        )


def test_un_token_de_dominio_no_puede_ser_el_de_una_cuenta(store: Store) -> None:
    dominio = _dominio(store)
    store.cambiar_dominio(dominio, {"bearer": "token-del-dominio-0123456789abcdef"})
    with pytest.raises(StoreError, match="ya lo usa el dominio"):
        _cuenta(store, dominio, bearer="token-del-dominio-0123456789abcdef")


# --- la cadena de permisos -----------------------------------------------------


def test_el_dominio_manda_sobre_el_global(store: Store) -> None:
    """El permiso por dominio se aplica a sus cuentas."""
    from config import account_allows

    dominio = _dominio(store)
    store.cambiar_dominio(dominio, {"allow_send": False})
    _cuenta(store, dominio)
    source = DatabaseAccounts(store, store.settings)
    cuenta = next(iter(source.snapshot().accounts.values()))
    settings = store.settings
    assert settings.enable_send is False or account_allows(cuenta, "send", settings) is False


def test_la_cuenta_manda_sobre_el_dominio(store: Store) -> None:

    dominio = _dominio(store)
    store.cambiar_dominio(dominio, {"allow_send": False})
    _cuenta(store, dominio, allow_send=True)
    source = DatabaseAccounts(store, store.settings)
    cuenta = next(iter(source.snapshot().accounts.values()))
    assert cuenta.allow_send is True


def test_sin_definir_hereda(store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio)
    source = DatabaseAccounts(store, store.settings)
    cuenta = next(iter(source.snapshot().accounts.values()))
    assert cuenta.allow_send is None


def test_el_envio_directo_tiene_su_propia_cadena_de_permisos(store: Store) -> None:
    """El permiso directo no se mezcla con el del envío normal."""
    dominio = _dominio(store)
    _cuenta(store, dominio, allow_send=True)
    source = DatabaseAccounts(store, store.settings)
    cuenta = next(iter(source.snapshot().accounts.values()))
    assert cuenta.allow_send is True
    # Sin definir: hereda del dominio, y el dominio no dice nada.
    assert cuenta.allow_direct_send is None

    store.cambiar_dominio(dominio, {"allow_direct_send": True})
    source = DatabaseAccounts(store, store.settings)
    cuenta = next(iter(source.snapshot().accounts.values()))
    assert cuenta.allow_direct_send is True

    # Y la cuenta puede prohibirlo aunque el dominio lo permita.
    identificador = store.cuenta_por_nombre("ada@corp.example.com")
    assert identificador is not None
    store.cambiar_cuenta(identificador.id, {"allow_direct_send": False})
    source = DatabaseAccounts(store, store.settings)
    cuenta = next(iter(source.snapshot().accounts.values()))
    assert cuenta.allow_direct_send is False


# --- la fuente de cuentas ------------------------------------------------------


def test_la_fuente_lee_las_cuentas(store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio)
    source = DatabaseAccounts(store, store.settings)
    snapshot = source.snapshot()
    assert "ada@corp.example.com" in snapshot.accounts
    assert snapshot.accounts["ada@corp.example.com"].password == "clave-ficticia"


def test_la_fuente_ve_las_cuentas_nuevas_sin_reiniciar(store: Store) -> None:
    """El punto del tiempo real: crear y usar, sin nada más."""
    source = DatabaseAccounts(store, store.settings)
    assert source.snapshot().accounts == {}
    dominio = _dominio(store)
    _cuenta(store, dominio)
    assert "ada@corp.example.com" in source.snapshot().accounts


def test_al_borrar_una_cuenta_desaparece(store: Store) -> None:
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio)
    source = DatabaseAccounts(store, store.settings)
    assert store.cuenta(cuenta) is not None
    assert "ada@corp.example.com" in source.snapshot().accounts
    store.borrar_cuenta(cuenta)
    assert source.snapshot().accounts == {}


def test_una_cuenta_desactivada_no_se_expone(store: Store) -> None:
    dominio = _dominio(store)
    cuenta = _cuenta(store, dominio)
    source = DatabaseAccounts(store, store.settings)
    store.cambiar_cuenta(cuenta, {"enabled": False})
    assert source.snapshot().accounts == {}


def test_el_dominio_por_defecto_abre_la_ruta_general(store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio)
    store.marcar_por_defecto(dominio)
    source = DatabaseAccounts(store, store.settings)
    snapshot = source.snapshot()
    assert snapshot.default_scope == frozenset({"ada@corp.example.com"})


def test_sin_dominio_por_defecto_la_ruta_general_no_abre_nada(store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio)
    source = DatabaseAccounts(store, store.settings)
    assert source.snapshot().default_scope == frozenset()


def test_los_secretos_de_las_cuentas_nuevas_se_avisan(store: Store) -> None:
    dominio = _dominio(store)
    _cuenta(store, dominio)
    source = DatabaseAccounts(store, store.settings)
    secretos = account_secrets(source.snapshot())
    assert "clave-ficticia" in secretos
