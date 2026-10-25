# Despliegue con Portainer

Stack Docker para quien administra el servidor. Los nombres de host de esta página son de ejemplo (`mcp.example.com`). El token y las contraseñas no van en git ni dentro de la imagen.

La imagen es multi-stage, `python:3.12-slim`, usuario `mcp` (uid 10001), sin secretos. Un solo worker de uvicorn: los tokens de confirmación y el cupo diario viven en memoria. El `HEALTHCHECK` llama a `GET /health`.

`docker-compose.yml` sirve de dos maneras. Portainer clona el Git y construye con `build:`. Si más adelante publicas la imagen, define `MCP_IMAGE` y comenta el bloque `build`.

El contenedor escucha en `0.0.0.0:8765` porque el proxy llega por la red de Docker. El compose publica ese puerto solo en `127.0.0.1:8765`. `/mcp` exige Bearer. Hacia Internet hace falta TLS. No abras `8765` en `0.0.0.0`.

## 1. Crear el stack desde Git

En Portainer: **Stacks → Add stack → Repository**. URL del repositorio, rama que quieras desplegar, Compose path `docker-compose.yml`. Activa la reconstrucción al actualizar el stack. No hace falta un `env_file` ni una ruta absoluta del host.

El servicio `caddy` lleva el perfil `tls` y no arranca con el stack normal. `mcp` y `audit-rotate` sí.

## 2. Variables del stack

En **Environment variables** define los nombres. Los valores no se documentan aquí.

| Nombre | Obligatoria | Qué es |
| --- | --- | --- |
| `MCP_BEARER_TOKEN` | sí | Secreto del cliente MCP. Mínimo 16 caracteres. |
| `MAIL_PRINCIPAL_PASSWORD` | si la cuenta `principal` está en el TOML | Contraseña o app password de esa cuenta. |
| `MAIL_ARCHIVO_PASSWORD` | si la cuenta `archivo` está en el TOML | Igual para la segunda cuenta del ejemplo. |
| `MCP_PUBLIC_HOST` | para el dominio público | Nombre del MCP, el que irá en el certificado. Arma `allowed_hosts` y `allowed_origins`. |
| `MCP_ALLOWED_HOSTS` | no | Lista separada por comas, si la generada no basta. |
| `MCP_ALLOWED_ORIGINS` | no | Igual, para orígenes del navegador. |
| `MCP_ACCOUNTS_TOML_B64` | si no montas el fichero | TOML en base64, una sola línea, sin contraseñas. |
| `MCP_IMAGE` | no | Imagen ya publicada. Si la usas, comenta `build:`. |
| `MCP_PUBLISH_BIND` / `MCP_PUBLISH_PORT` | no | Por defecto `127.0.0.1` y `8765`. |
| `MCP_AUDIT_MAX_BYTES` / `MCP_AUDIT_KEEP` / `MCP_AUDIT_ROTATE_SECONDS` | no | Rotación: 10 MiB, 12 copias, cada hora. |

Si añades otra cuenta, su `password_env` tiene que existir también como variable del servicio `mcp` y como variable del stack. Una línea vacía no sirve: el proceso no arranca si falta el secreto de una cuenta declarada.

`MCP_BEARER_TOKEN` y las contraseñas por cuenta van solo en Environment variables de Portainer. No se copian al repositorio, no van dentro de la imagen y no se escriben en `accounts.toml`.

## 3. De dónde sale accounts.toml

El fichero montado gana. Si `/config/accounts.toml` existe, se usa ese y se ignoran las variables de texto. Si no existe, el entrypoint genera `/tmp/accounts.toml` (modo `0600`, tmpfs) y apunta `MCP_CONFIG` ahí. El texto generado no puede traer una clave `password`, solo `password_env`.

1. **Variable.** Prepara el TOML en tu máquina (hosts reales, `password_env`, sin secretos) y codifícalo:

   ```bash
   base64 -w0 accounts.toml
   ```

   Pega el resultado en `MCP_ACCOUNTS_TOML_B64`. No hace falta ningún fichero en el host.

2. **Bind relativo.** Descomenta en `docker-compose.yml` el volumen `./accounts.toml:/config/accounts.toml:ro`. El fichero tiene que estar junto al checkout del stack y no se commitea.

3. **Config de Docker.** Descomenta el bloque `configs:` del servicio y el de abajo del fichero (`file: ./accounts.toml`). El fichero tampoco lleva contraseñas.

`docker-compose.ficticio.yml` monta `accounts.example.toml` para una prueba local. No lo uses con datos reales.

## 4. TLS

El puerto publicado por defecto no lleva TLS: es loopback, para un proxy que ya esté en el mismo host.

**(a) Proxy que ya existe.** nginx, Nginx Proxy Manager, Traefik o Caddy en el host pueden hacer proxy a `http://127.0.0.1:8765`. El ejemplo de nginx del repositorio es `deploy/nginx-mcp.conf` (el `server_name` de ejemplo es `mcp.example.com`). Un proxy en otro contenedor no debe usar `127.0.0.1`: únete a la red del stack y apunta a `http://mcp:8765`. Si Traefik llega solo por esa red, comenta el bloque `ports:` de `mcp`. Las etiquetas Traefik están comentadas en el servicio, con el dominio `mcp.example.com` y la red externa `proxy`.

**(b) Caddy de este compose.** Perfil `tls`, apagado por defecto. En Portainer, si el formulario tiene perfiles, añade `tls`. En la máquina:

```bash
docker compose --profile tls up -d --build
```

`deploy/Caddyfile` usa `tls internal` para no pedir un certificado público al arrancar. Para el dominio real, borra esa línea, define `MCP_PUBLIC_HOST` con un nombre que resuelva a este servidor y deja libres 80 y 443. Caddy no lleva `cap_drop: ALL`: tiene que abrir esos puertos. El proceso MCP sí va sin capacidades.

Con el dominio público, `MCP_PUBLIC_HOST` deja pasar el `Host` de ese nombre y el origen `https://` correspondiente, y mantiene `127.0.0.1` para las pruebas en loopback.

## 5. Logs, auditoría y actualización

- Logs del proceso: en Portainer, el contenedor `mcp` → **Logs**. El driver `json-file` guarda como mucho 3 ficheros de 10 MiB.
- Auditoría: volumen nombrado `audit`, montado en `/var/log/mcp-correo`.

  ```bash
  docker compose exec mcp python -c "print(open('/var/log/mcp-correo/audit.jsonl').read())"
  ```

  `audit-rotate` renombra `audit.jsonl` a `.1`, `.2`, … al pasar de `MCP_AUDIT_MAX_BYTES` y borra lo que exceda `MCP_AUDIT_KEEP`. El servidor abre el fichero en cada línea, así que el renombrado no pierde la línea siguiente.

- Actualizar: en el stack, **Pull and redeploy**. Los secretos de Environment variables y el volumen `audit` se conservan. Para cambiar el token o una contraseña, edita la variable y vuelve a desplegar el stack. La imagen sigue sin secretos.

Límites del servicio `mcp`: 512 MiB, `pids_limit` 128, `restart: unless-stopped`, raíz de solo lectura, tmpfs en `/tmp` (`noexec`, `nosuid`), `cap_drop: ALL` y `no-new-privileges`.

La unidad systemd no usa este compose. Si despliegas con systemd, el proceso sigue en `127.0.0.1:8765` con un solo worker. Ver [despliegue-systemd.md](despliegue-systemd.md).
