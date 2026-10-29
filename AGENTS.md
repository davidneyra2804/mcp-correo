# AGENTS.md

Directivas para trabajar en **mcp-correo**. Léelo antes de tocar nada.

## Qué es

Un servidor [MCP](https://modelcontextprotocol.io) que da a un asistente de
IA acceso a buzones IMAP/SMTP de terceros. El asistente **lee** libremente y
**escribe** solo con una orden explícita de quien lo opera, en dos pasos con un
`confirmation_id` de un solo uso.

El despliegue de referencia es **Portainer + Cloudflare Tunnel**, con toda la
configuración en variables de entorno.

```
Cliente MCP ──HTTPS──▶ Cloudflare ──▶ cloudflared ──▶ mcp-correo ──▶ IMAP/SMTP
```

## Las directivas

Estas no son preferencias. Cada una viene de un fallo real.

### 1. Todo por variables de entorno

El servidor se configura **entero** con variables `MCP_*`. No hay fichero de
configuración: no hay TOML, ni cuentas por variables, ni listas que mantener.

```
MCP_BEARER_TOKEN=el-secreto-del-cliente-mcp
MCP_DASHBOARD_KEY=la-clave-que-cifra-las-contrasenas
MCP_DASHBOARD_TOKEN=la-credencial-del-panel
```

**Las cuentas no van por el entorno.** Viven en la base de datos y las
gestiona el panel. No hay ninguna variable `MCP_ACCOUNT_*`: si alguna
volviera, el compose o el `.env.example` la documentarían y alguien creería
que configura una cuenta.

El panel y la base **siempre están**: es la forma de gestionar las
cuentas. `MCP_DASHBOARD_KEY` y `MCP_DASHBOARD_TOKEN` son obligatorias, y
si faltan el arranque para. La base tiene que vivir en un volumen: sin
volumen, el contenedor es de solo lectura y las cuentas se pierden en cada
reinicio.

### 2. Fallar pronto, y con un mensaje que diga qué hacer

Un valor mal escrito **aborta el arranque**. Nunca se ignora en silencio.

- Un interruptor solo admite `true`, `false`, `1` y `0`. `MCP_ENABLE_SEND=yes`
  no significa "apagado": significa error.
- Un límite de `0` es un error, no "sin definir": un `0` explícito tiene que
  llegar al validador y ser rechazado.
- Un salto de línea en un valor que acaba en una cabecera es un error.

El motivo es concreto: con un TOML, un error de sintaxis se ve al leer el
fichero. Con variables de entorno, un valor mal escrito se convierte en
"apagado" y el síntoma aparece semanas después, en forma de una tool que no
aparece. **Un error de configuración tiene que delatar la causa, aunque sea
incómodo.**

### 3. Una pregunta, un dueño

El mismo concepto no se implementa en dos sitios. Cuando un concepto se
repite, se extrae a un módulo y se importa.

Ejemplo: `write_capabilities` (qué tools se registran) y
`MailboxWriter._gated` (qué se puede hacer en cada operación) usan las
mismas reglas. Lo que no esté centralizado, se duplicará y divergirá.

### 4. Ningún dato real en el repositorio

Es público. Ni dominios, ni correos, ni hostnames de máquinas, ni IPs reales.

`tests/test_ficticio.py` lo comprueba en cada commit: correos de dominio no
reservado, dominios no reservados, y rastros personales. Los dominios de
ejemplo son `example.com`, `example.org`, `example.net` y `*.test`
(RFC 2606 y 6761).

Ha pillado fugas reales tres veces. **No lo relajes.**

### 5. La documentación dice lo que el código hace

Si el código cambia, la documentación cambia con él, y un test lo comprueba.
Hay tests que verifican que:

- el `.env.example` menciona todas las variables que el código conoce,
- el compose declara todas las variables fijas del servidor,
- `version.py`, `pyproject.toml` y la etiqueta de la imagen coinciden.

Un documento que miente es peor que ningún documento: alguien lo sigue y
pierde el tiempo.

Esto incluye la **documentación de las tools**: la descripción de cada tool
y la respuesta que devuelve son parte del contrato, no comentarios. Si una
tool cambia de nombre o de argumentos, el CHANGELOG lo dice y la sección de
despliegue avisa de lo que tiene que hacer el cliente.

### 6. Nada de secretos en la imagen ni en git

La imagen no lleva tokens ni contraseñas. Las cuentas se configuran por
entorno. `.env` está en `.gitignore`; lo que se versiona es `.env.example`,
con valores ficticios.

## Mapa del código

| Fichero | De qué se ocupa |
| --- | --- |
| `server.py` | `MCPServer`, el Bearer, el enrutado por cuenta, el registro de tools |
| `config.py` | Variables de entorno, capabilities, límites, validación |
| `scope.py` | El ámbito de la petición: qué cuentas puede tocar una llamada |
| `audit.py` | JSONL de cada llamada, sin cuerpos ni credenciales |
| `mail/imap.py` | Lectura (`EXAMINE`, `BODY.PEEK`) y el punto único de aislamiento |
| `mail/mutate.py` | Escritura: marcar, borrar, borrador, enviar |
| `mail/confirm.py` | `confirmation_id` de un solo uso y cupo diario, en memoria |
| `mail/compose.py` | Construcción del mensaje y escapado de cabeceras |
| `mail/readonly.py` | Proxy que bloquea la escritura en las rutas de lectura |
| `store/db.py` | La base de datos: esquema, migraciones, revisión |
| `store/crypto.py` | El cifrado de las contraseñas, con la clave fuera de la base |
| `store/store.py` | Las operaciones: dominios, cuentas y tokens |
| `store/accounts.py` | La fuente de cuentas: estática o de la base, con recarga |
| `store/direct_send.py` | La idempotencia del envío directo: claves y huellas, en la base |
| `dashboard/app.py` | El panel: rutas, sesión y anti-CSRF |
| `dashboard/api.py` | Los handlers del panel, incluida la prueba de conexión |
| `dashboard/ui.py` | La interfaz y el login |
| `docker/rotate_audit.py` | Rota el JSONL de auditoría |
| `docker/healthcheck.py` | La sonda: el MCP y, si está, el panel |
| `tests/ayuda.py` | Ajustes del servidor y cuentas de mentira para las pruebas |
| `tests/test_nombres_de_campos.py` | Los nombres de campo de la superficie MCP, que no pueden parecer credenciales |

## El modelo de rutas y permisos

**Rutas.** La ruta decide el ámbito; el Bearer decide la credencial.

| Ruta | Credencial | Ámbito |
| --- | --- | --- |
| `/mcp` | `MCP_BEARER_TOKEN` | la guía (el catálogo de rutas) y el dominio por defecto |
| `/mcp/<dominio>` | el global, o el del dominio | las cuentas de ese dominio |
| `/mcp/<cuenta>` | el global, el de la cuenta o el de su dominio | una cuenta |

`<cuenta>` puede ser el correo, el `NAME` de la cuenta o su índice.
`<dominio>` es el nombre del dominio. El bearer de una cuenta **solo**
vale en su ruta: en cualquier otra, 403. Y la ruta general es solo de la
credencial general: la de un dominio o la de una cuenta, ahí, responde 403.

El aislamiento se aplica en **un solo punto**: `MailService._account()`. El
ámbito viaja en un `ContextVar` (`scope.py`), porque las tools del SDK son
síncronas y se ejecutan en un hilo del pool.

**Permisos de escritura.** El global es el maestro y además el valor por
 defecto. Con el panel hay un nivel más: el dominio. El más específico
manda, y el que no dice nada hereda.

| Global | Del dominio | De la cuenta | Resultado |
| --- | --- | --- | --- |
| `false` | lo que sea | lo que sea | apagada |
| `true` | sin definir | sin definir | encendida (hereda) |
| `true` | sin definir | `true` | encendida |
| `true` | sin definir | `false` | apagada para esa cuenta |
| `true` | `false` | lo que sea | apagada en el dominio |

**El envío directo es una capacidad aparte**, con su propio interruptor
(`MCP_ENABLE_DIRECT_SEND`) y su propio permiso (`allow_direct_send`). No
hereda de `send`: una cuenta puede tener los dos o solo uno. En una cuenta
con envío directo, el MCP **no** exige confirmación por mensaje; la
autorización es la que se dio de antemano, y la idempotencia (en la base)
es lo que hace seguro el reintento.

## El flujo de trabajo

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

Sin red y sin buzón real: los tests llevan un doble de IMAP y otro de SMTP.

**Verifica en un clon limpio, no solo en tu `.venv`.** Local y CI no se
comportan igual, y la diferencia hay que buscarla:

```bash
TMP=$(mktemp -d); git clone . "$TMP/ci"; cd "$TMP/ci"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/ruff format --check . && .venv/bin/ruff check .
.venv/bin/pytest
PYTHONSAFEPATH=1 .venv/bin/pytest    # el entorno de Actions
```

**`ruff format --check`, no `ruff format`.** Para comprobar, es
`--check`: `ruff format` reescribe los ficheros y luego `ruff check`
pasa siempre, así que una violación de formato pasaría desapercibida y el
clon ya no sería lo que se iba a revisar.

**El clon tiene que ser un clon de verdad, con su `.git`.** Una copia con
`rsync` o `cp` no sirve: el detector de datos ficticios usa `git ls-files`,
y sin repositorio falla con `returned non-zero exit status 128` en vez de
comprobar nada. Si hay cambios sin commitear, hay que commitearlos antes:
el clon sale del último commit, no del directorio de trabajo.

Tres cosas que el clon limpio pilla y el directorio de trabajo no:

- Los ficheros **sin versionar** no los barre el detector de datos
  ficticios, que usa `git ls-files`.
- Las dependencias se instalan de verdad: tu `.venv` puede tener paquetes
  que `requirements.txt` ya no pide.
- `PYTHONSAFEPATH` (Actions) no añade el directorio de trabajo a
  `sys.path`, y los subprocesos que importan el proyecto dejan de
  encontrarlo. El fallo sale **solo en CI**, que es el peor sitio.

Y una regla de orden: **`ruff format` antes que `ruff check`**, y los dos
después de cada edición. Un cambio puede dejar líneas largas y hacer fallar
el linter donde antes pasaba.

Ojo con la diferencia: `ruff format` **reescribe**, `ruff format --check`
**comprueba**. Mientras se edita, se reescribe (que es lo que quiere: que
el código quede formateado). Para **verificar** que algo está formateado,
el comando es `--check`: con `format` primero, el linter pasa siempre y
el problema ya no está.

Antes de dar algo por bueno:

1. **Prueba la imagen, no solo el código.** `tests/test_docker.py` monta un
   directorio con lo que copia el Dockerfile y arranca el servidor desde ahí.
   Los tests locales pasan aunque a la imagen le falte un módulo.
2. **Piensa en la cuenta que lee un usuario nuevo.** ¿Qué variable falta? ¿El
   mensaje de arranque dice qué hacer?
3. **Si cambias una variable, `.env.example` y el compose.** Hay tests que lo
   comprueban, pero solo de los nombres: el valor por defecto también importa.
4. **Cada fallo que corrijas a mano, conviértelo en una regla.** Si lo
   encuentras revisando el diff, otro se tropezará con lo mismo, y
   probablemente tarde más en aparecer. Un test que falla es un fallo que no
   vuelve.
5. **La interfaz y la API no se pueden desincronizar.** `tests/test_interfaz_api.py`
   compara las llamadas del JavaScript con las rutas que declara la
   aplicación. Una ruta mal escrita no da error: el botón no hace nada.

## Trampas

Cada una de estas costó una release rota.

- **Un módulo que no llega a la imagen.** `scope.py` se quedó fuera del
  `COPY` del Dockerfile y el contenedor no arrancaba. Los tests locales pasaban
  porque corren desde el repo, donde el fichero sí está. La prueba que monta
  la imagen existe por esto.
- **Dos módulos con la misma regla y reglas distintas.** El entrypoint seguía
  mirando `MCP_ACCOUNTS` después de que el esquema pasara a discovery por
  índice. Hoy el entrypoint no existe: la configuración va entera por
  entorno, y las cuentas, por la base.
- **Un mensaje que lista lo que ya está puesto.** Decía *"marcado necesita
  `MCP_ENABLE_MARK=true` y `MCP_ACCOUNT_ALLOW_MARK_<N>=true`*" con la global
  ya en `true`, y hacía dudar de la que estaba bien. **Di solo lo que falta.**
- **`logout()` de imapclient ya cierra el socket.** Llamar a `shutdown()`
  después es un doble cierre que falla y ensucia el log en cada petición.
- **Un valor por defecto en la cuenta anula un global.** `MCP_SMTP_SECURITY`
  era código muerto porque la cuenta fijaba siempre el modo. Un default en la
  capa más específica puede anular el global que documentan.
- **El `Bcc` se quedaba en la copia de Enviados.** Lo que sale por SMTP no
  lleva `Bcc`; la copia que se guarda, sí. Quítalo antes del `APPEND`.
- **Un nombre visible en una cabecera.** Sin escapar, una coma parte la
  dirección en dos. Con un CRLF, se inyectan cabeceras. `formataddr` para
  lo primero, rechazo en la carga para lo segundo.
- **Un argumento obligatorio que la ruta ya determina.** `account` en las tools
  era obligatorio incluso en `/mcp/<cuenta>`, donde la ruta ya dice cuál es.
  El modelo tenía que adivinar la clave.
- **Un snapshot que se queda viejo.** El panel añade una cuenta y `/mcp` no la
  ve. El conjunto de cuentas no es un diccionario del arranque: es una
  **fuente** que se recarga, y la recarga se comprueba en cada petición
  (el contador de revisiones vive en la base). Si alguna vez se cachea sin
  invalidar, el síntoma es "el panel no hace nada".
- **Una credencial que cubre de más.** El aislamiento no mira los datos que
  devuelve la ruta, mira **el tipo de ruta**: la credencial de una cuenta no
  abre la ruta de un dominio, aunque ese dominio tenga una sola cuenta. Una
  regla que mire "las cuentas que quedan dentro" deja pasar a la credencial
  de una cuenta por la ruta de su dominio.
- **La ruta general como atajo a todo.** `/mcp` exponiendo todas las cuentas
  convierte al bearer general en un copymachine de buzones. Es la puerta de
  entrada: la guía, y el dominio por defecto si hay uno.
- **Dos fuentes de las cuentas a la vez.** La base de datos manda y las
  variables de entorno se ignoran. Mezclarlas es la forma segura de tener
  dos verdades, y de dos verdades sale una que nadie sabe cuál es. **En la
  v2 esto se resolvió quitando la segunda fuente**, no decidiendo cuál
  gana: la base es la única. Si algún día vuelve a haber dos, el síntoma
  es una tool que no aparece o una cuenta que cambia sola.
- **Una base de datos que no persiste.** Sin volumen, el contenedor es de
  solo lectura: o la base no se puede escribir, o se pierde en cada
  reinicio. La ruta tiene que caer en el volumen, y hay un test que lo
  comprueba.
- **Un fallo silencioso en la interfaz.** Una ruta mal escrita en el
  JavaScript, un botón sin acción, una etiqueta sin `for=`: nada falla y
  nada avisa. La página carga y la función no existe. Por eso
  `tests/test_interfaz_api.py` compara las dos capas.
- **El idioma del servidor no es el de quien lo usa.** El formulario pedía
  el mismo correo tres veces, porque el modelo de datos pide distinguir
  identificador de ruta, etiqueta y usuario de conexión. El modelo puede ser
  correcto y la interfaz, ilegible. Las excepciones van a "opciones
  avanzadas".
- **Editar no puede romper lo que ya funciona.** El alias de la ruta es el
  identificador en `/mcp`. Si al editar se sobrescribe con el correo, la
  ruta que ya tiene un cliente deja de existir, sin avisar.
- **Un `0` explícito no es "sin definir".** Al leer una variable de entorno
  con el patrón `int(valor) or 100`, un `0` se tomaba por "no definida" y
  caía al valor por defecto en silencio: un límite de `0` pasaba sin
  rechistar. Por eso existen `_env_int_or()` y `_env_float_or()`: distinguen
  "no definida" de un valor explícito, y el `0` llega al validador y se
  rechaza. **Un valor escrito a mano tiene que poder ser un error.**
- **`example.com`, nunca `ejemplo.com`.** Los dominios reservados son
  `example.com`, `example.org`, `example.net`, `*.test`, `*.invalid` y
  `*.localhost`. Esta confusión se coló dos veces.
- **Un nombre de campo puede hacer que el agente nunca reciba el valor.**
  Paperclip tapa por **nombre** los campos de una respuesta de tool que
  "parecen credenciales" (`token`, `secret`, `password`, `api_key`,
  `bearer`...), y **lo que entrega al modelo es el valor tapado**, no el
  original: su `validateToolContent` devuelve el resultado redactado. Con un
  campo llamado `confirm_token`, el agente recibía `***REDACTED***` en lugar
  del identificador y no podía completar el envío. El nombre del campo, no
  su valor, decide si se tapa. **Por eso el campo se llama
  `confirmation_id`, y su valor lleva un prefijo `cfm_`** que tampoco lo hace
  parecer una clave de proveedor. `tests/test_nombres_de_campos.py` lo fija:
  ningún nombre de la superficie MCP puede caer en un patrón de secreto, y
  el valor no puede tener la forma de una credencial conocida.
  El `confirmation_id` **no es una credencial**: sin el bearer de la cuenta no
  sirve de nada, solo vale para una operación, en una cuenta, y durante diez
  minutos.
- **La respuesta de una tool es un bloque de texto con JSON dentro.** La
  redacción de la plataforma también se aplica al texto, no solo a las claves:
  `"confirm_token": "..."` se sustituye dentro del bloque. Al comprobar si un
  valor sobrevive, hay que pasar la regex **por el texto de la respuesta**,
  no solo por las claves del objeto.
- **El cliente MCP cachea el catálogo de las tools.** Cambiar el nombre de un
  argumento rompe la primera llamada hasta que el cliente refresca el
  catálogo: manda el nombre viejo, el servidor lo rechaza con un error de
  validación, y el agente tiene que releer el esquema para salir del paso.
  Al cambiar el contrato de una tool, hay que **refrescar el catálogo en el
  cliente** y decirlo en el CHANGELOG, en la sección de despliegue.
- **Una respuesta sin identificadores no se puede comprobar.** `send_message`
  decía `sent: true` y `copy_in_sent: true`, pero sin `message_id` ni
  `sent_uid` no había forma de localizar la copia en Enviados: había que
  adivinar carpeta y criterio de búsqueda, y una búsqueda mal escrita daba
  cero resultados y parecía que la copia no estaba. **Toda operación que
  escriba algo que se pueda volver a leer devuelve cómo llegar a ello.**
- **Una tool que se llama una vez no puede depender de la segunda.** El
  flujo de dos pasos obligaba al agente a llevar un `confirmation_id` de
  una llamada a otra, y en Paperclip eso no ocurría: el agente llamaba una
  vez y la plataforma no le dejaba hacer la segunda. El **envío directo**
  (`send_message_direct`) resuelve eso: una llamada, sin confirmación por
  mensaje. Pero cambia el modelo de seguridad, así que es **opt-in**: su
  propio interruptor global (`MCP_ENABLE_DIRECT_SEND`), su propio permiso
  (`allow_direct_send`) y la idempotencia va en la base de datos, no en
  memoria. Un reintento tras un reinicio del servidor no puede duplicar el
  correo: si la clave viviera en memoria, el reinicio la borraría y el
  reintento enviaría otra vez.
- **Un nombre de argumento con `key` puede acabar tapado.** Paperclip
  redacta por nombre lo que parece una credencial, y `idempotency_key`
  lleva `key` dentro. El patrón de `tests/test_nombres_de_campos.py` no
  lo marca, pero el nombre es un contrato: el test fija que no cae en el
  patrón, y la auditoría lo redacta.
- **Un rechazo y una falta de respuesta no son lo mismo.** El SMTP puede
  rechazar el envío (el mensaje no salió) o dejar de responder (el mensaje
  **puede** haber salido). En el segundo caso, reenviar a ciegas duplica el
  correo. `mail/smtp_out.py` distingue los dos: un rechazo con respuesta
  (`SMTPRecipientsRefused`, `SMTPResponseException`) es un fallo y libera
  la clave de idempotencia; una excepción de red es `SmtpUncertain` y la
  clave queda reservada. **El doble de SMTP tiene que modelar el rechazo
  con la respuesta del servidor**, no con un `SMTPException` genérico: si
  el doble lanza la excepción genérica, el test dice "rechazó" cuando en
  realidad el código está viendo un envío incierto, y pasa por el motivo
  equivocado.
- **Una clave de idempotencia necesita una huella, no solo una clave.**
  La clave dice *qué* envío es; la huella dice *con qué contenido*. Sin
  la huella, un reintento con la misma clave pero con otro cuerpo se
  devolvería como "ya enviado" y el correo real no saldría nunca. Con la
  huella, la segunda llamada se rechaza por contenido distinto.
- **Una base de datos de pruebas se queda en el disco.** El `conftest.py`
  pone `MCP_DASHBOARD_DB` en el directorio temporal, y el fichero persiste
  entre ejecuciones. Al cambiar el **esquema** (una columna nueva, una
  tabla), la base vieja sigue ahí con la versión anterior y el arranque
  falla con `IndexError: No item with that key` al leer una fila: no es un
  fallo de la migración, es una base vieja que hay que borrar. Cuando
  cambia el esquema, hay que borrar la base de pruebas (o usar una base
  con nombre nuevo).
- **La versión del esquema se escribe siempre, no solo cuando falta.** La
  migración de la v1 a la v2 escribía `schema_version` solo si la fila no
  existía. Una base que migraba aplicaba los cambios pero **seguía
  marcando "1"**, así que la migración se volvía a aplicar en cada
  arranque. Solo se nota con una base que ya tiene la fila: por eso el
  test de migración tiene que **armar la base vieja a mano**, con sus
  cuentas dentro, y comprobar que después queda en la versión nueva. Un
  `prepare()` sobre una base recién creada no lo detecta: ahí la fila no
  existe y el `if` hace lo correcto.
- **Añadir una columna no es cambiar el `CREATE TABLE`.** El `CREATE TABLE`
  solo afecta a las bases **nuevas**. Una base que ya existe necesita un
  `ALTER TABLE`, y si la migración no lo hace, el servidor arranca y se
  cae al leer la primera fila: `IndexError: No item with that key`. Pasó
  con `allow_direct_send`: la columna se añadió al `_SCHEMA_V1` (que es
  el esquema de las bases nuevas) y la migración `_SCHEMA_V2` solo creaba
  la tabla `direct_sends`. **La v1 es histórica: no se toca.** Lo que se
  añade a una tabla existente va en la migración, con su `ALTER TABLE`.
- **El número de versión puede mentir.** Una migración que aplica los
  cambios y **después** falla deja la base con la versión nueva escrita y
  los cambios a medias. Una migración gateada por el número ("si la
  versión es menor que 2, migra") no la toca nunca más: parece al día y
  no lo está. Por eso la comprobación de columnas se hace **contra la
  tabla real** (`PRAGMA table_info`), no contra el número, y por eso
  tiene que ser **idempotente**: si la columna ya está, no se toca. El
  test que vigila esto arma una base "a medias" a mano: con la tabla
  nueva, la versión nueva y **sin** la columna.
- **Un test que recorre una lista vacía pasa siempre.** El doble de IMAP
  expone el esquema como `input_schema`, y el test leía `inputSchema`:
  `getattr` devolvía `None`, la lista quedaba vacía y el test pasaba sin
  mirar nada. **Un test que no puede fallar no vigila nada**: hay que
  comprobar que el esquema existe y que se han mirado nombres, y hay que
  comprobar que el test falla cuando se rompe lo que vigila (revertir el
  nombre y ver que falla).
- **El doble de IMAP tiene que saber lo que el código usa.** El criterio
  `HEADER Message-ID` no estaba simulado: el doble lo ignoraba y daba
  "coincide todo". Un test puede pasar **por el motivo equivocado** si el
  doble no modela lo que el servidor real modela.

## Publicar

La versión vive en `version.py`. Para subir una:

```bash
sed -i 's/__version__ = ".*"/__version__ = "2.2.0"/' version.py
sed -i 's/^version = ".*"/version = "2.2.0"/' pyproject.toml
sed -i 's/ARG MCP_VERSION=.*/ARG MCP_VERSION=2.2.0/' Dockerfile
sed -i 's/mcp-correo 2\.1\.0 |/mcp-correo 2.2.0 |/' docs/configuracion.md
sed -i 's|mcp-correo:2\.1\.0|mcp-correo:2.2.0|' README.md
git commit -am "version 2.2.0"
git tag v2.2.0 && git push origin v2.2.0
```

Los `sed` de la documentación no son opcionales: hay un test que
comprueba que la documentación no habla de una versión vieja. El patrón es
la versión **actual**, así que hay que cambiarlo en cada subida.

Cada `sed` tiene que tener **algo que sustituir**. La firma
`mcp-correo X.Y.Z |` solo está en `docs/configuracion.md`: si un `sed`
la busca en un fichero donde no existe, no cambia nada y parece que sí.

En macOS, `sed -i` necesita el sufijo vacío: `sed -i '' 's/.../.../'`. Sin
él, `sed` se come el script como si fuera un fichero y falla.

El ejemplo de arriba es el de la **próxima** versión: el patrón tiene que ser
la versión actual, o el `sed` no cambia nada y se publica una versión que
dice ser la anterior. Lo mismo en el README y aquí: **los dos bloques tienen
que apuntar al mismo número**. Si solo se actualiza uno, seguir el otro al
pie de la letra publica una versión anterior (o deja la documentación sin
cambiar).

La etiqueta dispara `.github/workflows/release.yml`, que pasa los tests,
publica la imagen en GHCR y crea el Release. **Si los tests fallan, la imagen
no se publica.** Así se detectó una fuga de correo real en el CHANGELOG: la
1.1.0 rota nunca llegó al registro.

El cuerpo del Release **sale del CHANGELOG**: un paso del workflow extrae la
sección de la versión y la compone con el bloque de la imagen. Las notas
automáticas de GitHub no bastaban: no recogían los cambios ni la advertencia
de que la imagen se publica sin probar en local. Si el CHANGELOG no tiene
sección para la versión, el paso avisa y sigue, porque la imagen ya está
publicada cuando llega y no debe ser él el que rompa.

La v2.0.1 se publicó así (2026-10-28): commit `bc2657b`, etiqueta `v2.0.1`,
imagen en `ghcr.io/davidneyra2804/mcp-correo:2.0.1` y `latest`. Se publicó
**sin Docker en la máquina**, así que la imagen no se ha arrancado ni probado
en local. La v2.0.0 se publicó así (2026-10-27): commit `d7ebf0c`, etiqueta
`v2.0.0`, imagen en `ghcr.io/davidneyra2804/mcp-correo:2.0.0` y `latest`. **La
imagen sale solo para `linux/amd64`**: el workflow no lleva `setup-qemu` ni
`platforms`, así que en un host arm64 hay que construirse en local o añadir
multi-arch al workflow.

### Lo que cuesta una release sin probarla

La imagen que sale de la etiqueta **no se ha arrancado en la máquina que la
publica**, y eso se repite porque la máquina de publicación no tiene Docker.
La red de seguridad es `tests/test_docker.py`, que simula el `COPY` del
Dockerfile y arranca el servidor desde esa copia: detecta los módulos que
no llegan a la imagen, pero **no** que la imagen construya, ni que los
permisos del contenedor sean correctos, ni que el volumen de datos funcione.

Cuando una release toca el **esquema de la base** (una tabla o una columna
nueva), esto pesa más: la migración se aplica al arrancar, y una base vieja
en el volumen `/var/lib/mcp-correo` tiene que migrar bien. La migración
está probada contra una base v1 en los tests, pero no contra una base real
de una instalación en marcha.

Por eso, antes de subir una versión que cambia el esquema, conviene
arrancar la imagen con un volumen que tenga una base de la versión
anterior y comprobar que la migración sale bien. Si no hay Docker en la
máquina, hay que decirlo en el commit y en el Release: es mejor que el
usuario lo sepa antes de redesplegar que descubrirlo con el contenedor
parado.

### Comprobar que la publicación salió bien

El workflow puede terminar en verde y la imagen no estar. Sin `gh` instalado,
se mira por la API:

```bash
# Los workflows de la etiqueta
curl -s "https://api.github.com/repos/<repo>/actions/runs?per_page=5" \
  | python3 -c "import json,sys; [print(r['name'], r['status'], r['conclusion']) for r in json.load(sys.stdin)['workflow_runs'][:5]]"

# El Release
curl -s "https://api.github.com/repos/<repo>/releases/tags/v2.0.0"

# Las etiquetas de imagen, con un token anónimo de solo lectura
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:<repo>:pull&service=ghcr.io" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://ghcr.io/v2/<repo>/tags/list"

# La etiqueta OCI de versión, leyendo el manifiesto publicado
curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  "https://ghcr.io/v2/<repo>/manifests/2.0.0"
```

Esto último es lo que garantiza que la imagen publicada lleva la versión
correcta: `org.opencontainers.image.version` tiene que coincidir con
`version.py`, y el `entrypoint` tiene que ser el actual. El manifiesto es un
índice multi-arch: hay que bajar al manifiesto de `linux/amd64`, sacar su
`config.digest` y leer **ese** blob. El `entrypoint` va en `config.Entrypoint`,
no en las etiquetas.

Sin `gh` no se puede editar un Release: para cambiar sus notas hay que
re-ejecutar la etiqueta (`git tag -f` y `git push --force origin vX.Y.Z`), que
vuelve a publicar la imagen. Por eso el cuerpo se compone en el workflow y no
a mano.

## La revisión

**Al terminar una implementación, antes del commit y del push, hay que
pasar la skill `revision`.** No es opcional, y no es "si te acuerdas": la
regla está aquí porque este fichero se inyecta en cada sesión. Lo único
que se salta es lo que no toca comportamiento (un texto, un comentario).

Por qué existe: el error del `ALTER TABLE` que faltó en la migración, y
el clon limpio que no se llegó a hacer, eran **validaciones que este
propio fichero ya pedía**. El fallo no fue no saber la regla: fue no
ejecutarla. Un revisor con contexto fresco y una lista de comprobaciones
es una red que atrapa eso.

La skill hace cinco cosas:

1. Prepara el diff completo (`git add -A` y `git diff --cached`), para
   que el revisor vea también los ficheros nuevos.
2. Lanza un subagente revisor, con contexto limpio, que trabaja en un
   **clon aparte** y comprueba el cambio ejecutando, no opinando.
3. Obliga a **verificar los hallazgos** antes de arreglarlos.
4. Repite la revisión si el arreglo cambió el código.
5. Obliga a **informar**: qué se revisó, qué era real y qué quedó sin
   comprobar.

Lo que **no** es la revisión: no sustituye a las pruebas, no arregla lo
que no sabe, y no es independiente del modelo (si el revisor usa el mismo
modelo, comparte los puntos ciegos). Es una red, no una garantía.

## Antes de fusionar a `main`

- [ ] La revisión de la skill `revision` está pasada, y sus hallazgos
      reales están corregidos.
- [ ] Los tests pasan en local **y** en un clon limpio.
- [ ] La imagen arranca: `docker compose -f docker-compose.yml -f docker-compose.local.yml up --build`.
- [ ] La prueba de humo pasa: `python herramientas/humo.py`.
- [ ] La documentación coincide con el código.
- [ ] Ningún dato real en el árbol.
- [ ] Si cambia el contrato de configuración, `.env.example`, el compose y
      `docs/configuracion.md` actualizados, con el CHANGELOG al día.
- [ ] Si cambia el **nombre** de un argumento o de una clave de la respuesta,
      está dicho en el CHANGELOG, en la sección de despliegue, porque el
      cliente cachea el catálogo y hay que refrescarlo.
- [ ] Si cambian las rutas, el `deploy/nginx-mcp.conf` las sigue: con
      `location = /mcp` (coincidencia exacta) las rutas por cuenta y por
      dominio dan 404.
- [ ] Si el panel cambia, `docs/dashboard.md` y el README cuentan el flujo
      nuevo.
- [ ] Si cambia el **esquema de la base**, la migración está probada desde
      la versión anterior, y el arranque con una base vieja no se rompe.
- [ ] Si la migración añade una **columna**, tiene su `ALTER TABLE`: el
      `CREATE TABLE` solo vale para las bases nuevas.

**Si no hay Docker en la máquina, dilo en el commit y en el Release.** La
prueba que simula el `COPY` del Dockerfile y arranca el servidor desde esa
copia (`tests/test_docker.py`) detecta los módulos que no llegan a la
imagen, pero **no** que la imagen construya, ni que los permisos del
contenador sean los correctos, ni que el volumen de datos funcione. Es una
red de seguridad, no una prueba de la imagen.

## Lo que está pendiente

- **Multi-arch.** La imagen sale solo para `linux/amd64`. En un host arm64 hay
  que construirla en local o añadir `setup-qemu` y `platforms` al workflow.
