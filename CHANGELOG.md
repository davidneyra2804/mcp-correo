# Changelog

Todas las novedades de mcp-correo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
el versionado es [SemVer](https://semver.org/lang/es/).

## [No publicado]

## [2.1.0] — 2026-10-29

El **envío directo** para las rutinas automáticas, y la herramienta que
impide dar por buena una implementación sin mirarla.

### Added

- **Envío directo opt-in para rutinas automáticas.** La tool
  `send_message_direct` envía el mensaje en **una sola llamada**, sin
  `confirmation_id` y sin confirmación humana por mensaje. Existe para los
  agentes que trabajan en segundo plano: en Paperclip, un agente que
  extrae pendientes de Trello y manda el correo llama una vez, y la
  plataforma no le deja hacer la segunda llamada del flujo de dos pasos.

  El modo está apagado por defecto y es independiente del envío normal:

  | | Interruptor global | Permiso de dominio/cuenta |
  | --- | --- | --- |
  | Envío con confirmación | `MCP_ENABLE_SEND` | `allow_send` |
  | Envío directo | `MCP_ENABLE_DIRECT_SEND` | `allow_direct_send` |

  La tool exige `idempotency_key`: una clave estable por envío. La misma
  clave con el mismo contenido **no vuelve a enviar**, devuelve el
  resultado anterior con `duplicate: true`; la misma clave con otro
  contenido se rechaza. Las claves viven en la base de datos, así que
  sobreviven a un reinicio y un reintento no duplica el correo.

  El esquema de la base pasa a la versión 2, con la tabla `direct_sends`.
  La migración se aplica al arrancar.

  Los fallos del SMTP se distinguen: un **rechazo** libera la clave y
  permite reintentar; una **falta de respuesta** deja la clave en estado
  incierto, porque el correo pudo salir, y el servidor se niega a
  reenviarlo con esa clave.

  Esto cambia el modelo de seguridad a propósito: en una cuenta con envío
  directo, el servidor **no** exige confirmación por mensaje. La
  autorización es la que se dio de antemano, y conviene limitarla a la
  cuenta que usa la rutina.

### Fixed

- **La migración añade la columna que falta.** La v2 añadió el permiso
  `allow_direct_send` a `domains` y `accounts`, pero la migración solo
  creaba la tabla `direct_sends`: la columna se había añadido al
  `CREATE TABLE` de la v1, y eso solo afecta a las bases **nuevas**. Una
  base v1 en marcha migraba sin la columna y el servidor se caía al
  arrancar con `IndexError: No item with that key` al leer las cuentas.

  Ahora la migración hace el `ALTER TABLE` que faltaba, y la comprobación
  es **idempotente y no depende del número de versión**: se mira la tabla
  real. Eso repara también las bases que quedaron a medias (marcadas como
  la versión nueva pero sin la columna), que es lo que pasó en el
  despliegue que falló.

- **La versión del esquema se escribe al migrar.** La migración escribía
  `schema_version` solo si la fila no existía. Una base que migraba
  aplicaba los cambios pero seguía marcando la versión anterior, así que
  la migración se volvía a aplicar en cada arranque. Ahora se escribe
  siempre.

### Documentación

- **La revisión automática antes de dar algo por bueno.** La skill
  `revision` (`.opencode/skills/revision/`) lanza un subagente revisor
  con contexto limpio al terminar una implementación, antes del commit y
  del push. El revisor es el agente `reviewer`
  (`.opencode/agents/reviewer.md`), que **no puede usar las tools de
  edición**: la garantía no depende de que el prompt se lo pida. (Puede
  usar el shell, que necesita para clonar y correr tests, pero trabaja
  siempre en un clon desechable.)

  El revisor trabaja en un clon aparte, comprueba el cambio
  **ejecutando** (tests, clon limpio con dependencias de verdad, y que el
  test nuevo falla sin el arreglo) y contrasta el cambio con la lista de
  trampas del `AGENTS.md`. El agente principal verifica sus hallazgos
  antes de arreglarlos, y repite la revisión si el arreglo cambió el
  código.

  La regla que la hace obligatoria está en el `AGENTS.md`, que se inyecta
  en cada sesión: no depende de que el modelo "se acuerde".

  Existe porque las dos últimas implementaciones se dieron por buenas sin
  ejecutar validaciones que el propio `AGENTS.md` ya pedía: una migración
  sin `ALTER TABLE` y un clon limpio sin hacer. La skill se corrigió
  varias veces con la ayuda del revisor antes de estar lista: encontró,
  entre otros, que el detector de datos ficticios pasaba en falso sobre
  los ficheros nuevos sin versionar.

- **`tests/test_revision.py`.** La skill se vigila a sí misma: que el
  frontmatter sea YAML válido, que los marcadores del prompt coincidan con
  los de la skill, que el fichero de referencia exista en la ruta que dice,
  que el agente no pueda editar, que la skill y el `AGENTS.md` no se
  contradigan y que no se cuelen palabras en otro idioma.

- **Las lecciones de esta versión quedan en el `AGENTS.md`.** Catorce
  trampas nuevas, cada una con su historia. Seis son del terreno del
  contrato con el cliente: el nombre de un campo puede hacer que el
  agente nunca reciba el valor; la respuesta de una tool es texto con
  JSON dentro y también se redacta; el cliente cachea el catálogo de las
  tools; una respuesta sin identificadores no se puede comprobar; un
  test que recorre una lista vacía pasa siempre; y el doble de IMAP tiene
  que saber lo que el código usa, o el test pasa por el motivo equivocado.

  Las otras ocho son de este trabajo: una tool que se llama una vez no
  puede depender de la segunda; un nombre de argumento con `key` puede
  acabar tapado; un rechazo y una falta de respuesta no son lo mismo; una
  clave de idempotencia necesita una huella, no solo una clave; una base
  de datos de pruebas se queda en el disco; la versión del esquema se
  escribe siempre, no solo cuando falta; **añadir una columna no es
  cambiar el `CREATE TABLE`**; y el número de versión puede mentir.

### Despliegue

- **La base de datos migra sola al arrancar.** El esquema pasa a la
  versión 2. No hay que tocar la base a mano y **las cuentas no se
  pierden**: la migración añade la columna que faltaba y comprueba las
  columnas contra la tabla real, así que también repara las bases que
  quedaron a medias con una versión nueva escrita y los cambios sin
  aplicar. El log dice qué columnas se han añadido; si el arranque falla,
  el error dice si la base está en solo lectura o bloqueada.
- Hay que **refrescar el catálogo de las tools** en el cliente MCP: se
  añade `send_message_direct` y aparece un permiso nuevo en el panel. Un
  cliente con el catálogo viejo sigue funcionando con las tools de antes.
- Para usar el envío directo: `MCP_ENABLE_DIRECT_SEND=true` en el entorno
  (y en el compose), y `allow_direct_send` en el panel, en el dominio o en
  la cuenta concreta.
- En Paperclip, la política del agente tiene que permitir `send_message_direct`
  sin aprobación interactiva: el servidor ya no pide confirmación, pero el
  cliente puede tenerla configurada por su cuenta.
- **La imagen se ha publicado sin construir ni probar en local**: la
  máquina de publicación no tiene Docker. `tests/test_docker.py` comprueba
  que los módulos que tienen que entrar en la imagen estén, pero no que
  la imagen construya, ni que los permisos del contenedor sean los
  correctos, ni que el volumen de datos funcione.
- **La imagen sale solo para `linux/amd64`**: el workflow no lleva
  `setup-qemu` ni `platforms`. En un host arm64 hay que construirla en
  local.

## [2.0.1] — 2026-10-27

Corrección del contrato de las tools de escritura y del flujo de confirmación,
con dos incidentes reales de por medio.

### Fixed

- **`confirm_token` se renombra a `confirmation_id`.** El agente no conseguía
  leer el valor de la preparación y no podía completar el envío. La causa
  estaba en Paperclip: tapa por **nombre** los campos de una respuesta de tool
  que "parecen credenciales" (`token`, `secret`, `password`, `api_key`,
  `bearer`...), y **el valor tapado es el que recibe el agente**, no el
  original. `confirm_token` caía en ese patrón, así que el agente recibía
  `***REDACTED***` en lugar del identificador. `confirmation_id` no cae, y el
  valor llega intacto.

  El `confirmation_id` no es una credencial: sin el bearer de la cuenta no
  sirve de nada, solo vale para una operación, en una cuenta, y durante diez
  minutos. Su valor lleva ahora un prefijo `cfm_` para que tampoco tenga la
  forma de una clave de ningún proveedor.

  Es un cambio de contrato: el argumento de `send_message` y `delete_message`
  se llama ahora `confirmation_id`, y la respuesta de `prepare_send` y
  `prepare_delete` devuelve ese campo. Los clientes que leían el esquema
  dinámicamente no se enteran; los que lo tenían escrito, sí.

- **Un `confirmation_id` que llega tapado dice que llegó tapado.** Antes el
  error era «desconocido o ya usado», que no distinguía un identificador
  malo de uno que nunca llegó. Ahora el mensaje dice que la plataforma lo
  redactó y que hay que volver a preparar.

### Added

- **El envío dice cómo localizar el mensaje.** `send_message` devuelve
  `message_id` y `sent_uid`, además de `sent_folder`. `create_draft` devuelve
  `message_id` y `draft_uid`. Con un diagnóstico real en la mano: el envío
  devolvió `copy_in_sent: true` y `sent: true`, pero las búsquedas
  posteriores en la carpeta de Enviados devolvieron cero mensajes y el
  informe no tenía forma de comprobar la copia, porque la respuesta no
  traía ningún identificador. Con `message_id` y `sent_uid`, el mensaje se
  localiza sin adivinar carpeta ni criterio.
- **`search_messages` acepta `message_id`.** Es la forma determinista de
  encontrar un mensaje concreto del que se conoce el identificador, y la
  que se usa para localizar la copia de un envío. Acepta el Message-ID con o
  sin ángulos.
- **`list_accounts` dice `sent_folder` y `drafts_folder`** de cada cuenta. La
  guía decía dónde está cada buzón, pero no en qué carpeta se guarda la
  copia de Enviados: el agente tenía que adivinar el nombre y acababa
  buscando en una carpeta que no era.
- **`tests/test_nombres_de_campos.py`.** Ningún nombre de campo de la
  superficie MCP puede caer en un patrón de secreto, y el valor del
  `confirmation_id` no puede tener la forma de una credencial conocida. El
  test se comprobó revirtiendo el nombre: falla, que es lo que tiene que
  hacer.

  Cubre las tres cosas que pasaron en producción: que el `confirmation_id`
  sobrevive a la redacción de la plataforma (se aplica su regex a la
  respuesta real), que un cliente con el catálogo viejo recibe un error
  accionable y no el del valor tapado, y que las respuestas de envío y
  borrador tampoco tienen claves que se tapen.

### Changed

- **El flujo de envío y de borrado se explica en tres capas.** El agente
  llamaba a `prepare_send`, creía que el correo salía y no sabía que tenía
  que llamar después a `send_message`. Ahora el contrato se dice en las
  instrucciones del servidor (paso a paso), en la descripción de cada tool
  (`prepare_send` dice que no envía y cuál es la siguiente llamada;
  `send_message` dice de dónde sale el `confirmation_id`) y en la respuesta de
  la preparación. No se puede depender de que el cliente trasmita las
  instrucciones generales del servidor.
- **La respuesta de la preparación lleva el estado explícito.** `prepare_send`
  y `prepare_delete` devuelven `status: "prepared"`, `sent: false` o
  `deleted: false`, y `next_tool` con la tool que sigue. La segunda llamada
  devuelve `status: "sent"` o `status: "deleted"`. El estado ya no depende de
  que el modelo deduzca la secuencia de un texto.
- **Los avisos dicen qué hacer a continuación.** El aviso de la preparación ya
  no solo prohíbe llamar a `send_message` o `delete_message` antes de tiempo:
  indica que la operación no se ha ejecutado, que hay que mostrar la vista
  previa, esperar la orden explícita y luego llamar a la tool siguiente con el
  `confirmation_id` devuelto. También avisa de que el `confirmation_id` caduca
  y de que, si falta o no llegó legible, hay que volver a preparar en vez de
  inventarlo.

No cambia el modelo de seguridad: sigue haciendo falta la orden explícita de
quien opera el asistente, y el `confirmation_id` sigue siendo de un solo uso,
ligado a la cuenta y a la operación.

### Despliegue

Al subir esto hay que **refrescar el catálogo de la conexión** en el cliente
MCP: el nombre del argumento de `send_message` y `delete_message` ha cambiado,
y un cliente con el catálogo viejo sigue mandando `confirm_token`, que el
servidor rechaza con un error de validación. Se recupera leyendo el esquema
de nuevo, pero es mejor no llegar ahí.

La imagen se ha publicado **sin construir ni probar en local**: la máquina de
publicación no tiene Docker. `tests/test_docker.py` comprueba que los módulos
que tienen que entrar en la imagen estén, pero no que la imagen construya, ni
los permisos del contenedor, ni que el volumen de datos funcione. La imagen
sale solo para `linux/amd64`.

## [1.0.0] — 2026-10-26

Primera versión estable. El objetivo sigue siendo el mismo: que un asistente
de IA pueda trabajar con buzones IMAP/SMTP de terceros sin que el agente
necesite salida a IMAP ni SMTP, y sin que pueda escribir sin una orden
explícita de quien lo opera.

### Añadido

- **Configuración solo por variables de entorno.** Cada ajuste del servidor
  tiene su variable `MCP_*`. Las cuentas se declaran numeradas:
  `MCP_ACCOUNT_<CAMPO>_<N>`. Precedencia: entorno > `accounts.toml` > defaults.
- **Rutas por cuenta.** `/mcp` expone todos los buzones con el bearer global.
  `/mcp/<cuenta>` expone uno solo, identificado por su correo, su `NAME` o su
  número, y se puede autenticar con una credencial propia
  (`MCP_ACCOUNT_BEARER_<N>`) que no vale en ninguna otra ruta.
- **Aislamiento en un único punto.** `MailService._account` es el único sitio
  donde se comprueba el ámbito de la petición, de modo que ninguna tool puede
  tocar una cuenta fuera de su ruta.
- **Despliegue con Portainer.** `docker-compose.yml` no monta ningún
  fichero de configuración: todo llega por variables. Overlays para
  Cloudflare Tunnel (`docker-compose.tunnel.yml`), para Caddy con TLS propio
  (`docker-compose.proxy.yml`) y para desarrollo local
  (`docker-compose.local.yml`).
- **Cloudflare Tunnel.** `cloudflared` alcanza el contenedor por la red de
  Compose; no hace falta abrir ningún puerto en el host ni añadir Caddy.
- **Versionado.** `version.py` es la fuente de verdad, un test la sincroniza
  con `pyproject.toml` y con la etiqueta de la imagen, y la versión aparece en
  el handshake MCP. Las etiquetas `vX.Y.Z` publican la imagen en GHCR y crean
  el Release.

### Seguridad

- Bearer obligatorio comparado con `hmac.compare_digest`; sin él, el proceso
  no arranca.
- Los interruptores de escritura solo admiten `true`, `false`, `1` y `0`: un
  valor mal escrito aborta el arranque en vez de quedarse apagado en
  silencio.
- Las credenciales por cuenta no pueden repetirse ni coincidir con la global.
- Auditoría JSONL por llamada, sin cuerpos ni credenciales. Si no se puede
  escribir, la tool no muta el buzón ni emite un token.

## [1.0.1] — 2026-10-26

Correcciones de una auditoría completa del proyecto.

### Corregido

- **El logging no lo configuraba el proyecto.** Los mensajes salían porque el
  SDK configura el logger raíz de rebote al construir el servidor MCP, con su
  formato. Si el SDK cambiaba, el banner de arranque se iba con él. Ahora se
  configura antes de nada, con el mismo formato que uvicorn.
- **`MCP_SMTP_SECURITY` no hacía nada** en las cuentas por entorno: la cuenta
  fijaba siempre el modo, así que el global era código muerto. Ahora la cuenta
  solo lo fija si dice `SMTP_USE_SSL`, y el puerto por defecto acompaña al modo
  (465 para `ssl`, 587 para `starttls`).
- **Los destinatarios ocultos se quedaban en la copia de Enviados.** El mismo
  mensaje llevaba `Bcc` por SMTP y sin `Bcc` al guardarlo.
- **`MCP_CONFIG` a un fichero inexistente impedía arrancar**, aunque las
  cuentas estuvieran definidas por entorno. Pasaba en el despliegue con systemd.
- **`/mcp/0` resolvía a una cuenta arbitraria** del `accounts.toml`.
- **`find_unanswered` afirmaba un criterio que no había comprobado** cuando no
  podía abrir la carpeta de enviados. Ahora lo dice.
- **El rotador de auditoría moría con una traza** en bucle de reinicios si un
  tamaño no era un número. Y una clave `"password"` entrecomillada se colaba en
  el TOML generado.

### Consistencia

- El entrypoint ya no decide si hay cuentas: solo prepara el fichero. Era el
  sitio donde aparecían las discrepancias de esquema.
- El mapa de capacidades, el límite de carpeta y la lista de cabeceras viven
  ahora en un solo sitio.
- `tests/test_ficticio.py` impide que un dominio, un correo o un rastro personal
  se cuelen en el repositorio.

### Documentación

- «No expone nada por sí mismo» era falso: publica `127.0.0.1:8765`.
- «El proceso arranca y avisa» era falso: aborta.
- Variables del servidor que nadie documentaba: `MCP_CONFIG`,
  `MCP_ALLOW_NONLOCAL_BIND`, `MCP_ACCOUNTS_TOML*`, `MCP_GENERATED_CONFIG`,
  `CADDY_*`, `CLOUDFLARED_VERSION`.
- El nginx del despliegue con systemd no servía las rutas por cuenta.

[1.0.1]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.1
## [1.0.2] — 2026-10-26

### Corregido

- **El `Dockerfile` no copiaba `scope.py` a la imagen.** El módulo llegó con
  las rutas por cuenta y se quedó fuera del `COPY`. La imagen no arrancaba:
  `ModuleNotFoundError: No module named 'scope'`. Los tests locales pasaban
  porque corren desde el repositorio, donde el fichero sí está.

### Pruebas

- Una prueba arma un directorio con **exactamente lo que copia el Dockerfile** y
  arranca el servidor desde ahí. Si un módulo o un fichero se queda fuera de
  la imagen, se ve.
- Otra comprueba que la lista de módulos que la app importa coincide con la
  del `COPY`.

[1.0.2]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.2
[1.0.1]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.1
## [1.0.3] — 2026-10-26

### Corregido

- **El contenedor de `audit-rotate` se quedaba "unhealthy" para siempre.** El
  `HEALTHCHECK` de la imagen espera un servidor HTTP en el 8765, y este
  servicio no sirve HTTP: es un bucle que vigila el fichero. Fallaba con
  *Connection refused* en cada intento. Ahora el servicio desactiva el
  healthcheck heredado.
- **El rotador no decía nada al arrancar.** Como solo imprimía cuando rotaba
  algo, y eso tarda una hora, el log salía vacío y el contenedor parecía
  parado. Ahora dice qué está vigilando.

### Pruebas

- Una comprueba que solo el servicio del servidor hereda el `HEALTHCHECK` de
  la imagen: los demás tienen que desactivarlo.

[1.0.3]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.3
[1.0.2]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.2
[1.0.1]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.1
## [1.0.4] — 2026-10-26

### Corregido

- **El 421 "Invalid Host header" no decía de dónde venía el problema.** Con un
  túnel de Cloudflare, la causa más común es que `MCP_ALLOWED_HOSTS` esté
  definida y no incluya el hostname público: la lista explícita **sustituye**
  a la derivada de `MCP_PUBLIC_HOST`, y el `Host` que reenvía el túnel se
  queda fuera. La respuesta ahora dice dónde mirar, sin filtrar la lista de
  hosts permitidos.
- **El arranque avisa si `MCP_PUBLIC_HOST` no está en `allowed_hosts`.** Y el
  log de arranque dice ya cuáles son los hosts y orígenes permitidos, para no
  tener que deducirlos.

### Pruebas

- El 421 incluye la pista y no filtra los hosts permitidos.
- El aviso de arranque salta cuando el host público se queda fuera de la
  lista, y no salta cuando está dentro.

[1.0.4]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.4
[1.0.3]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.3
[1.0.2]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.2
[1.0.1]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.1
## [1.0.5] — 2026-10-26

### Diagnóstico

- **El log dice qué `Host` llegó y cuáles se aceptan.** Con un túnel, el
  culpable puede ser que el `Host` que reenvía Cloudflare no sea el hostname
  público (por ejemplo, si la ruta tiene un *HTTP Host Header* distinto), o que
  la lista de hosts no lo incluya. Con una línea de log, se sabe cuál de los
  dos es.
- **La respuesta del 421 incluye el `Host` recibido.** El llamante ya conoce
  el suyo, y es la pista que faltaba.

[1.0.5]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.5
[1.0.4]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.4
[1.0.3]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.3
[1.0.2]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.2
[1.0.1]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.1
## [1.0.6] — 2026-10-26

### Diagnóstico

- **El arranque dice por qué una capacidad de escritura está apagada.** Encender
  `MCP_ENABLE_MARK` no basta: la cuenta también necesita
  `MCP_ACCOUNT_ALLOW_MARK_<N>=true`. Con una sola de las dos, la tool no
  aparece en `tools/list` y no había forma de saber por qué.

  ```
  INFO     Servidor listo: 1 cuentas, escucha 0.0.0.0:8765, escritura=ninguna
  INFO     Por qué están apagadas: marcado necesita MCP_ENABLE_MARK=true y
           MCP_ACCOUNT_ALLOW_MARK_<N>=true en la cuenta
  ```

- `list_accounts` documenta que `can_send`, `can_mark`, `can_delete` y
  `can_draft` reflejan las dos puertas.

[1.0.6]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.6
[1.0.5]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.5
[1.0.4]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.4
[1.0.3]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.3
[1.0.2]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.2
[1.0.1]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.1
## [1.0.7] — 2026-10-26

### Corregido

- **El argumento `account` de las tools era obligatorio incluso en una ruta de
  una sola cuenta.** En `/mcp/<cuenta>` la cuenta ya la fija la ruta, pero el
  modelo tenía que además saber la clave y pasarla. Si no la pasaba,
  pydantic rechazaba la llamada antes de llegar al código:
  `Tool 'list_messages' rejected arguments: ['account']`.

  Ahora `account` es opcional en todas las tools. Si la ruta expone una sola
  cuenta, se usa esa. Si expone varias, hay que indicarla, y el error dice
  cuáles hay: *"Indica la cuenta. En esta ruta hay: ..."*.
- **Ruido en el log al cerrar la conexión IMAP.** `logout()` ya cierra el
  socket, así que el `shutdown()` de después era un doble cierre que fallaba
  siempre y escribía *"No se pudo cerrar el socket IMAP de ..."* en cada
  petición. Ahora el cierre explícito solo se hace si `logout()` falla.

### Documentación

- Las rutas por cuenta y el argumento opcional, explicados en el README y en
  la guía de configuración.

[1.0.7]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.7
[1.0.6]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.6
[1.0.5]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.5
[1.0.4]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.4
[1.0.3]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.3
[1.0.2]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.2
[1.0.1]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.1
## [1.0.8] — 2026-10-26

### Corregido

- **El arranque listaba las dos variables de una capacidad aunque la global ya
  estuviera puesta.** Decía *"marcado necesita `MCP_ENABLE_MARK=true` y
  `MCP_ACCOUNT_ALLOW_MARK_<N>=true`"*, y con la global ya en `true` eso lleva
  a dudar de la que ya está bien. Ahora cada capacidad dice **solo lo que
  falta**, y cuando es el permiso por cuenta, con un ejemplo copiable:

  ```
  INFO     Por qué están apagadas: marcado: falta MCP_ACCOUNT_ALLOW_MARK_<N>=true
           en la cuenta (por ejemplo, MCP_ACCOUNT_ALLOW_MARK_1=true)
  ```

[1.0.8]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.8
[1.0.7]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.7
[1.0.6]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.6
[1.0.5]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.5
[1.0.4]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.4
[1.0.3]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.3
[1.0.2]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.2
[1.0.1]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.1
## [1.0.9] — 2026-10-26

### Cambiado

- **El permiso por cuenta de escritura es un override opcional, no un segundo
  interruptor.** Antes hagan falta las dos cosas: el global
  (`MCP_ENABLE_MARK=true`) y el permiso de la cuenta
  (`MCP_ACCOUNT_ALLOW_MARK_<N>=true`). Encender una capacidad eran dos
  cambios en dos sitios, y el síntoma —que la tool no aparezca— no decía
  cuál faltaba.

  Ahora el global es el maestro y además el valor por defecto:

  | Global | Permiso de la cuenta | Resultado |
  | --- | --- | --- |
  | `false` | lo que sea | apagada: el global manda |
  | `true` | sin definir | encendida: la cuenta lo hereda |
  | `true` | `true` | encendida |
  | `true` | `false` | apagada para esa cuenta: manda la cuenta |

  El override por cuenta sigue sirviendo para dejar fuera una cuenta sin
  apagar la capacidad entera.

  **Esto también cambia el `accounts.toml`**: una cuenta sin `allow_send` ahora
  hereda el `enable_send` global, en vez de estar apagada.

### Añadido

- `write_capabilities_detail` distingue los dos motivos por los que una
  capacidad puede estar apagada: que falte el global, o que todas las
  cuentas la tengan en `false`.

[1.0.9]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.9
[1.0.8]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.8
[1.0.7]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.7
[1.0.6]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.6
[1.0.5]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.5
[1.0.4]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.4
[1.0.3]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.3
[1.0.2]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.2
[1.0.1]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.1
## [1.1.0] — 2026-10-26

### Añadido

- **Nombre visible del remitente: `MCP_ACCOUNT_SENDER_<N>`.** El `From` de los
  correos salientes era solo la dirección, así que quien lo recibía veía el
  nombre de la cuenta sin el dominio. Con esta variable:

  ```bash
  MCP_ACCOUNT_SENDER_1=Ada Lovelace
  ```

  el `From` pasa a ser `Ada Lovelace <ada@corp.example.com>`, y en el
  `accounts.toml` se llama `sender`.

  El nombre se escapa con las reglas de la RFC 5322: si lleva coma o comillas,
  se entrecomilla, para que no parta la dirección en dos. Un salto de línea se
  rechaza al cargar la configuración, no ya al enviar: acabaría en una cabecera
  y permitiría inyectar un `Bcc` de verdad. El sobre SMTP sigue llevando la
  dirección pelada.

### Documentación

- `SENDER` en la lista de campos de cuenta, en el `.env.example` y en el
  ejemplo de `accounts.toml`.

[1.1.0]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.1.0
[1.0.9]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.9
[1.0.8]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.8
[1.0.7]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.7
[1.0.6]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.6
[1.0.5]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.5
[1.0.4]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.4
[1.0.3]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.3
[1.0.2]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.2
[1.0.1]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.1
[1.0.0]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.0

## [2.0.0] — 2026-10-26

Un panel de control en un segundo puerto, y las cuentas de correo en una
base de datos en vez de en variables de entorno. **El contrato de las rutas
cambia**, y por eso es una versión mayor.

### Añadido

- **Panel de control en su propio puerto.** Una segunda superficie HTTP, en
  el mismo proceso y otro puerto, para dar de alta dominios y cuentas sin
  tocar el despliegue. Tiene su propia credencial (`MCP_DASHBOARD_TOKEN`),
  su propia sesión firmada y su propia capa anti-CSRF. **No puede leer ni
  escribir un buzón**: solo gestiona la configuración y prueba conexiones.
- **Las cuentas en una base de datos SQLite.** La base es la **única** fuente
  de las cuentas. No hay variables `MCP_ACCOUNT_<CAMPO>_<N>` ni fichero de
  configuración: las cuentas se dan de alta en el panel, y una instalación
  nueva empieza vacía.
- **Cuentas por dominio.** Un dominio agrupa cuentas y les da un servidor
  IMAP y SMTP por defecto, unos permisos y una credencial propia. La
  cadena de permisos crece un nivel: global → dominio → cuenta.
- **Exposición en tiempo real.** Una cuenta creada en el panel está en su
  ruta `/mcp/<cuenta>` en la siguiente petición. Sin reiniciar. El
  contador de revisiones vive en la base, así que funciona igual dentro de
  un proceso que entre dos.
- **Ruta por dominio: `/mcp/<dominio>`.** Abre las cuentas del dominio, con
  la credencial del dominio o la general.
- **Token por dominio y token por cuenta**, generados y rotados desde el
  panel. Se muestran una sola vez.
- **Botón de probar.** Valida la conexión IMAP (y SMTP) con la contraseña
  recién escrita, antes de guardar. Usa el mismo código que el resto del
  servidor, así que el mensaje es el mismo que saldría al leer el buzón.
- **Contraseñas cifradas en reposo**, con AES-GCM y una clave que **no**
  está en la base de datos (`MCP_DASHBOARD_KEY`). El arranque comprueba que
  la clave corresponde a la base y, si no, para y lo dice.
- **Auditoría del panel.** Todo lo que hace queda en el mismo JSONL que las
  tools, con su propio nombre y sin secretos.

### Cambiado

- **El panel y la base de datos no son opcionales.** Son la forma de
  gestionar las cuentas. `MCP_DASHBOARD_KEY` y `MCP_DASHBOARD_TOKEN` son
  obligatorias, y si faltan el arranque para diciendo cuál. `MCP_DASHBOARD_DB`
  es la ruta del fichero, no un interruptor: por defecto `cuentas.db`, y en
  el contenedor sobre el volumen de datos.
- **`MCP_ACCOUNTS` desaparece.** La lista de índices de cuenta no hacía
  falta: los índices se descubren solos. Con la lista, además, un
  descuadre abortaba el arranque por algo que no era un error de
  configuración.
- **`/mcp` ya no expone todas las cuentas.** Pasa a ser la puerta de
  entrada: la guía (el catálogo de rutas) y, si hay uno, el dominio marcado
  como por defecto. Para abrir un buzón hay que nombrar la cuenta o el
  dominio. `list_accounts` devuelve el catálogo, con la ruta de cada
  cuenta y de cada dominio.
- **La credencial tiene que abrir la ruta.** `MCP_BEARER_TOKEN` es el bearer
  general. El de un dominio abre la ruta de su dominio y las de sus
  cuentas; el de una cuenta, solo la suya. Una credencial de cuenta en
  `/mcp/<dominio>` responde 403, aunque el dominio tenga una sola cuenta.
- **La lista de tools de escritura depende del interruptor global**, no de
  las cuentas: la lista se fija al arrancar y las cuentas pueden cambiar
  después. El permiso por cuenta se sigue comprobando en cada llamada, que
  es donde se comprueba de todos modos.
- **Sin cuentas ya no es un error de arranque.** Las da de alta el panel.
- **Se retira la configuración por fichero y por variables de cuenta.**
  `accounts.toml`, `MCP_CONFIG`, `MCP_ACCOUNTS_TOML`, `MCP_ACCOUNTS_TOML_B64`
  y `MCP_GENERATED_CONFIG` dejan de leerse, y con ellas todas las variables
  `MCP_ACCOUNT_<CAMPO>_<N>`. La configuración del servidor sigue siendo
  **entera** por variables `MCP_*`, una por campo. El `entrypoint` del
  contenedor, que solo preparaba el TOML, desaparece: la imagen ejecuta el
  servidor directamente.
- **El texto de arranque dice de dónde viene la configuración.** Siempre son
  variables de entorno, y el panel lo dice cuando la base está vacía.

### Corregido

- **El panel podía morir en silencio.** Hacía el `bind` en su hilo: si el
  puerto estaba ocupado, el hilo moría, el log decía "Panel en marcha" y
  el proceso seguía vivo **sin panel**. Con el panel obligatorio, eso es un
  proceso roto. Ahora el socket se abre en el hilo principal y, si no
  puede, el proceso para y lo dice.

### Seguridad

- El panel escucha en `127.0.0.1` y su puerto se publica en loopback.
- La sesión del panel es una cookie firmada con HMAC, `HttpOnly` y
  `SameSite=Strict`, con caducidad.
- Las peticiones que cambian algo exigen la cabecera `X-MCP-Dashboard`:
  un formulario de otro sitio no puede poner una cabecera a medida.
- La API nunca devuelve una contraseña. Al leer una cuenta se ve si tiene
  contraseña, no cuál es.
- La base de datos va en un volumen. Sin él, el contenedor es de solo
  lectura y las cuentas se pierden en cada reinicio.

[2.0.0]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v2.0.0
