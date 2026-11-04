# Validación visual — VYRA-25

## Hallazgos y cambios

- Captura original de la tarea madre: el dominio principal quedaba después del secundario. El render ordena ahora primero el dominio marcado `default`; al cambiarlo y recargar, el nuevo principal permanece primero.
- Captura original de la tarea madre: el menú de opciones quedaba recortado o se superponía al contenido. El fixture actualizado muestra el menú fuera del recorte y sin tapar los controles de la fila.
- Captura de revisión de VYRA-25: «Añadir cuenta», «Editar» y «…» estaban a distinta altura. El margen de `1.2rem` destinado al elemento nativo `<menu>` del diálogo también alcanzaba los botones con clase `.menu`. Se limitó esa regla a `dialog menu`; Playwright midió centros verticales idénticos para los tres controles en escritorio y móvil.
- La inspección por visión mostró también que el carácter matemático `⋯` no se veía en la fuente del entorno. Se reemplazó por la elipsis horizontal `…`, que aparece en las capturas posteriores.

## Verificación

- Navegador: Chromium headless con Playwright, viewport escritorio `1440×1000` y móvil `390×844`.
- La página ejecutada contiene el HTML, CSS y JavaScript reales de la rama VYRA-25. Las rutas API se interceptaron dentro del navegador y respondieron con fixture ficticio (`vyrts.com` principal y `vyrgs.com` secundario); no se conectó a backend ni a datos reales.
- Playwright comprobó modos claro/oscuro/sistema, persistencia al recargar, seguimiento en vivo de `prefers-color-scheme`, orden inicial y tras cambiar el principal/recargar, apertura de opciones con Enter, cierre con Escape y retorno del foco, nombre accesible, foco visible y ausencia de errores de JavaScript.
- Medida de los centros verticales de «Añadir cuenta», «Editar» y «…»: escritorio `520.6 px` en los tres controles (dispersión `0 px`); móvil `708 px` en los tres (dispersión `0 px`). El botón de opciones mide `44×44 px` y el foco visible tiene contorno de `2 px`.
- Inspección visual de capturas posterior a los cambios: texto legible en temas claro y oscuro; controles alineados; sin solapamiento de la fila en los dos viewports.
- Pruebas del repositorio en el clon aislado de VYRA-25: `295 passed` (`/tmp/vyra25-pyenv/bin/pytest -q`). `git diff --check` sin errores.

## Capturas posteriores

Se adjuntan al issue cuatro capturas tomadas en Chromium: escritorio claro/oscuro y móvil claro/oscuro. La captura reportada por el usuario sigue adjunta al comentario original para comparación.

## Límites y riesgo residual

La API fue simulada con fixture: estas pruebas no verifican persistencia de datos ni cambios de backend. La inspección cubre los viewports indicados, no todas las escalas, navegadores o tecnologías de asistencia.

## Integración en la rama de Orión

El commit `3049666d27cae6f5c5c70ca6d444252186ed1fe9` se integró en `feat/panel-modo-oscuro-acordeon` (ver [VYRA-26](/VYRA/issues/VYRA-26)). El parche se aplicó sobre esa rama: la regla del diálogo pasó de `.menu` a `dialog menu` y el botón de opciones pasó de `⋯` a `…`.

Las dos aserciones del contrato de accesibilidad se añadieron a `tests/test_accesibilidad_panel.py`, el archivo que en esta rama recoge el contrato estructural de CSS y JavaScript del panel. En el clon aislado de VYRA-25 no existía ese archivo y las aserciones iban en `tests/test_interfaz.py`.

La rama queda integrada y sin desplegar: no se ha construido ni publicado ninguna imagen, ni se ha tocado backend, API ni datos.
