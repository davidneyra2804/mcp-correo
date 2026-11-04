"""Contrato de accesibilidad del panel: acordeón, menú y retorno del foco.

Estas pruebas leen el JavaScript servido: comprueban que el patrón de
*menu button* y el retorno de foco no se deshacen al tocar el panel. El
comportamiento real se comprueba con Playwright contra el entorno de
prueba; aquí queda el contrato estructural, que corre en la suite normal.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "static" / "panel.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "static" / "panel.css").read_text(encoding="utf-8")


def test_las_acciones_del_dialogo_no_se_desalinean_con_el_boton_de_opciones() -> None:
    """El margen del menú del diálogo no puede alcanzar al botón «…».

    La clase `.menu` la usan dos cosas: el `<menu>` nativo del diálogo de
    edición y el botón de opciones que el JavaScript crea en cada
    dominio. Si la regla del diálogo sigue siendo `.menu`, su margen
    superior desalinea ese botón con «Añadir» y «Editar».
    """
    assert "dialog menu {" in CSS
    assert "\n.menu {" not in CSS


def test_el_boton_de_opciones_muestra_un_glifo_visible() -> None:
    """El botón «…» no puede quedarse vacío si la fuente no tiene el glifo.

    El punto medio matemático (`⋯`) no está en todas las fuentes de
    interfaz; la elipsis horizontal (`…`) sí.
    """
    assert 'disparador.textContent = "…"' in JS


def test_el_summary_del_acordeon_no_lleva_controles_interactivos() -> None:
    """El `summary` es un control: dentro solo puede haber texto."""
    bloque = JS[JS.index("function pintarDominio") : JS.index("function pintarCabeceraDominio")]
    assert 'document.createElement("summary")' in bloque
    assert "cabecera.append(pintarCabeceraDominio(dominio))" in bloque
    # Las acciones se construyen aparte, fuera del `details`.
    assert "caja.append(cabecera);" in bloque
    assert "contenedor.append(caja, acciones, cuerpo);" in bloque


def test_el_menu_declara_el_patron_aria_y_las_entradas_salen_del_orden_de_tab() -> None:
    bloque = JS[JS.index("function menuMasOpciones") : JS.index("function elementoMenu")]
    assert 'setAttribute("aria-haspopup", "menu")' in bloque
    assert 'setAttribute("aria-expanded", "false")' in bloque
    assert 'lista.setAttribute("role", "menu")' in bloque
    assert 'disparador.setAttribute("aria-controls", idLista)' in bloque
    assert "b.tabIndex = -1;" in JS


def test_el_menu_gestiona_el_teclado_y_restablece_aria_expanded() -> None:
    bloque = JS[JS.index("function menuMasOpciones") : JS.index("function elementoMenu")]
    for tecla in ('"ArrowDown"', '"ArrowUp"', '"Home"', '"End"', '"Escape"'):
        assert tecla in bloque, f"el menú no gestiona {tecla}"
    assert 'disparador.setAttribute("aria-expanded", "false")' in bloque
    # Al elegir una opción también se restablece, no solo con Escape.
    eleccion = JS[JS.index("function elementoMenu") : JS.index("/* Un único par de listeners")]
    assert 'disparador.setAttribute("aria-expanded", "false")' in eleccion
    assert "disparador.focus();" in eleccion


def test_el_dialogo_devuelve_el_foco_al_elemento_que_lo_abrio() -> None:
    bloque = JS[JS.index("function confirmar") : JS.index("/* --- pintado")]
    assert "const abridor = document.activeElement;" in bloque
    assert "if (abridor && document.contains(abridor)) abridor.focus();" in bloque


def test_los_listeners_globales_se_instalan_una_sola_vez() -> None:
    """Un par de listeners para todos los menús, no uno por menú."""
    bloque = JS[JS.index("function menuGlobal") : JS.index("/* --- el foco")]
    assert "if (menuGlobalInstalado) return;" in bloque
    assert "menuGlobalInstalado = true;" in bloque
    assert bloque.count('document.addEventListener("click"') == 1
    assert bloque.count('document.addEventListener("keydown"') == 1
    # El listener global se llama una vez al arrancar, no en cada pintado.
    assert JS.count("menuGlobal();") == 1
