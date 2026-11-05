# Validación visual — VYRA-34

El token efectivo y el tema claro/oscuro/sistema en los botones de copiar
la URL del MCP y el token de cada cuenta.

## Lo que había

La base de este trabajo es VYRA-32 (`4992f46`), que ya traía los dos
botones de copiar. Dos cosas faltaban, y ninguna era «retocar»:

**El token efectivo.** VYRA-32 leía `cuenta.bearer` y nada más. Una cuenta
sin credencial propia devolvía el token vacío, así que el botón no podía
copiar nada. El texto de la interfaz («esta cuenta no tiene token propio:
usa el de su dominio») describía un comportamiento que el backend no
cumplía.

**El tema.** El panel era de modo oscuro único: `:root` declaraba
`color-scheme: dark` y no había ni selector ni `prefers-color-scheme`.

## El hallazgo sobre VYRA-25

El encargo parte de que VYRA-25 ya implementó claro/oscuro/sistema en
`feat/panel-modo-oscuro-acordeon`, commit `867637a`. **Ese commit no
contiene el tema.** Es el arreglo de alineación de acciones y visibilidad
del menú: cuatro ficheros, `panel.css` (+5 −1), `panel.js`, un documento y
un fichero de pruebas.

El trabajo de tema de VYRA-25 estaba en otro commit, `869a460`, en la rama
aislada `work/VYRA-25` de Atenea. Ese commit **no llegó a `main`**:
VYRA-26 integró solo el parche de `3049666` (la alineación del menú) y
VYRA-28 mergeó `867637a`.

Comprobado en el repositorio, no supuesto:

```
git log --all -S "prefers-color-scheme" -- dashboard/static/panel.css   # sin resultados
git show main:dashboard/static/panel.css | grep color-scheme             # solo "dark"
```

Es decir: **no había ningún soporte de tema que reutilizar**. La tarea dice
«reutiliza solo el selector/persistencia y estilos de temas requeridos»
suponiendo que existen; no existían, y hay que implementarlos. Por eso el
«antes» solo tiene capturas en oscuro: ese panel no se podía ver en claro,
y no se ha inventado una captura «antes claro».

## Lo implementado

### El tema

- **Selector** en la cabecera: Claro / Oscuro / Sistema, con `aria-pressed`
  para decir cuál está activo.
- **Persistencia** en `localStorage` (`mcp-correo-tema`). El atributo se
  aplica en la cabeza del HTML, antes de pintar, para que no haya un
  destello del tema equivocado.
- **«Sistema»** no pone atributo: manda la media query. El panel sigue al
  dispositivo **en vivo**, con el listener de `change` de `matchMedia`.
- Los colores que dependían del tema estaban escritos a pelo en 17 reglas.
  Ahora son variables (`--texto-acento`, `--borde-ok`, `--cabecera-fondo`,
  `--degradado-bienvenida`…), así que los dos temas solo se diferencian en
  los valores de `:root`. Un test lo vigila: ningún color literal puede
  quedar fuera de las variables (la impresión, que siempre va en blanco, es
  la única excepción).
- El `theme-color` del navegador acompaña al tema: es lo que se ve en la
  barra del navegador en el móvil.

No se ha tocado el menú ni el orden de dominios: lo arregló VYRA-25 y está
aceptado.

### El token efectivo

Con la entrega de VYRA-33 (Apolo), la ruta devuelve el token **efectivo**:
el propio de la cuenta, o el de su dominio, y `origen` dice de cuál.

- La interfaz **distingue los tres casos**: `cuenta` (token propio),
  `dominio` (heredado) y `general` (no hay ninguno que copiar).
- Una etiqueta en la fila dice «Token del dominio» cuando el token es
  heredado, y «Solo con el token general» cuando no hay token que copiar.
  Solo aparece cuando hay algo que aclarar: una cuenta con su propio token
  deja la fila limpia.
- El texto de error es el verdadero. El anterior («usa el de su dominio»)
  era falso con el backend nuevo: el token del dominio **sí** se copia.
  El caso `general` se dice con honestidad en vez de prometer una copia que
  no va a funcionar.
- El `title` y el `aria-label` del botón explican de dónde sale el token de
  esa cuenta, antes de que se pulse nada.

### Un fallo encontrado de paso

Cada botón programaba su vuelta al estado normal con su propio
`setTimeout`, sin cancelar el anterior. Copiar dos veces seguidas hacía
que el temporizador de la primera copia **borrara la confirmación de la
segunda**: el botón volvía a su texto original mientras la segunda copia
sí se había hecho. El usuario veía que no se había copiado, y lo que se
había copiado era lo correcto. Ahora cada botón guarda su temporizador y
cancela el anterior.

## Verificación

### Pruebas

- `pytest`: **358 pasan** (301 antes de VYRA-32, más 57 de este trabajo).
- `ruff check`: sin hallazgos. `ruff format --check`: 81 ficheros, todos
  con el formato.
- **Clon limpio** con su propio entorno: 358 pasan, y también con
  `PYTHONSAFEPATH=1` (el entorno de Actions, donde los fallos de importación
  solo salen en CI).

### Navegador real

Chromium con Playwright, con el panel de verdad levantado sobre una base
ficticia. Viewport de escritorio `1440×1000` y de móvil `390×844`.

| Comprobación | Resultado |
|---|---|
| El panel carga y pinta las cuentas | ok |
| Fondo oscuro por defecto | `rgb(12, 16, 23)` |
| Tres opciones de tema, «sistema» marcado | ok |
| El fondo claro es distinto del oscuro | `rgb(244, 246, 251)` |
| La elección persiste tras recargar | ok |
| Copiar el token: el portapapeles tiene el token de la cuenta | ok |
| Copiar la URL: el portapapeles tiene la URL completa | `https://mcp.example.com/mcp/ada@corp.example.com` |
| **Cuenta sin token propio: se copia el token del dominio** | `token-del-dominio-0123456789abcdef` |
| La fila dice «Token del dominio» | ok |
| Una cuenta con token propio no lleva etiqueta | ok |
| **Cuenta sin ningún token: la fila avisa, y no dice «Copiado»** | ok |
| El aviso dice que solo se abre con el token general | ok |
| El portapapeles no se ha tocado en ese caso | ok |
| El botón de copiar se alcanza con el Tab | ok |
| Foco visible con el teclado | ok |
| Con Enter también copia | ok |
| **Fallo del portapapeles: no dice «Copiado», avisa y enseña el valor** | ok |
| El aviso es `role="status"` y `aria-live="polite"` | ok |
| En «sistema» no hay atributo y manda el dispositivo | ok |
| El panel sigue al dispositivo **en vivo**, sin recargar | ok |
| Con un tema elegido a mano, el dispositivo ya no manda | ok |
| Errores de JavaScript en la consola | ninguno |

La cuenta sin token propio se comprobó **contra el servidor MCP de verdad**:
el token que devuelve el panel es el que `BearerAuth._permite` acepta para
abrir esa ruta. No basta con que el token se devuelva.

## Capturas

En `docs/capturas-vyra34/`:

**Antes** (base `4992f46`, modo oscuro único — no existe un «antes en
claro» porque ese panel no se podía ver en claro):
- `vyra34-antes-oscuro-escritorio.png`
- `vyra34-antes-oscuro-movil.png`

**Después:**
- `vyra34-claro-escritorio.png`
- `vyra34-claro-movil.png`
- `vyra34-oscuro-escritorio.png`
- `vyra34-oscuro-movil.png`

**Estado «Copiado»:**
- `vyra34-copiado-claro-escritorio.png`
- `vyra34-copiado-oscuro-escritorio.png`

Todas las capturas se revisaron con visión: el texto se lee en los dos
temas, los botones no se desbordan en móvil y los dos badges de origen se
distinguen.

## Límites y riesgo residual

- **No se ha hecho push, ni PR, ni merge, ni despliegue.** La rama es local.
- **La ruta devuelve el token en claro** a quien tenga sesión del panel. Es
  lo que aceptó David en VYRA-32 y lo que pedía el encargo, y el token ya
  se guardaba en claro en la base (la contraseña sigue cifrada con
  `MCP_DASHBOARD_KEY`). Si el modelo de seguridad cambia en el futuro
  (tokens con hash), esa ruta deja de poder existir sin revisar el diseño.
- **El fallo del portapapeles enseña el token en la propia página**, que es
  lo que pedía el requisito como alternativa. En un ordenador compartido
  eso deja el token a la vista; es un riesgo aceptado por el requisito.
- **No se ha comprobado la imagen de Docker**: no hay Docker en esta
  máquina. No hay módulos nuevos de Python más allá de `rutas.py` (que ya
  traía VYRA-32) ni dependencias nuevas — `requirements.txt` y
  `requirements-dev.txt` no cambian — así que el `COPY` del `Dockerfile`
  solo añade `rutas.py`, que sin él la imagen arrancaría sin ese módulo.
  El cambio no se ha construido ni ejecutado en Docker.
- La validación de navegador cubre Chromium, y los dos viewports
  indicados. No cubre otros navegadores, otras escalas ni otras tecnologías
  de asistencia.
- El backend de VYRA-33 se ha integrado **tal como lo entregó Apolo**
  (commit `a82f074` en su rama). La revisión de código de esa parte es de
  Apolo; aquí se ha comprobado que la interfaz consume bien lo que expone.
