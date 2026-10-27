# Changelog

Todas las novedades de mcp-correo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
el versionado es [SemVer](https://semver.org/lang/es/).

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
