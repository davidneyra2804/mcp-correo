---
name: Revisión
description: "Auditar una implementación antes de darla por buena. Úsala al terminar cualquier cambio de código, antes del commit y del push: lanza un subagente revisor con contexto fresco que comprueba el cambio contra las validaciones que este proyecto ya pagó, y verifica sus hallazgos antes de arreglarlos."
metadata:
  opencode/autoinvoke: true
---

# Revisión

Una implementación terminada no está buena hasta que alguien la mira con
la cabeza fría. Este es el paso que faltaba: un revisor con **contexto
limpio**, que no participó en la decisión, y una lista de
comprobaciones que sale de la historia del proyecto.

**Este skill no arregla nada.** El revisor informa; el agente principal
decide qué hacer con el informe. Un revisor que arregla se autoaproba.

## Cuándo

La revisión **no es opcional**. Al terminar una implementación, **antes**
del commit y del push, y también cuando el usuario pida una revisión, una
segunda opinión o una auditoría.

Lo único que se salta es lo que no toca comportamiento (un comentario, un
texto, un refactor sin efecto). Si toca el esquema de la base, la
configuración, la superficie de las tools o la seguridad, **no**.

## El presupuesto

**Una revisión, y tiene que salir en menos de 10 minutos.**

Esto no es arbitrario: las primeras revisiones tardaron entre 5 y 66
minutos, y el tiempo no se iba en revisar, se iba en **verificar de más**:
clonar, instalar un entorno de cero, construir arneses de pruebas de
mutación e investigar la plataforma. Todo eso lo hace mejor el agente
principal, en segundos.

De ahí las tres reglas, y no son negociables:

1. **El revisor no clona ni instala nada.** Trabaja en el árbol, que ya
   tiene el cambio y las dependencias. El prompt se lo dice.
2. **El agente principal hace las mutaciones.** Si el revisor dice que un
   test no vigila lo que dice vigilar, lo compruebas **tú**, revirtiendo
   el arreglo a mano. No le pidas que monte un arnés.
3. **El revisor no investiga la plataforma.** Lo que no sepa de
   OpenCode va a "Sin comprobar" y sigue.

Y el bucle: **una revisión, no un ciclo**. Si el revisor encuentra algo
crítico, lo arreglas y **decides tú** si mereces otra pasada. La
repetición es tuya, no automática: repetir sin criterio es lo que se
come el tiempo.

## El flujo

### 1. Prepara el alcance

El diff es lo que se revisa, y tiene que llegar completo al revisor,
**ficheros nuevos incluidos**:

```bash
git status --short          # 1. mira primero qué hay en el árbol
git add -A                  # 2. mete todo en el índice
# 3. QUITA del índice el trabajo a medias que no es de este cambio:
#    git restore --staged <fichero>
git diff --cached > /tmp/revision.diff   # 4. el diff, ya limpio
git log --oneline -5
```

El orden importa: `git restore --staged` va **antes** de escribir el
diff. Si lo desindexas después, el diff ya lo lleva (comprobado: el
fichero sigue en el diff).

`git add -A` deja el índice preparado (que es lo que hace falta para el
commit) y hace que el diff incluya lo que no estaba versionado. Un
revisor que no ve un fichero nuevo no puede revisarlo.

Ojo con el alcance: `git add -A` mete **todo** el árbol. Si hay trabajo
a medias que no es de este cambio (un `.env` sin ignorar, notas, un
fichero de depuración), entra en el diff y el revisor audita cosas que no
son del cambio. Mira el `git status` del paso 1 y quítalo del índice antes
de generar el diff.

**Si el diff sale vacío**, no hay nada sin commitear: el cambio ya está
en un commit, y lo que se revisa es ese commit. Pásale al revisor el
`git show <sha>` de ese commit en `{{DIFF}}` y el sha en `{{COMMITS}}`. En
ese caso, guarda también ese `git show` en `/tmp/revision.diff`: es el
mismo fichero que aplica el paso 5.

Si repitas la revisión, **vuelve a hacer este paso**: el diff se
regenera sobre el árbol ya corregido.

### 2. Corre las pruebas y prepasa el resultado

El revisor **no ejecuta nada**: no tiene shell. Una lista de comandos
permitidos no es defendible, porque cualquier subcomando con un
argumento de escritura la cuela (`ruff check --fix`,
`git diff --output=`, `pytest --junit-xml=`...). Y no lo necesita: tú le
pases la salida y él lee, razona y reporta.

Corre los tests y el lint **antes** de lanzarlo, y guárdalo:

```bash
{
  echo "== pytest =="
  .venv/bin/pytest -q -ra 2>&1
  echo "exit=$?"
  echo "== ruff format --check =="
  .venv/bin/ruff format --check . 2>&1
  echo "exit=$?"
  echo "== ruff check =="
  .venv/bin/ruff check . 2>&1
  echo "exit=$?"
} > /tmp/revision-tests.txt 2>&1
```

El `-ra` es para que aparezcan **qué** tests se saltaron y por qué: sin
eso, el revisor solo ve el recuento y no puede atribuirlos al cambio.

Ojo: `ruff format .` **reescribe** los ficheros y `ruff check` pasa
después. Para comprobar, el comando es `ruff format --check .`.

Si repites la revisión, **vuelve a hacer este paso**: la salida tiene
que ser la del código corregido.

### 3. Lanza al revisor

El revisor es un subagente con contexto fresco. El prompt completo está en
`references/auditoria.md`, **relativo al directorio base de esta skill**:
OpenCode inyecta esa ruta al cargar la skill, en una línea que empieza por
`Base directory for this skill:`. Léelo con la herramienta de lectura
(`read`), con esa ruta absoluta, y pásalo tal cual rellenando el alcance.

No uses una ruta fija desde la raíz del repo: la sesión puede estar
abierta en un subdirectorio, y ahí esa ruta no existe.

Lánzalo con el tool `subagent`:

- `agent`: `reviewer` (el agente del proyecto, `.opencode/agents/reviewer.md`).
  No tiene shell, no puede editar y no puede lanzar subagentes.
- `description`: `Auditar la implementación`
- `prompt`: el de `references/auditoria.md`, con los cinco marcadores
  rellenos: `{{REPOSITORIO}}`, `{{DIFF}}`, `{{ALCANCE}}`, `{{COMMITS}}` y
  `{{SALIDA_PRUEBAS}}` (el fichero del paso 2, con los tests y el lint).

  `{{DIFF}}` y `{{SALIDA_PRUEBAS}}` son **rutas de ficheros**, no su
  contenido: el revisor no tiene shell, así que solo puede leerlos con la
  herramienta de lectura.

Del modelo no te charges: lo fija el `reviewer` (MiniMax M3.1 Flash, que
es lo que pidió el usuario). Si el usuario pide otro modelo, pásalo en el
tool.

**El revisor no puede escribir en los ficheros del proyecto.** No tiene
shell, y la edición, la escritura, el parcheo, el lanzamiento de
subagentes y Code Mode están denegados. Por eso trabaja en tu árbol sin
riesgo: no puede aplicar un parche, revertir un fichero ni instalar
nada. Para leer ficheros usa la herramienta de lectura, que es la que
respeta la protección de los secretos.

(Ojo: las tools propias de OpenCode —crear un worktree, mover la
sesión— no pasan por esas denegaciones. No tocan los ficheros del
proyecto, pero conviene saberlo.)

### 4. Verifica los hallazgos

**No te creas al revisor.** Es otro modelo, con sus propios fallos: puede
inventar un problema que no existe, o quedarse corto. Cada hallazgo se
comprueba antes de actuar:

- Si dice que un test falla, **ejecútalo** y mira el fallo.
- Si dice que falta un `ALTER TABLE`, **mira el código** de la migración.
- Si dice que un test no vigila lo que dice vigilar, **revierte el arreglo
  tú** y mira si el test falla. Es un comando o dos; no hace falta un
  arnés.
Un hallazgo que no se puede reproducir no es un hallazgo: se descarta, y
se dice al usuario que se descartó. Los confirmados se arreglan.

### 5. Las dos comprobaciones que son tuyas

El revisor no hace estas dos, y el `AGENTS.md` las pide. Son las caras,
y las haces tú en segundos porque ya tienes el entorno:

**a. El clon limpio.** No lo pide el revisor (clonar e instalar un entorno
de cero es justo lo que costaba una hora). Lo haces tú, después de la
revisión.

**Primero, regenera el diff**: el del paso 1 es el de *antes* de los
arreglos, y el clon tiene que validar **el código que se va a
fusionar**. Con el diff viejo, el clon valida el código anterior y da
verde en falso.

```bash
git add -A
git diff --cached > /tmp/revision.diff
```

**El clon tiene que llevar el cambio**, y `git clone` sale del último
commit. Hay dos casos:

- El cambio **no** está commiteado (lo normal: la revisión es antes del
  commit). Se aplica el diff dentro del clon, con `--index` para que los
  ficheros nuevos queden versionados (si no, el detector de datos
  ficticios no los mira).
- El cambio **ya** está commiteado. El clon ya lo lleva: no se aplica
  nada.

Y el bloque **aborta si el `git apply` falla**, porque si no, los tests se
corren contra el código anterior y el control no vale:

```bash
set -e
TMP=$(mktemp -d); git clone . "$TMP/ci"; cd "$TMP/ci"
# Si el cambio no está commiteado, aplícalo (con --index).
# Si ya lo está, el clon lo lleva: no apliques nada.
git apply --index /tmp/revision.diff
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/ruff format --check . && .venv/bin/ruff check .
.venv/bin/pytest
PYTHONSAFEPATH=1 .venv/bin/pytest
```

Un "patch does not apply" significa que el clon ya lo llevaba, y un
"can't open" que el fichero del diff no está donde se cree. Los dos
casos hay que mirarlos, no pasarlos por alto.

**b. Que el test nuevo falla sin el arreglo.** Por cada test **nuevo** del
cambio, revierte **solo el arreglo**, dejando el test, y mira que el test
falla. Un test que no puede fallar no vigila nada, y el `AGENTS.md` lo
dice desde hace tiempo.

El fallo tiene que ser **una aserción dentro del test**: si sale un
`ImportError` o un `AttributeError`, el test no está midiendo lo que dice
medir, y da igual que "falle". Y si sale "no tests ran", es que
revertiste el test también, no el arreglo.

### 6. Decide si repites

**Una revisión no es un ciclo.** Si el revisor encontró algo crítico, lo
arreglas y decides:

- ¿El arreglo cambia el **comportamiento** o la **superficie**? Entonces
  sí, otra revisión (con el diff regenerado).
- ¿El arreglo es un ajuste de texto, un test o un detalle interno? No
  hace falta otra revisión: verifícalo tú con los tests.

La revisión repetida se paga, y se paga en el tiempo de quien espera. El
valor está en la **primera** pasada, que es la que mira el cambio con ojos
nuevos.

### 7. Informa

Di al usuario qué se revisó, qué encontró el revisor, qué era real y qué
no, y qué quedó sin comprobar. Si el revisor no pudo comprobar algo (por
ejemplo, no hay Docker en la máquina), dilo: **una revisión con huecos
dichos vale más que una que parece completa**.

## Lo que este skill no puede

- **No sustituye a las pruebas.** El revisor las lee, no las escribe. Si
  falta una validación, sigue faltando.
- **No arregla lo que no sabe.** El revisor ve el diff, no el problema
  entero. Los fallos de diseño se ven leyendo el código de alrededor.
- **No es independiente del modelo.** Si el revisor usa el mismo modelo
  que el agente principal, comparte los puntos ciegos. Lo que aporta es
  el contexto limpio, la lista de comprobaciones y la verificación
  mecánica: **es una red, no una garantía**.
- **No es una auditoría exhaustiva.** Con el presupuesto de 10 minutos, se
  busca lo grave: un CRÍTICO que rompe el despliegue, un fallo de
  seguridad, un test que no vigila. Los detalles menores se quedan sin
  mirar, y eso hay que decirlo.

## Nota sobre el informe

El informe lo escribe otro modelo, y puede salir con **palabras en inglés
coladas en el texto español**, o con destroces. Límpialo antes de
relatar: lo que se le entrega al usuario va en español y sin ruido.

Si el modelo es MiniMax, también puede emitir caracteres chinos (CJK). La
skill global `limpieza-cjk` los quita con un script; es opcional, y no
está en este repositorio, así que si no la tienes, quita a mano lo que
veas.
