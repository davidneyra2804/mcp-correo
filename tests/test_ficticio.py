"""El repositorio es público: ningún dato real puede colarse.

Este repo se despliega con la configuración real de alguien. Si un dominio,
un correo o un hostname de una máquina real se cuelan en la documentación, en
los ejemplos o en los tests, se publica sin querer.

Estos tests lo impiden. Fallan si aparece algo que no sea de los dominios
reservados por la RFC 2606/6761 o de la lista corta de servicios públicos que
el proyecto menciona a propósito.

Las direcciones del propio repositorio (github.com, ghcr.io) no son datos
suyos: son la dirección del proyecto. Y no hay forma de que un repositorio
público no tenga dueño.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Dominios reservados para documentación. RFC 2606 y RFC 6761.
RESERVADOS_EXACTOS = frozenset(
    {"example.com", "example.org", "example.net", "example", "test", "invalid", "localhost"}
)
RESERVADOS_SUFIJOS = (
    ".example.com",
    ".example.org",
    ".example.net",
    ".example",
    ".test",
    ".invalid",
    ".localhost",
)

#: Servicios públicos que el proyecto menciona a propósito.
PERMITIDOS = frozenset(
    {
        "github.com",
        "ghcr.io",
        "modelcontextprotocol.io",
        "semver.org",
        "keepachangelog.com",
        "portainer.io",
        "developers.cloudflare.com",
        "jsonrpc.org",
        "opensource.org",
        "creativecommons.org",
        "ietf.org",
        "python.org",
        "pypi.org",
        "docker.io",
        "localhost",
        "ip6.me",
    }
)

#: Dominios que solo pueden aparecer como prefijo de subdominio.
SUFIJOS_PERMITIDOS = (
    "github.com",
    "githubusercontent.com",
    "githubassets.com",
)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
#: Dominio en minúsculas, con un TLD plausible. El filtro de TLD evita que
#: se cuelen rutas de Python como imaplib.IMAP4.error, ni nombres de fichero
#: como docker-compose.local.yml. La mirada negativa evita el acceso a
#: atributos de Python, que es lo más parecido a un dominio: logger.info(.
_DOMINIO = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|net|org|io|dev|app|cloud|me|info|biz|xyz|site|online|tech|co|uk|de|fr|it|nl|pt|br|ar|mx|cat|test|invalid|example|es|eu|ai)\b"
    r"(?!\s*\()"
)

#: Rastros personales que no deben aparecer en el árbol.
RASTROS_PERSONALES = (
    "gmail.com",
    "MacBook-Pro",
    "vyrtech",
)


def _ficheros_versionados() -> list[Path]:
    """Los ficheros que git sigue. Nada de .venv ni de ficheros sueltos."""
    listado = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [ROOT / nombre for nombre in listado if (ROOT / nombre).is_file()]


def _texto() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8", errors="ignore") for path in _ficheros_versionados()
    }


def _reservado(dominio: str) -> bool:
    return dominio in RESERVADOS_EXACTOS or any(
        dominio.endswith(sufijo) for sufijo in RESERVADOS_SUFIJOS
    )


def _sospechoso(dominio: str) -> bool:
    """¿Merece la pena mirar este dominio?

    Con tres etiquetas o más, casi siempre es un dominio de verdad. Con dos,
    el acceso a atributos de Python se parece mucho: self.app, logger.info.
    Ahí solo se mira si el nombre tiene guion o dígito, que es lo que
    distingue a los dominios de verdad de una coincidencia con una palabra.
    """
    etiquetas = dominio.split(".")
    if len(etiquetas) >= 3:
        return True
    nombre = etiquetas[0]
    return "-" in nombre or any(caracter.isdigit() for caracter in nombre)


def test_todo_correo_usa_un_dominio_reservado() -> None:
    """example.com y(example.org) están reservados para documentación."""
    malos: list[str] = []
    for path, text in _texto().items():
        for correo in _EMAIL.findall(text):
            dominio = correo.rsplit("@", 1)[1].lower()
            if not _reservado(dominio):
                malos.append(f"{path.relative_to(ROOT)}: {correo}")
    assert not malos, "Correos que no son de dominio reservado:\n  " + "\n  ".join(malos)


def test_todo_dominio_es_reservado_o_esta_permitido() -> None:
    """Ni un dominio real colado en la documentación."""
    malos: list[str] = []
    for path, text in _texto().items():
        for dominio in _DOMINIO.findall(text):
            dominio = dominio.lower()
            if _reservado(dominio) or dominio in PERMITIDOS:
                continue
            if any(dominio.endswith(f".{sufijo}") for sufijo in SUFIJOS_PERMITIDOS):
                continue
            if not _sospechoso(dominio):
                continue
            malos.append(f"{path.relative_to(ROOT)}: {dominio}")
    assert not malos, "Dominios que no son de documentación:\n  " + "\n  ".join(sorted(set(malos)))


def test_no_hay_rastros_personales_en_el_arbol() -> None:
    """Ni correos personales ni hostnames de máquinas."""
    malos: list[str] = []
    for path, text in _texto().items():
        for rastro in RASTROS_PERSONALES:
            if rastro in text:
                malos.append(f"{path.relative_to(ROOT)}: {rastro}")
    assert not malos, "Rastros personales:\n  " + "\n  ".join(malos)


@pytest.mark.parametrize(
    "fichero",
    ["README.md", "CHANGELOG.md", "docs/configuracion.md", "docs/despliegue-portainer.md"],
)
def test_la_documentacion_no_tiene_dominios_reales(fichero: str) -> None:
    """Los ficheros que más se leen, revisados a ojo por si acaso."""
    text = (ROOT / fichero).read_text(encoding="utf-8")
    for dominio in _DOMINIO.findall(text):
        dominio = dominio.lower()
        if _reservado(dominio) or dominio in PERMITIDOS:
            continue
        if any(dominio.endswith(f".{sufijo}") for sufijo in SUFIJOS_PERMITIDOS):
            continue
        if not _sospechoso(dominio):
            continue
        raise AssertionError(f"{fichero}: {dominio}")
