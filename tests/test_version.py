"""La versión tiene que ser la misma en todos los sitios.

Hay tres lugares donde aparece el número: `version.py` (la fuente de
verdad), `pyproject.toml` (lo exige el formato) y la etiqueta de la
imagen. Si uno se queda atrás, el despliegue y la documentación mienten.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from audit import AuditLog
from server import create_app
from tests.ayuda import ajustes
from version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_la_version_sigue_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_pyproject_dice_la_misma_version() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_la_etiqueta_de_la_imagen_dice_la_misma_version() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"ARG MCP_VERSION=(\S+)", dockerfile)
    assert match, "El Dockerfile debería declarar ARG MCP_VERSION"
    assert match.group(1) == __version__


def test_el_handshake_mcp_dice_la_version(tmp_path: Path) -> None:
    """El cliente ve la versión en el initialize, sin exponerla en /health."""
    settings = ajustes()
    audit = AuditLog(tmp_path / "audit.jsonl")
    application, _runtime = create_app(
        settings, {}, "token-de-prueba-0123456789abcdef", audit=audit
    )
    with TestClient(application, base_url="http://127.0.0.1:8765") as http:
        response = http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": "Bearer token-de-prueba-0123456789abcdef",
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["serverInfo"]["version"] == __version__


def test_health_no_revela_la_version(tmp_path: Path) -> None:
    """`/health` no pide token: no debe filtrar la versión a quien llame."""
    settings = ajustes()
    audit = AuditLog(tmp_path / "audit.jsonl")
    application, _runtime = create_app(
        settings, {}, "token-de-prueba-0123456789abcdef", audit=audit
    )
    with TestClient(application, base_url="http://127.0.0.1:8765") as http:
        response = http.get("/health")
    assert response.status_code == 200
    assert __version__ not in response.text


def test_el_banner_de_arranque_se_ve(tmp_path: Path) -> None:
    """Los logs del arranque tienen que salir de verdad.

    Antes salían porque el SDK configuraba el logger raíz de rebote al
    construir el MCPServer, con su formato. Si el SDK cambiaba, el banner
    cambiaba con él, o desaparecía.
    """
    import subprocess
    import sys

    from tests.fakes import entorno_de_subproceso

    env = entorno_de_subproceso(
        ROOT,
        MCP_BEARER_TOKEN="token-de-prueba-0123456789abcdef",
        MCP_AUDIT_LOG=str(tmp_path / "audit.jsonl"),
    )
    completed = subprocess.run(
        [sys.executable, "-c", "import server"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    salida = completed.stdout + completed.stderr
    assert "Servidor listo:" in salida, salida
    assert "Configuración: " in salida, salida
    assert f"mcp-correo {__version__}" in salida, salida
    # Con el prefijo de nivel, como los de uvicorn.
    assert "INFO     Servidor listo:" in salida, salida


@pytest.mark.parametrize("fichero", ["README.md", "docs/configuracion.md"])
def test_la_documentacion_no_contradice_la_version(fichero: str) -> None:
    """Si el README habla de una versión concreta, tiene que ser la buena."""
    text = (ROOT / fichero).read_text(encoding="utf-8")
    for mentioned in set(re.findall(r"\bv?(\d+\.\d+\.\d+)\b", text)):
        if mentioned in {"0.2.0", "1.0.0"}:
            assert mentioned == __version__, f"{fichero} menciona {mentioned}"


def _bloque_de_publicar(fichero: Path) -> list[str]:
    """Las líneas del bloque de "Publicar": los `sed` y los `git`.

    Se recorta la sección del fichero, en vez de filtrar el fichero
    entero: si algún día se documenta otro `sed` en el README (un ejemplo
    de rotación, un script de mantenimiento), este helper no lo cogía y
    el test de sincronía fallaba con un bloque que no había cambiado.

    La sección se busca por su encabezado, que es distinto en cada
    fichero ("Publicar" en el AGENTS.md, "Versionado" en el README), y
    acaba en el siguiente encabezado del mismo nivel.
    """
    lineas = fichero.read_text(encoding="utf-8").splitlines()
    inicio = None
    for numero, linea in enumerate(lineas):
        if linea.startswith("## ") and (
            "publicar" in linea.lower() or "versionado" in linea.lower()
        ):
            inicio = numero
            break
    assert inicio is not None, f"{fichero.name}: no está la sección de publicar"
    dentro: list[str] = []
    en_bloque = False
    for linea in lineas[inicio + 1 :]:
        if linea.startswith("## "):
            break
        if linea.startswith("```bash"):
            en_bloque = True
            continue
        if en_bloque and linea.startswith("```"):
            break
        if en_bloque:
            dentro.append(linea)
    return [linea for linea in dentro if linea.startswith(("sed -i ", "git commit ", "git tag "))]


def _patron_de_sed(linea: str) -> str:
    """El lado izquierdo de un `sed`: lo que busca y sustituye.

    Es la parte que tiene que ser la versión actual: si el patrón apunta
    a otra, el `sed` no cambia nada y se publica una versión que dice
    ser la anterior.

    El delimitador del `sed` (`/`, `|`, `"`) se captura para poder
    encontrar el cierre. Un grupo **no** capturante aquí no vale: el
    `\1` sería el grupo equivocado y el patrón saldría vacío, y un test
    que mira una lista vacía pasa siempre.
    """
    coincidencia = re.search(r"s(['\"/|])(.*?)\1", linea)
    return coincidencia.group(2) if coincidencia else ""


def _sustitucion_de_sed(linea: str) -> str:
    """El lado derecho de un `sed`: lo que escribe."""
    coincidencia = re.search(r"s(['\"/|])(.*?)\1(.*?)\1", linea)
    return coincidencia.group(3) if coincidencia else ""


def _versiones(texto: str) -> set[str]:
    """Los números de versión de un texto, con o sin la barra escapada."""
    encontradas = re.findall(r"(\d+(?:\\?\.)?\d+(?:\\?\.)?\d+)", texto)
    return {v.replace("\\", "") for v in encontradas}


def test_los_dos_bloques_de_publicar_apuntan_al_mismo_numero() -> None:
    """El README y el AGENTS.md tienen que publicar lo mismo.

    Pasó en la 2.1.0: el bloque del README se actualizó y el del
    `AGENTS.md` se quedó apuntando a una versión anterior. Seguir el
    `AGENTS.md` al pie de la letra publicaba una versión más vieja que la
    actual, y los `sed` de la documentación no casaban con nada.

    Se comparan **todas** las líneas del bloque, incluidas las de `git
    commit` y `git tag`: la etiqueta es la que decide qué se publica.
    """
    readme = _bloque_de_publicar(ROOT / "README.md")
    agentes = _bloque_de_publicar(ROOT / "AGENTS.md")
    assert readme and agentes, "Uno de los dos bloques de publicar no está"
    assert readme == agentes, (
        "Los bloques de publicar divergen:\n"
        "README.md:\n  " + "\n  ".join(readme) + "\n"
        "AGENTS.md:\n  " + "\n  ".join(agentes)
    )


def test_cada_sed_del_bloque_usa_la_version_actual_como_patron() -> None:
    """El patrón de **cada** `sed` tiene que ser la versión actual.

    El `sed` sustituye la versión actual por la siguiente. Si el patrón
    apunta a otra, no cambia nada y se publica una versión que dice ser
    la anterior.

    Cada línea se mira por separado: mirar la unión de todas esconde el
    error, porque basta con que una de ellas esté bien.

    Y si el patrón no se puede extraer, el test **falla**: un test que
    recorre una lista vacía pasa siempre.
    """
    lineas = [
        linea for linea in _bloque_de_publicar(ROOT / "README.md") if linea.startswith("sed -i ")
    ]
    assert lineas, "El bloque de publicar no tiene ningún sed"
    vistas = 0
    for linea in lineas:
        patron = _patron_de_sed(linea)
        assert patron, f"No se ha podido sacar el patrón de {linea!r}"
        versiones = _versiones(patron)
        if not versiones:
            # El patrón es un comodín (`.*`): el `sed` sustituye lo que
            # haya, así que no lleva número de versión.
            continue
        vistas += 1
        assert versiones == {__version__}, (
            f"El patrón de esta línea no es la versión actual ({__version__}): "
            f"{versiones} en {linea!r}"
        )
    assert vistas >= 2, (
        f"Solo {vistas} líneas del bloque llevan la versión en el patrón: "
        "el test no está mirando lo que dice mirar."
    )


def test_el_bloque_de_publicar_etiqueta_la_version_siguiente() -> None:
    """La etiqueta y el commit tienen que ser de la versión siguiente.

    Si el `git tag` apunta a otra, el workflow aborta: la etiqueta tiene
    que coincidir con la versión que escriben los `sed`. Y no vale solo
    que la etiqueta y el commit coincidan entre sí: tienen que ser **la
    versión que el bloque escribe**.
    """
    lineas = _bloque_de_publicar(ROOT / "README.md")
    etiquetas = set()
    for linea in lineas:
        coincidencia = re.search(r"git tag v(\d+\.\d+\.\d+)", linea)
        if coincidencia:
            etiquetas.add(coincidencia.group(1))
    commits = set()
    for linea in lineas:
        coincidencia = re.search(r'git commit -am "version (\d+\.\d+\.\d+)"', linea)
        if coincidencia:
            commits.add(coincidencia.group(1))
    assert etiquetas, "El bloque no dice qué etiqueta se publica"
    assert commits, "El bloque no dice con qué commit se publica"
    assert etiquetas == commits, (
        f"La etiqueta ({etiquetas}) y el commit ({commits}) no son la misma versión."
    )
    # Y esa versión tiene que ser la que el bloque escribe.
    escritas = set()
    for linea in lineas:
        patron = _patron_de_sed(linea)
        sustitucion = _sustitucion_de_sed(linea)
        if "__version__" in patron:
            escritas |= _versiones(sustitucion)
    assert escritas, "No se ha podido sacar la versión que escribe el bloque"
    assert etiquetas == escritas, (
        f"La etiqueta ({etiquetas}) no es la versión que escribe el bloque ({escritas})."
    )
    assert __version__ not in etiquetas, (
        f"La etiqueta es la versión actual ({__version__}): ya está publicada."
    )
