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
`git show <sha>` de ese commit en `{{DIFF}}`, el sha en `{{COMMITS}}`, y
**dile que el clon ya lo contiene**: el parche viene ya aplicado y no hay
que aplicarlo otra vez.

Cada vez que repitas la revisión (paso 4), **vuelve a hacer este paso**: el
diff se regenera sobre el árbol ya corregido.

### 2. Lanza al revisor

El revisor es un subagente con contexto fresco. El prompt completo está en
`references/auditoria.md`, **relativo al directorio base de esta skill**:
OpenCode inyecta esa ruta al cargar la skill, en una línea que empieza por
`Base directory for this skill:`. Léelo con la herramienta de lectura
(`read`), con esa ruta absoluta, y pásalo tal cual rellenando el alcance.

No uses una ruta fija desde la raíz del repo: la sesión puede estar
abierta en un subdirectorio, y ahí esa ruta no existe.

Lánzalo con el tool `subagent`:

- `agent`: `reviewer` (el agente del proyecto, `.opencode/agents/reviewer.md`).
  Tiene la edición **denegada** y el modelo ya configurado.
- `description`: `Auditar la implementación`
- `prompt`: el de `references/auditoria.md`, con los cuatro marcadores
  rellenos: `{{REPOSITORIO}}`, `{{DIFF}}`, `{{ALCANCE}}` y `{{COMMITS}}`.

Del modelo no te charges: lo fija el `reviewer` (MiniMax M3.1 Flash, que
es lo que pidió el usuario). Si el usuario pide otro modelo, pásalo en el
tool.

El revisor trabaja en un **clon aparte**, no en tu árbol. Por eso no
puede romper nada de lo que tienes a medias.

### 3. Verifica los hallazgos

**No te creas al revisor.** Es otro modelo, con sus propios fallos: puede
inventar un problema que no existe, o quedarse corto. Cada hallazgo se
comprueba antes de actuar:

- Si dice que un test falla, **ejecútalo** y mira el fallo.
- Si dice que falta un `ALTER TABLE`, **mira el código** de la migración.
- Si dice que el diff no aplica, **aplica el diff** y mira.

Un hallazgo que no se puede reproducir no es un hallazgo: se descarta, y
se dice al usuario que se descartó. Los confirmados se arreglan.

### 4. Repite si hubo arreglos

Si el revisor encuentra algo y lo arreglas, el cambio ya no es el que se
revisó: **vuelve a lanzar la revisión**. Una revisión que no cubre el
arreglo no cubre nada. Y vuelve a preparar el diff (paso 1): el diff
anterior ya no sirve.

### 5. Informa

Di al usuario qué se revisó, qué encontró el revisor, qué era real y qué
no, y qué quedó sin comprobar. Si el revisor no pudo comprobar algo (por
ejemplo, no hay Docker en la máquina), dilo: **una revisión con huecos
dichos vale más que una que parece completa**.

## Lo que este skill no puede

- **No sustituye a las pruebas.** El revisor las ejecuta, no las
  escribe. Si falta una validación, sigue faltando.
- **No arregla lo que no sabe.** El revisor ve el diff, no el problema
  entero. Los fallos de diseño se ven leyendo el código de alrededor.
- **No es independiente del modelo.** Si el revisor usa el mismo modelo
  que el agente principal, comparte los puntos ciegos. Lo que aporta es
  el contexto limpio, la lista de comprobaciones y la verificación
  mecánica: **es una red, no una garantía**.

## Nota sobre el informe

El informe lo escribe otro modelo, y puede salir con **palabras en inglés
coladas en el texto español**, o con destroces. Límpialo antes de
relatar: lo que se le entrega al usuario va en español y sin ruido.

Si el modelo es MiniMax, también puede emitir caracteres chinos (CJK). La
skill global `limpieza-cjk` los quita con un script; es opcional, y no
está en este repositorio, así que si no la tienes, quita a mano lo que
veas.
