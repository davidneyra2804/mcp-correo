# AGENTS.md

Directivas para trabajar en **mcp-correo**. Léelo antes de tocar nada.

## Qué es

Un servidor [MCP](https://modelcontextprotocol.io) que da a un asistente de
IA acceso a buzones IMAP/SMTP de terceros. El asistente **lee** libremente y
**escribe** solo con una orden explícita de quien lo opera, en dos pasos con un
token de un solo uso.

El despliegue de referencia es **Portainer + Cloudflare Tunnel**, con toda la
configuración en variables de entorno.

```
Cliente MCP ──HTTPS──▶ Cloudflare ──▶ cloudflared ──▶ mcp-correo ──▶ IMAP/SMTP
```

## Las directivas

Estas no son preferencias. Cada una viene de un fallo real.

### 1. Todo por variables de entorno

El servidor se configura **entero** con variables `MCP_*`. Un fichero de
configuración es la alternativa legacy (`accounts.toml`), no el camino normal.

Una variable por campo, con el índice de la cuenta al final:

```
MCP_ACCOUNT_USERNAME_1=ada@corp.example.com
MCP_ACCOUNT_INBOX_HOST_1=imap.corp.example.com
MCP_ACCOUNT_PASSWORD_1=la-clave
```

Para añadir una cuenta: copias el bloque y cambias el número. No hay listas
que mantener, ni variables que enumerar en el compose.

**Las cuentas no van por el entorno.** Viven en la base de datos y las
gestiona el panel. Las del entorno se importan **una sola vez**, y solo si
la base está vacía. A partir de ahí la base manda, y las variables de
cuenta ya no se leen.

El panel y la base **siempre están**: es la forma de gestionar las
cuentas. `MCP_DASHBOARD_KEY` y `MCP_DASHBOARD_TOKEN` son obligatorias, y
si faltan el arranque para. La base tiene que vivir en un volumen: sin
volumen, el contenedor es de solo lectura y las cuentas se pierden en cada
reinicio.

### 2. Fallar pronto, y con un mensaje que diga qué hacer

Un valor mal escrito **aborta el arranque**. Nunca se ignora en silencio.

- Un interruptor solo admite `true`, `false`, `1` y `0`. `MCP_ENABLE_SEND=yes`
  no significa "apagado": significa error.
- Un nombre de campo desconocido es un error, con la lista de los válidos.
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
| `mail/confirm.py` | Token de un solo uso y cupo diario, en memoria |
| `mail/compose.py` | Construcción del mensaje y escapado de cabeceras |
| `mail/readonly.py` | Proxy que bloquea la escritura en las rutas de lectura |
| `store/db.py` | La base de datos: esquema, migraciones, revisión |
| `store/crypto.py` | El cifrado de las contraseñas, con la clave fuera de la base |
| `store/store.py` | Las operaciones: dominios, cuentas y tokens |
| `store/accounts.py` | La fuente de cuentas: estática o de la base, con recarga |
| `dashboard/app.py` | El panel: rutas, sesión y anti-CSRF |
| `dashboard/api.py` | Los handlers del panel, incluida la prueba de conexión |
| `dashboard/ui.py` | La interfaz y el login |
| `docker/entrypoint.py` | Prepara el `accounts.toml` si lo hay. Nada más |
| `docker/rotate_audit.py` | Rota el JSONL de auditoría |
| `docker/healthcheck.py` | La sonda: el MCP y, si está, el panel |

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
.venv/bin/ruff format . && .venv/bin/ruff check .
.venv/bin/pytest
PYTHONSAFEPATH=1 .venv/bin/pytest    # el entorno de Actions
```

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
  índice. El entrypoint **no** decide si hay cuentas: solo prepara el fichero.
  Esa pregunta es de `config.py`.
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
  dos verdades, y de dos verdades sale una que nadie sabe cuál es.
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
- **`example.com`, nunca `ejemplo.com`.** Los dominios reservados son
  `example.com`, `example.org`, `example.net`, `*.test`, `*.invalid` y
  `*.localhost`. Esta confusión se coló dos veces.

## Publicar

La versión vive en `version.py`. Para subir una:

```bash
sed -i 's/__version__ = ".*"/__version__ = "1.2.0"/' version.py
sed -i 's/^version = ".*"/version = "1.2.0"/' pyproject.toml
sed -i 's/ARG MCP_VERSION=.*/ARG MCP_VERSION=1.2.0/' Dockerfile
sed -i 's/mcp-correo 2\.0\.0 |/mcp-correo 1.2.0 |/' docs/configuracion.md README.md
sed -i 's|mcp-correo:2\.0\.0|mcp-correo:1.2.0|' README.md
git commit -am "version 1.2.0"
git tag v1.2.0 && git push origin v1.2.0
```

Los `sed` de los dos últimos ficheros no son opcionales: hay un test que
comprueba que la documentación no habla de una versión vieja. El patrón es
la versión **actual**, así que hay que cambiarlo en cada subida.

La etiqueta dispara `.github/workflows/release.yml`, que pasa los tests,
publica la imagen en GHCR y crea el Release. **Si los tests fallan, la imagen
no se publica.** Así se detectó una fuga de correo real en el CHANGELOG: la
1.1.0 rota nunca llegó al registro.

## Antes de fusionar a `main`

- [ ] Los tests pasan en local **y** en un clon limpio.
- [ ] La imagen arranca: `docker compose -f docker-compose.yml -f docker-compose.local.yml up --build`.
- [ ] La documentación coincide con el código.
- [ ] Ningún dato real en el árbol.
- [ ] Si cambia el contrato de configuración, `.env.example`, el compose y
      `docs/configuracion.md` actualizados, con el CHANGELOG al día.
- [ ] Si cambian las rutas, el `deploy/nginx-mcp.conf` las sigue: con
      `location = /mcp` (coincidencia exacta) las rutas por cuenta y por
      dominio dan 404.
- [ ] Si el panel cambia, `docs/dashboard.md` y el README cuentan el flujo
      nuevo.
