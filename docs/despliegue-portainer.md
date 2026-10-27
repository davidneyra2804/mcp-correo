# Despliegue con Portainer

Stack Docker para quien administra el servidor. **Toda la configuración va en
variables de entorno**: en Portainer se pega un `.env` y no hay que escribir ni
subir ningún fichero. El contrato completo está en
[configuracion.md](configuracion.md).

La imagen es multi-stage, `python:3.12-slim`, usuario `mcp` (uid 10001), sin
secretos. Un solo worker de uvicorn: los tokens de confirmación y el cupo
diario viven en memoria. El `HEALTHCHECK` llama a `GET /health`.

`docker-compose.yml` sirve de dos maneras. Desde Git no hace falta publicar
nada: la imagen local se llama `mcp-correo:local`. Solo `mcp` tiene `build:`;
`audit-rotate` usa esa misma imagen (`pull_policy: never` y `depends_on: mcp`),
así que no se construye dos veces. El contexto de build es el propio
repositorio: el Dockerfile no copia nada de fuera.

Portainer ejecuta `docker compose pull` y después `up`. El mensaje del
despliegue puede decir «pull». Ese pull no busca `mcp-correo:local` en un
registro, porque `mcp` lleva `pull_policy: build` y `audit-rotate` lleva
`never`. Compose construye `mcp-correo:local` al levantar el servicio. Si el
pull fallara con «pull access denied for mcp-correo», la política no está
aplicada (hace falta este compose, no uno que deje la imagen sin
`pull_policy`).

Para una imagen ya publicada, define `MCP_IMAGE` con su nombre completo y
`MCP_PULL_POLICY=always`. Las dos hacen falta: sin la segunda, Compose
seguiría construyendo en local y no descargaría la del registro. Con
`MCP_PULL_POLICY=always`, `audit-rotate` usa la misma imagen publicada, así
que tampoco hay que construirla.

El contenedor escucha en `0.0.0.0:8765` porque el proxy llega por la red de
Docker. El compose publica ese puerto solo en `127.0.0.1:8765`. `/mcp` exige
Bearer. Hacia Internet hace falta TLS. No abras `8765` en `0.0.0.0`.

## 1. Crear el stack desde Git

En Portainer: **Stacks → Add stack → Repository**. URL del repositorio, rama
que quieras desplegar, Compose path `docker-compose.yml`. Activa la
reconstrucción al actualizar el stack.

El compose base solo tiene el MCP y la rotación de la auditoría: **no expone
nada por sí mismo**. Quien publica es un overlay, que en Portainer se añade
en **Additional paths** (es lo mismo que pasar varios `-f` a `docker compose`):

| Additional paths | Para qué |
| --- | --- |
| `docker-compose.tunnel.yml` | Cloudflare Tunnel. Es tu caso. |
| `docker-compose.proxy.yml` | Caddy con TLS propio. Solo si no usas túnel. |

Los dos a la vez no tiene sentido: serían dos terminadores de TLS. Con túnel,
el TLS lo termina el edge de Cloudflare y `cloudflared` habla HTTP plano con
el contenedor por la red de Compose.

Los contenedores llevan nombre fijo, para reconocerlos en la lista de
Portainer y en los logs: `mcp-correo`, `mcp-correo-audit-rotate`,
`mcp-correo-cloudflared` y `mcp-correo-caddy`.

Un aviso: `container_name` es único en todo el host. Si despliegas el mismo
stack dos veces, o dos stacks con el mismo nombre, Docker se quejará.

## 2. Las variables del stack

En **Environment variables** marca **Load variables from .env file** y sube tu
`.env`. Portainer guarda esas variables y las deja disponibles para el compose.
Los valores no se documentan aquí; el punto de partida es
[.env.example](../.env.example).

Las que no puedes dejar de definir:

| Nombre | Obligatoria | Qué es |
| --- | --- | --- |
| `MCP_BEARER_TOKEN` | sí | Secreto del cliente MCP. Mínimo 16 caracteres. `openssl rand -base64 48`. |
| `MCP_ACCOUNT_USERNAME_<N>` | sí | Usuario de la cuenta N. |
| `MCP_ACCOUNT_INBOX_HOST_<N>` | sí | Servidor IMAP de la cuenta N. |
| `MCP_ACCOUNT_PASSWORD_<N>` | sí, o `MCP_ACCOUNT_PASSWORD_ENV_<N>` | Contraseña de la cuenta N. |
| `MCP_ACCOUNT_BEARER_<N>` | no | Credencial que da acceso solo a esa cuenta. Ver abajo. |
| `MCP_PUBLIC_HOST` | para el dominio público | Nombre del MCP, el que irá en el certificado. Arma `allowed_hosts` y `allowed_origins`. |
| `MCP_ALLOWED_HOSTS` | no | Lista separada por comas, si la generada no basta. |
| `MCP_ALLOWED_ORIGINS` | no | Igual, para orígenes del navegador. |
| `MCP_IMAGE` | no | Imagen ya publicada. Junto con `MCP_PULL_POLICY=always`. |
| `MCP_PULL_POLICY` | no | Vacía: `build` en `mcp` y `never` en `audit-rotate`. `always` solo si `MCP_IMAGE` apunta a un registro. |
| `MCP_PUBLISH_BIND` / `MCP_PUBLISH_PORT` | no | Por defecto `127.0.0.1` y `8765`. |
| `MCP_DASHBOARD_DB` | no | Ruta del fichero SQLite. **Su presencia activa el panel** y convierte la base de datos en la fuente de las cuentas. |
| `MCP_DASHBOARD_KEY` | con el panel | Clave con la que se cifran las contraseñas. No está en la base: guárdala. |
| `MCP_DASHBOARD_TOKEN` | con el panel | Credencial de acceso al panel. Distinta de `MCP_BEARER_TOKEN`. |
| `MCP_AUDIT_MAX_BYTES` / `MCP_AUDIT_KEEP` / `MCP_AUDIT_ROTATE_SECONDS` | no | Rotación: 10 MiB, 12 copias, cada hora. |
| `CLOUDFLARE_TUNNEL_TOKEN` | solo con el túnel | Token del túnel, del panel de Cloudflare. |

Si añades otra cuenta, sus variables `MCP_ACCOUNT_<CAMPO>_<N>` tienen que estar
también en las variables del stack. Una línea vacía no sirve: el proceso no
arranca si falta el secreto de una cuenta declarado.

`MCP_BEARER_TOKEN` y las contraseñas van solo en Environment variables de
Portainer. No se copian al repositorio, no van dentro de la imagen y no se
escriben en ningún fichero del servidor.

### El panel, si lo activas

Con `MCP_DASHBOARD_DB` (por ejemplo `/var/lib/mcp-correo/cuentas.db`) el
panel arranca en el puerto 8766 y las cuentas pasan a estar en la base de
datos. En el stack hace falta además `MCP_DASHBOARD_KEY` y
`MCP_DASHBOARD_TOKEN`.

La base tiene que caer en el volumen `data`, que el compose ya declara y
monta en `/var/lib/mcp-correo`. El contenedor es de solo lectura: sin ese
volumen, la base no se puede escribir.

Las cuentas que ya tengas en `MCP_ACCOUNT_<CAMPO>_<N>` se importan **una
vez**, y solo si la base está vacía. A partir de ahí, la base manda: para
cambiar una cuenta, desde el panel.

El puerto del panel se publica en loopback, como el del MCP. Publicarlo
en abierto es una decisión que hay que querer: el panel ve las
contraseñas. Ver [El panel de control](dashboard.md).

### Cómo llegan las variables al contenedor

El compose las pasa por dos vías:

- **`environment:`**, con los nombres fijos del servidor. Aquí el token es
  obligatorio: si falta, el propio compose para con un error antes de
  levantar nada.
- **`env_file: stack.env`**, que es el fichero donde Portainer deja todas las
  variables del stack. Es lo que hace llegar las variables
  `MCP_ACCOUNT_<CAMPO>_<N>` sin enumerarlas una a una en el YAML.

`env_file` con `required: false` necesita **Compose 2.24 o superior**. Si el
fichero no está, se sigue: si tampoco hay cuentas por entorno, el contenedor
**no arranca** y el log dice `No hay cuentas. Define las variables de cada
cuenta (MCP_ACCOUNT_<CAMPO>_<N>)`.

Si tu Portainer usa un Compose más antiguo y se queja del `env_file`, hay dos
salidas: subir el Compose, o definición alternativa de la configuración con
`MCP_ACCOUNTS_TOML_B64` (el TOML en base64, sin contraseñas) que el entrypoint
convierte en `/tmp/accounts.toml` dentro del contenedor.

## 3. Las cuentas

Las cuentas se numeran. El nombre de la variable no cambia de una a otra,
solo el número final:

```bash
MCP_ACCOUNT_USERNAME_1=ada@corp.example.com
MCP_ACCOUNT_INBOX_HOST_1=imap.corp.example.com
MCP_ACCOUNT_SMTP_HOST_1=smtp.corp.example.com
MCP_ACCOUNT_SMTP_PORT_1=587
MCP_ACCOUNT_SMTP_USE_SSL_1=false
MCP_ACCOUNT_PASSWORD_1=la-clave-de-la-cuenta

MCP_ACCOUNT_USERNAME_2=luis@corp.example.com
MCP_ACCOUNT_INBOX_HOST_2=imap.otro.example.com
MCP_ACCOUNT_PASSWORD_2=otra-clave
```

Para añadir una cuenta se copia el bloque y se cambia el número. No hay que
declararla en ninguna lista.

La contraseña va en dos sitios posibles, nunca en los dos:
`MCP_ACCOUNT_PASSWORD_<N>` con el secreto, o
`MCP_ACCOUNT_PASSWORD_ENV_<N>` con el nombre de otra variable.

El fichero `accounts.toml` y las variables `MCP_ACCOUNTS_TOML_B64` /
`MCP_ACCOUNTS_TOML` siguen funcionando como alternativa. Si existen las dos
fuentes, mandan las cuentas del entorno.

## 3 bis. Una credencial por cuenta

Si quieres que un cliente solo vea un buzón, dale su propia credencial:

```bash
MCP_ACCOUNT_BEARER_1=bearer-solo-de-la-cuenta-1-0123456789abcdef
```

Y apúntalo a la ruta de esa cuenta:

```
https://mcp.example.com/mcp/ada@corp.example.com
```

En `/mcp` ve el catálogo de rutas (y las cuentas del dominio por defecto,
si hay uno marcado); en `/mcp/ada@corp.example.com` solo esa cuenta. El
bearer de una cuenta no vale en la ruta de otra, ni en la de un dominio,
ni en la general: responde 403. Los detalles están en
[configuracion.md](configuracion.md).

## 4. TLS

El puerto publicado por defecto no lleva TLS: es loopback, para un proxy que ya
esté en el mismo host.

**(a) Cloudflare Tunnel.** Sin puertos en el host y sin Caddy. Mira
[despliegue-tunel-cloudflare.md](despliegue-tunel-cloudflare.md).

**(b) Proxy que ya existe.** nginx, Nginx Proxy Manager, Traefik o Caddy en el
host pueden hacer proxy a `http://127.0.0.1:8765`. El ejemplo de nginx del
repositorio es `deploy/nginx-mcp.conf` (el `server_name` de ejemplo es
`mcp.example.com`). Un proxy en otro contenedor no debe usar `127.0.0.1`:
únete a la red del stack y apunta a `http://mcp:8765`. Si Traefik llega solo
por esa red, comenta el bloque `ports:` de `mcp`. Las etiquetas Traefik están
comentadas en el servicio, con el dominio `mcp.example.com` y la red externa
`proxy`.

**(c) Caddy de este repositorio.** Overlay `docker-compose.proxy.yml`, para
quien quiera TLS propio con Let's Encrypt:

```bash
docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d --build
```

`deploy/Caddyfile` usa `tls internal` para no pedir un certificado público al
arrancar. Para el dominio real, borra esa línea, define `MCP_PUBLIC_HOST` con
un nombre que resuelva a este servidor y deja libres 80 y 443. Caddy no lleva
`cap_drop: ALL`: tiene que abrir esos puertos. El proceso MCP sí va sin
capacidades.

Con el dominio público, `MCP_PUBLIC_HOST` deja pasar el `Host` de ese nombre y
el origen `https://` correspondiente, y mantiene `127.0.0.1` para las pruebas
en loopback.

## 5. Logs, auditoría y actualización

- Logs del proceso: en Portainer, el contenedor `mcp` → **Logs**. El driver
  `json-file` guarda como mucho 3 ficheros de 10 MiB.
- Auditoría: volumen nombrado `audit`, montado en `/var/log/mcp-correo`.

  ```bash
  docker compose exec mcp python -c "print(open('/var/log/mcp-correo/audit.jsonl').read())"
  ```

  `audit-rotate` renombra `audit.jsonl` a `.1`, `.2`, … al pasar de
  `MCP_AUDIT_MAX_BYTES` y borra lo que exceda `MCP_AUDIT_KEEP`. El servidor
  abre el fichero en cada línea, así que el renombrado no pierde la línea
  siguiente.

- Base de datos del panel: volumen nombrado `data`, montado en
  `/var/lib/mcp-correo`. Solo existe si activas el panel. **Copia de
  seguridad**: el fichero contiene las cuentas y las contraseñas
  cifradas, pero sin `MCP_DASHBOARD_KEY` no sirven de nada. Copia las dos
  cosas, y la clave aparte.

- Actualizar: en el stack, **Pull and redeploy**. Los secretos de Environment
  variables y el volumen `audit` se conservan. Para cambiar el token o una
  contraseña, edita la variable y vuelve a desplegar el stack. La imagen sigue
  sin secretos.

Límites del servicio `mcp`: 512 MiB, `pids_limit` 128, `restart: unless-stopped`,
raíz de solo lectura, tmpfs en `/tmp` (`noexec`, `nosuid`), `cap_drop: ALL` y
`no-new-privileges`.

La unidad systemd no usa este compose. Si despliegas con systemd, el proceso
sigue en `127.0.0.1:8765` con un solo worker. Ver
[despliegue-systemd.md](despliegue-systemd.md).
