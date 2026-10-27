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
[1.0.0]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.0
