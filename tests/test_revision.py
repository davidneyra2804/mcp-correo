"""La skill de revisión se vigila a sí misma.

Una skill que nadie comprueba se rompe sin que nadie se entere: un
marcador que no coincide, un fichero de referencia que se mueve, un
agente que se renombra. Eso pasa y no da ningún error visible: la
revisión deja de funcionar y nadie se da cuenta hasta que vuelve a
fallar algo que ya estaba pillado.

Estas pruebas comprueban que la skill y su agente siguen en pie:

- el frontmatter es válido y la skill se anuncia sola,
- los marcadores del prompt son los mismos que lista la skill,
- el fichero de referencia existe donde la skill dice,
- el agente revisor existe, no puede editar y tiene el modelo,
- la skill y el `AGENTS.md` no se contradicen,
- los ficheros no tienen texto pegado ni encabezados rotos.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".opencode" / "skills" / "revision"
SKILL = SKILL_DIR / "SKILL.md"
PROMPT = SKILL_DIR / "references" / "auditoria.md"
AGENTE = ROOT / ".opencode" / "agents" / "reviewer.md"

#: Los modelos que este proyecto usa. Si el revisor cambia de modelo, hay
#: que actualizar esta lista: un id mal escrito hace que el revisor no se
#: lance, y sin esto nadie se entera.
MODELOS_CONOCIDOS = frozenset(
    {
        "minimax/MiniMax-M3.1-Flash",
    }
)


def _frontmatter(fichero: Path) -> dict:
    """El frontmatter de un fichero, parseado como YAML.

    Se usa YAML de verdad, y no una regex: el frontmatter tiene que **ser**
    YAML válido, y un parser propio no lo comprueba. Un escalar plano con
    `": "` dentro no es YAML válido (aunque OpenCode lo tolere), y eso
    rompe cualquier otra herramienta que lo lea.
    """
    texto = fichero.read_text(encoding="utf-8")
    coincidencia = re.match(r"\A---\n(.*?)\n---\n", texto, re.DOTALL)
    assert coincidencia, f"{fichero.name} no empieza por un frontmatter bien formado"
    datos = yaml.safe_load(coincidencia.group(1))
    assert isinstance(datos, dict), f"{fichero.name}: el frontmatter no es un mapa"
    return datos


# --- la skill -------------------------------------------------------------------


def test_la_skill_existe_y_tiene_frontmatter() -> None:
    assert SKILL.is_file(), "La skill de revisión no está donde dice"
    datos = _frontmatter(SKILL)
    assert datos["name"]
    assert datos["description"], "Sin descripción, el modelo no la descubre"


def test_la_skill_se_anuncia_sola() -> None:
    """Sin `autoinvoke`, el modelo no la ve y no se llama sola."""
    datos = _frontmatter(SKILL)
    metadata = datos.get("metadata") or {}
    assert metadata.get("opencode/autoinvoke") is True, (
        "La skill no se anuncia sola: sin autoinvoke, el modelo no la ve."
    )


def test_el_id_de_la_skill_sale_de_la_ruta() -> None:
    """El ID es el de la ruta, no el del frontmatter.

    Si el directorio se renombra, el ID cambia, y el `AGENTS.md` (que la
    cita por su ID) se queda mirando a la nada. El ID se deriva **del
    disco**, no de una constante: comparar una constante consigo misma
    no vigila nada.
    """
    directorios = sorted(p.parent.name for p in ROOT.glob(".opencode/skills/*/SKILL.md"))
    assert "revision" in directorios, (
        f"La skill de revisión no está en .opencode/skills/revision/: {directorios}"
    )
    assert "revision" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_el_fichero_de_referencia_existe() -> None:
    """La skill manda leer una ruta: ese fichero tiene que estar.

    Se extrae la ruta **de la skill**, no se compara con una constante: si
    la skill pasa a decir otra cosa, el test tiene que fallar.
    """
    texto = SKILL.read_text(encoding="utf-8")
    rutas = set(re.findall(r"references/[\w.-]+\.md", texto))
    assert rutas, "La skill no dice dónde está el prompt del revisor"
    for ruta in rutas:
        assert (SKILL_DIR / ruta).is_file(), f"La skill apunta a {ruta} y no existe"
    assert (SKILL_DIR / "references" / "auditoria.md").is_file()


def test_los_marcadores_del_prompt_coinciden_con_los_de_la_skill() -> None:
    """Los cuatro marcadores tienen que estar en los dos sitios.

    Si la skill lista un marcador que el prompt no tiene, el prompt se
    lanza con un `{{...}}` sin rellenar. Y al revés.
    """
    texto_prompt = PROMPT.read_text(encoding="utf-8")
    texto_skill = SKILL.read_text(encoding="utf-8")
    marcadores_prompt = set(re.findall(r"\{\{([A-Z_]+)\}\}", texto_prompt))
    marcadores_skill = set(re.findall(r"`\{\{([A-Z_]+)\}\}`", texto_skill))
    assert marcadores_prompt, "El prompt no tiene marcadores"
    assert marcadores_prompt == marcadores_skill, (
        f"Los marcadores no coinciden: en el prompt {sorted(marcadores_prompt)}, "
        f"en la skill {sorted(marcadores_skill)}"
    )


# --- el agente ------------------------------------------------------------------


def test_el_agente_revisor_existe_y_no_puede_editar() -> None:
    """La garantía no puede depender solo del prompt.

    El agente builtin puede editar. Este no: la edición está denegada en
    su configuración, así que un revisor que se pasa de listo no puede
    tocar el árbol.
    Y se comprueba **la regla que gana**, no que haya un `deny` por ahí:
    las reglas se aplican en orden y gana la última que casa. Una regla
    `allow` detrás devolvería la edición, y una regla con action `*`
    también casa con la edición.
    """
    assert AGENTE.is_file(), "Falta el agente revisor"
    datos = _frontmatter(AGENTE)
    assert datos.get("mode") == "subagent", "El agente tiene que ser subagente"
    reglas = datos.get("permissions") or []
    assert isinstance(reglas, list) and reglas, "El agente no tiene permisos"
    # Las reglas que pueden tocar la edición: las de `edit` y las
    # comodín. Gana la última.
    que_casan = [
        regla
        for regla in reglas
        if str(regla.get("action")) == "edit" or str(regla.get("action")) == "*"
    ]
    assert que_casan, "No hay ninguna regla sobre la edición"
    ultima = que_casan[-1]
    assert ultima.get("effect") == "deny", (
        f"La última regla que toca la edición es {ultima!r}: con ella, el revisor puede editar."
    )


def test_el_agente_revisor_tiene_modelo() -> None:
    """El modelo se fija en el agente, no en la llamada.

    Así la skill no tiene que pasarlo, y el tool no se usa contra su
    contrato. Y el id tiene que existir: uno mal escrito hace que el
    revisor no arranque, y sin esto nadie se entera.
    """
    datos = _frontmatter(AGENTE)
    modelo = str(datos.get("model") or "")
    assert modelo, "El agente no fija modelo"
    assert "/" in modelo, f"El modelo tiene que ser provider/model: {modelo}"
    assert modelo in MODELOS_CONOCIDOS, (
        f"El modelo {modelo!r} no está en la lista de modelos conocidos "
        f"({sorted(MODELOS_CONOCIDOS)}). Si es a propósito, actualiza la lista."
    )


def test_el_agente_que_usa_la_skill_existe() -> None:
    """El nombre que la skill pasa al tool tiene que ser un agente real.

    Si la skill dice `reviewer` y el fichero se llama `revisor.md`, la
    llamada falla en tiempo de ejecución y la revisión no ocurre: sin
    este test, nadie se entera.
    """
    texto = SKILL.read_text(encoding="utf-8")
    coincidencia = re.search(r"`agent`:\s*`([\w-]+)`", texto)
    assert coincidencia, "La skill no dice qué agente lanza"
    nombre = coincidencia.group(1)
    assert (ROOT / ".opencode" / "agents" / f"{nombre}.md").is_file(), (
        f"La skill lanza el agente {nombre!r} y no existe .opencode/agents/{nombre}.md"
    )


# --- coherencia con el AGENTS.md ------------------------------------------------


def test_el_agents_md_exige_la_revision() -> None:
    """La regla tiene que estar en el `AGENTS.md`.

    Es el fichero que se inyecta en cada sesión: si la regla solo está en
    la skill, depende de que el modelo la descubra, y eso no es una
    garantía.
    """
    texto = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "revision" in texto, "El AGENTS.md no menciona la skill de revisión"
    assert "antes del commit" in texto, "El AGENTS.md no dice cuándo se pasa"


def _plano(texto: str) -> str:
    """El texto en una línea, con los espacios normalizados.

    Un salto de línea parte una frase en dos y la busca falla, aunque la
    frase esté ahí. Las comprobancias van sobre el texto plano.
    """
    return re.sub(r"\s+", " ", texto.lower())


def test_la_skill_y_el_agents_md_no_se_contradicen() -> None:
    """Los dos tienen que decir lo mismo de la obligatoriedad.

    Una dice "no es opcional" y la otra abre una escapatoria: el agente
    elige la que le conviene.

    Se comprueba con frases **negativas**, no con la presencia de una
    palabra: si el `AGENTS.md` deja de decir que es obligatoria, el test
    tiene que fallar. Con "aparece la palabra X" no se detecta.
    """
    skill = _plano(SKILL.read_text(encoding="utf-8"))
    agentes = _plano((ROOT / "AGENTS.md").read_text(encoding="utf-8"))
    # Los dos tienen que exigirla.
    assert "antes del commit" in skill
    assert "antes del commit" in agentes
    # Y los dos tienen que decir que no es opcional. Se busca la frase
    # entera, no la palabra "opcional": esta aparece con otros sentidos
    # (por ejemplo, una skill auxiliar que es opcional).
    for nombre, texto in (("la skill", skill), ("el AGENTS.md", agentes)):
        assert "no es opcional" in texto, f"{nombre} no dice que es obligatoria"
        for frase in ("la revisión es opcional", "puedes saltarte la revisión"):
            assert frase not in texto, f"{nombre} dice '{frase}': se contradice."
    # La excepción de lo trivial tiene que estar en los dos, y ser la misma.
    assert "un texto" in skill
    assert "un texto" in agentes


# --- el texto -------------------------------------------------------------------


def test_no_hay_encabezados_pegados_al_texto() -> None:
    """Un `##` pegado a una frase no es un encabezado.

    Markdown exige que el encabezado empiece al principio de la línea. Si
    no, la sección no existe en el árbol del documento y todo lo que
    cuelga de ella se queda dentro del párrafo anterior.
    """
    for fichero in (SKILL, PROMPT, AGENTE):
        for numero, linea in enumerate(fichero.read_text(encoding="utf-8").splitlines(), 1):
            if linea.startswith("#") or linea.startswith("    "):
                continue
            if re.search(r"\S#{1,6}\s", linea):
                raise AssertionError(
                    f"{fichero.name}:{numero}: encabezado pegado al texto: {linea!r}"
                )


def test_no_hay_palabras_en_ingles_coladas() -> None:
    """Cuatro palabras en inglés se colaron en el texto español.

    No es cosmético: dos estaban **dentro de las instrucciones** que el
    revisor debe seguir, así que las leía mal.

    Y el barrido es de todo lo que toca el cambio, no solo de los tres
    ficheros nuevos: un destroce en el CHANGELOG se cuela igual, y este
    mismo test lo caza.
    """
    prohibidas = ("participated", "finds", "Theoretical", "cateó", "queitersalió")
    for fichero in (
        SKILL,
        PROMPT,
        AGENTE,
        ROOT / "CHANGELOG.md",
        ROOT / "AGENTS.md",
        ROOT / "README.md",
    ):
        texto = fichero.read_text(encoding="utf-8")
        for palabra in prohibidas:
            assert palabra not in texto, f"{fichero.name}: '{palabra}' no es español"
