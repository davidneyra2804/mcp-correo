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

[1.0.0]: https://github.com/davidneyra2804/mcp-correo/releases/tag/v1.0.0
