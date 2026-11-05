"""El tema del panel: claro, oscuro y sistema.

El selector tiene tres opciones y la elección persiste tras recargar. En
«sistema» el panel sigue la apariencia del dispositivo, también en vivo:
si el sistema cambia de tema con el panel abierto, el panel se entera sin
recargar.

Aquí queda el contrato estructural —el JavaScript y el CSS que se sirven—
que corre en la suite normal. El comportamiento real en el navegador se
comprueba con Playwright contra el entorno de prueba.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "static" / "panel.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "static" / "panel.css").read_text(encoding="utf-8")
HTML = (ROOT / "dashboard" / "static" / "panel.html").read_text(encoding="utf-8")


def _bloque_tema() -> str:
    return JS[JS.index("const CLAVE_TEMA") : JS.index("/* --- arranque")]


def test_el_selector_ofrece_claro_oscuro_y_sistema() -> None:
    """Las tres opciones están en el HTML, con su nombre y su explicación."""
    for opcion in ("claro", "oscuro", "sistema"):
        assert f'data-tema-opcion="{opcion}"' in HTML
    assert "Ver el panel en claro" in HTML
    assert "Ver el panel en oscuro" in HTML
    assert "Seguir la apariencia del dispositivo" in HTML


def test_el_selector_marca_la_opcion_activa() -> None:
    """La opción activa se marca con `aria-pressed`, no solo con color."""
    bloque = _bloque_tema()
    assert 'boton.setAttribute("aria-pressed", activo ? "true" : "false")' in bloque
    assert "marcarTemaEnElSelector" in bloque


def test_el_tema_elegido_se_guarda_y_se_recupera() -> None:
    """La elección se guarda en `localStorage` y sobrevive a la recarga."""
    bloque = _bloque_tema()
    assert "window.localStorage.setItem(CLAVE_TEMA, tema)" in bloque
    assert "window.localStorage.getItem(CLAVE_TEMA)" in bloque


def test_el_tema_se_pone_antes_de_pintar() -> None:
    """El atributo se pone en la cabeza, para que no haya destello.

    Si el tema se aplicara al final, la página se pintaría primero con el
    oscuro y luego saltaría al elegido: un parpadeo que se nota.
    """
    cabeza = HTML[: HTML.index("</head>")]
    assert "mcp-correo-tema" in cabeza
    # El script en línea está en la cabeza, no al final del body.
    assert cabeza.index("mcp-correo-tema") < HTML.index("<body>")


def test_el_tema_sistema_no_pone_atributo() -> None:
    """En «sistema» no hay atributo: manda la media query del CSS.

    Si se pusiera `data-tema="claro"` al elegir «sistema», la media query
    no podría ganar y el panel dejaría de seguir al dispositivo.
    """
    bloque = _bloque_tema()
    assert 'raiz.removeAttribute("data-tema")' in bloque
    assert 'raiz.setAttribute("data-tema", tema)' in bloque


def test_el_panel_sigue_al_sistema_en_vivo() -> None:
    """Con «sistema», un cambio de apariencia del dispositivo se sigue."""
    bloque = _bloque_tema()
    assert 'window.matchMedia("(prefers-color-scheme: light)")' in bloque
    assert 'consulta.addEventListener("change", alCambiar)' in bloque
    assert 'if (temaGuardado() === "sistema") aplicarTema("sistema")' in bloque


def test_el_css_tiene_el_tema_claro() -> None:
    """El tema claro está definido, y es un bloque de verdad."""
    assert ':root[data-tema="claro"]' in CSS
    assert "color-scheme: light" in CSS
    # El claro tiene sus propios fondos y textos: no basta con invertir.
    claro = CSS[CSS.index(':root[data-tema="claro"]') :]
    claro = claro[: claro.index("/* El tema claro pedido por el sistema")]
    for variable in ("--fondo", "--fondo-1", "--texto", "--borde", "--acento"):
        assert f"{variable}:" in claro


def test_el_css_sigue_al_sistema_cuando_no_hay_elegido() -> None:
    """Sin elección, el panel se ve como el dispositivo manda."""
    assert "@media (prefers-color-scheme: light)" in CSS
    assert ":root:not([data-tema]):not(.tema-oscuro)" in CSS


def _sin_bloques_de_tema(css: str) -> str:
    """Quita los bloques donde se definen las variables del tema.

    Ahí los literales sí son el tema, y no hay nada que cambiar. Se corta
    por llaves, no por marcas de texto: así el test no depende de cómo
    esté redactado el comentario que separa los bloques.
    """
    from re import DOTALL, compile

    # Un bloque que empieza por uno de estos selectores, con su cuerpo.
    patron = compile(
        r"(?::root\s*\{|:root\[data-tema[^\{]*\{|@media\s*\(prefers-color-scheme[^\{]*\{)",
        DOTALL,
    )
    quitado = []
    cursor = 0
    while True:
        encontrado = patron.search(css, cursor)
        if encontrado is None:
            break
        inicio = encontrado.start()
        # Se busca la llave que cierra, contando las anidadas.
        nivel = 0
        fin = inicio
        for posicion, letra in enumerate(css[inicio:], inicio):
            if letra == "{":
                nivel += 1
            elif letra == "}":
                nivel -= 1
                if nivel == 0:
                    fin = posicion + 1
                    break
        quitado.append(css[inicio:fin])
        cursor = fin
    for bloque in quitado:
        css = css.replace(bloque, "")
    return css


def test_ningun_color_esta_escrito_a_pelo_fuera_de_las_variables() -> None:
    """Los colores del panel son variables, para que el tema los cambie.

    Si una regla escribe un color literal, ese color se queda en el tema
    oscuro cuando el panel va en claro: el texto se lee mal o el contraste
    se rompe. La única excepción es la impresión, que siempre es en blanco.
    """
    fuera = _sin_bloques_de_tema(CSS)

    # La impresión va en blanco, con independencia del tema.
    if "@media print" in fuera:
        fuera = fuera[: fuera.index("@media print")]

    literales = re.findall(r"#[0-9a-fA-F]{3,8}\b", fuera)
    assert not literales, f"colores escritos a palo fuera de las variables: {literales}"


def test_el_tema_no_altera_el_marcador_de_la_pagina() -> None:
    """El `theme-color` del navegador acompaña al tema.

    Es lo que se ve en la barra del navegador en el móvil: si se queda en
    el oscuro con el panel en claro, parece que la página va en oscuro.
    """
    assert 'name="theme-color"' in HTML
    bloque = _bloque_tema()
    assert "theme-color" in bloque
