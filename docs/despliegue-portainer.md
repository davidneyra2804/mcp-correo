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

El servicio `caddy` lleva el perfil `tls` y no arranca con el stack normal.
`mcp` y `audit-rotate` sí.

Para exponer con Cloudflare Tunnel, añade `docker-compose.tunnel.yml` en
**Additional paths**: es la misma semántica que `docker compose -f ... -f ...`.
La guía del túnel está en
[despliegue-tunel-cloudflare.md](despliegue-tunel-cloudflare.md).

## 2. Las variables del stack

En **Environment variables** marca **Load variables from .env file** y sube tu
`.env`. Portainer guarda esas variables y las deja disponibles para el compose.
Los valores no se documentan aquí; el punto de partida es
[.env.example](../.env.example).

Las que no puedes dejar de definir:

| Nombre | Obligatoria | Qué es |
| --- | --- | --- |
| `MCP_BEARER_TOKEN` | sí | Secreto del cliente MCP. Mínimo 16 caracteres. `openssl rand -base64 48`. |
| `MCP_ACCOUNTS` | sí | Lista de claves de cuenta, separada por comas. |
| `MAIL_PRINCIPAL_PASSWORD` | si la cuenta `principal` está definida | Contraseña o app password de esa cuenta. |
| `MAIL_ARCHIVO_PASSWORD` | si la cuenta `archivo` está definida | Igual para la segunda cuenta. |
| `MCP_PUBLIC_HOST` | para el dominio público | Nombre del MCP, el que irá en el certificado. Arma `allowed_hosts` y `allowed_origins`. |
| `MCP_ALLOWED_HOSTS` | no | Lista separada por comas, si la generada no basta. |
| `MCP_ALLOWED_ORIGINS` | no | Igual, para orígenes del navegador. |
| `MCP_IMAGE` | no | Imagen ya publicada. Junto con `MCP_PULL_POLICY=always`. |
| `MCP_PULL_POLICY` | no | Vacía: `build` en `mcp` y `never` en `audit-rotate`. `always` solo si `MCP_IMAGE` apunta a un registro. |
| `MCP_PUBLISH_BIND` / `MCP_PUBLISH_PORT` | no | Por defecto `127.0.0.1` y `8765`. |
| `MCP_AUDIT_MAX_BYTES` / `MCP_AUDIT_KEEP` / `MCP_AUDIT_ROTATE_SECONDS` | no | Rotación: 10 MiB, 12 copias, cada hora. |
| `CLOUDFLARE_TUNNEL_TOKEN` | solo con el túnel | Token del túnel, del panel de Cloudflare. |

Si añades otra cuenta, sus variables `MCP_ACCOUNT_<CLAVE>_*` tienen que estar
también en las variables del stack. Una línea vacía no sirve: el proceso no
arranca si falta el secreto de una cuenta declarada.

`MCP_BEARER_TOKEN` y las contraseñas van solo en Environment variables de
Portainer. No se copian al repositorio, no van dentro de la imagen y no se
escriben en ningún fichero del servidor.

### Cómo llegan las variables al contenedor

El compose las pasa por dos vías:

- **`environment:`**, con los nombres fijos del servidor. Aquí el token es
  obligatorio: si falta, el propio compose para con un error antes de
  levantar nada.
- **`env_file: stack.env`**, que es el fichero donde Portainer deja todas las
  variables del stack. Es lo que hace llegar las variables
  `MCP_ACCOUNT_<CLAVE>_*` sin enumerarlas una a una en el YAML.

`env_file` con `required: false` necesita **Compose 2.24 o superior**. Si el
fichero no está, se sigue: el proceso arranca y avisa de que no hay cuentas.

Si tu Portainer usa un Compose más antiguo y se queja del `env_file`, hay dos
salidas: subir el Compose, o definición alternativa de la configuración con
`MCP_ACCOUNTS_TOML_B64` (el TOML en base64, sin contraseñas) que el entrypoint
convierte en `/tmp/accounts.toml` dentro del contenedor.

## 3. Las cuentas

En el `.env`, con el patrón `MCP_ACCOUNT_<CLAVE>_<CAMPO>`:

```bash
MCP_ACCOUNTS=principal

MCP_ACCOUNT_PRINCIPAL_IMAP_HOST=imap.corp.example.com
MCP_ACCOUNT_PRINCIPAL_SMTP_HOST=smtp.corp.example.com
MCP_ACCOUNT_PRINCIPAL_SMTP_PORT=587
MCP_ACCOUNT_PRINCIPAL_SMTP_SECURITY=starttls
MCP_ACCOUNT_PRINCIPAL_USERNAME=ada@corp.example.com
MCP_ACCOUNT_PRINCIPAL_PASSWORD=la-clave-de-la-cuenta
```

La contraseña va en dos sitios posibles, nunca en los dos:
`MCP_ACCOUNT_<CLAVE>_PASSWORD` con el secreto, o
`MCP_ACCOUNT_<CLAVE>_PASSWORD_ENV` con el nombre de otra variable.

El fichero `accounts.toml` y las variables `MCP_ACCOUNTS_TOML_B64` /
`MCP_ACCOUNTS_TOML` siguen funcionando como alternativa. Si existen las dos
fuentes, mandan las cuentas del entorno.

## 4. TLS

El puerto publicado por defecto no lleva TLS: es loopback, para un proxy que ya
esté en el mismo host.

**(a) Proxy que ya existe.** nginx, Nginx Proxy Manager, Traefik o Caddy en el
host pueden hacer proxy a `http://127.0.0.1:8765`. El ejemplo de nginx del
repositorio es `deploy/nginx-mcp.conf` (el `server_name` de ejemplo es
`mcp.example.com`). Un proxy en otro contenedor no debe usar `127.0.0.1`:
únete a la red del stack y apunta a `http://mcp:8765`. Si Traefik llega solo
por esa red, comenta el bloque `ports:` de `mcp`. Las etiquetas Traefik están
comentadas en el servicio, con el dominio `mcp.example.com` y la red externa
`proxy`.

**(b) Caddy de este compose.** Perfil `tls`, apagado por defecto. En Portainer,
si el formulario tiene perfiles, añade `tls`. En la máquina:

```bash
docker compose --profile tls up -d --build
```

`deploy/Caddyfile` usa `tls internal` para no pedir un certificado público al
arrancar. Para el dominio real, borra esa línea, define `MCP_PUBLIC_HOST` con
un nombre que resuelva a este servidor y deja libres 80 y 443. Caddy no lleva
`cap_drop: ALL`: tiene que abrir esos puertos. El proceso MCP sí va sin
capacidades.

**(c) Cloudflare Tunnel.** Sin puertos en el host. Mira
[despliegue-tunel-cloudflare.md](despliegue-tunel-cloudflare.md).

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
