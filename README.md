# mcp-correo

Interfaz [MCP](https://modelcontextprotocol.io) sobre IMAP y SMTP. Un asistente puede leer el correo y, solo con una orden explícita de quien lo opera, enviar, marcar como leído y eliminar.

El proceso habla el protocolo MCP por HTTP. El buzón sigue siendo un servidor IMAP/SMTP normal: este proyecto no lo administra.

## Por qué existe

Muchos agentes solo pueden salir a Internet por HTTPS, el puerto 443. No abren IMAP (993) ni SMTP (465 o 587), así que no llegan al buzón por sí solos.

mcp-correo corre en un servidor propio. El cliente del asistente se conecta a ese proceso por HTTPS. El proceso, en la red donde sí hay correo, habla IMAP y SMTP. El asistente no guarda la contraseña del buzón: la guarda este servidor, y el cliente solo presenta un Bearer.

## Características

- Lectura IMAP con `EXAMINE` y `BODY.PEEK`: listar, buscar y leer no marca los mensajes como leídos.
- Envío SMTP (`ssl` en el 465 o `starttls` en el 587), con respuesta (`In-Reply-To` / `References`), adjuntos limitados y copia en Enviados.
- Marcar leído o no leído, borrar a la Papelera (o de forma definitiva solo si se pidió al preparar) y guardar borradores.
- Cada capacidad de escritura tiene un interruptor global y otro por cuenta. Apagados, la tool no se registra.
- Enviar y borrar piden confirmación en dos pasos. El token dura 10 minutos, es de un solo uso y queda ligado a la cuenta y a la operación.
- Varias cuentas en un TOML. La contraseña no va en el fichero: solo el nombre de una variable de entorno.
- Auditoría JSONL de cada llamada, sin cuerpos ni credenciales.
- Transporte Streamable HTTP, un solo worker de uvicorn.

## Tools

La lectura está siempre disponible. La escritura solo aparece si el interruptor global y `allow_*` de al menos una cuenta están en `true`.

| Tool | Modo | Interruptor |
| --- | --- | --- |
| `list_accounts` | lectura | siempre |
| `list_folders` | lectura | siempre |
| `list_messages` | lectura | siempre |
| `search_messages` | lectura | siempre |
| `get_message` | lectura | siempre |
| `get_attachment` | lectura | siempre |
| `find_unanswered` | lectura | siempre |
| `list_threads` | lectura | siempre |
| `prepare_send` | preparación, no envía | `enable_send` y `allow_send` |
| `send_message` | escritura | los mismos, más `confirm_token` |
| `mark_read` | escritura | `enable_mark` y `allow_mark` |
| `mark_unread` | escritura | `enable_mark` y `allow_mark` |
| `prepare_delete` | preparación, no borra | `enable_delete` y `allow_delete` |
| `delete_message` | escritura | los mismos, más `confirm_token` |
| `create_draft` | escritura | `enable_drafts` y `allow_drafts` |

`prepare_send` devuelve la vista previa y un `confirm_token`. `send_message` solo acepta la cuenta y ese token: no se pueden cambiar destinatarios ni asunto en el segundo paso. Con el borrado pasa lo mismo: `permanent` se fija en `prepare_delete` y viaja dentro del token. Marcar es directo y queda auditado. `create_draft` guarda en Borradores y no envía.

## Seguridad

- **Bearer.** `MCP_BEARER_TOKEN` es obligatorio (mínimo 16 caracteres). Se compara el SHA-256 con `hmac.compare_digest`. Sin token, `/mcp` responde 401. `GET /health` responde `{"status":"ok"}` y no devuelve correo: es la sonda del contenedor.
- **Solo lectura por defecto.** `enable_send`, `enable_mark`, `enable_delete` y `enable_drafts` salen en `false`, y cada cuenta repite `allow_*`. Un texto `"false"` no enciende un interruptor: el proceso no arranca. Hace falta un booleano.
- **Confirmación en dos pasos.** Enviar y borrar no se ejecutan con la primera llamada. El token caduca, no se reutiliza y no sirve para otra cuenta ni para otra operación. El cupo diario solo cuenta un envío que el SMTP aceptó.
- **Auditoría sin cuerpos.** Cada línea anota fecha, tool, cuenta y argumentos reducidos (destinatarios o UID, asunto, nombres de fichero). No anota cuerpos, adjuntos, el `confirm_token` ni contraseñas. Si no puede escribir la línea, la tool no muta el buzón ni emite un token.
- **Inyección de instrucciones.** Asuntos, cuerpos y nombres de adjunto son datos no confiables. Las instrucciones del servidor dicen que un correo no es una orden: `send_message` y `delete_message` solo tras una orden explícita de quien opera el asistente, en esa conversación, después de ver la vista previa.
- **Red.** Por defecto el proceso escucha en `127.0.0.1`. Otro host exige `MCP_ALLOW_NONLOCAL_BIND=1`. `allowed_hosts` y `allowed_origins` cortan el DNS rebinding. Hacia Internet hace falta TLS en un proxy. Un solo worker: los tokens y el cupo viven en memoria.

La checklist de quien despliega está en [docs/seguridad.md](docs/seguridad.md).

## Arquitectura

```mermaid
flowchart LR
  asistente[Asistente]
  cliente[Cliente MCP]
  proxy[Proxy TLS]
  mcp[mcp-correo]
  imap[Servidor IMAP]
  smtp[Servidor SMTP]

  asistente --> cliente
  cliente -->|"HTTPS 443"| proxy
  proxy -->|"HTTP loopback"| mcp
  mcp -->|"IMAPS 993"| imap
  mcp -->|"SMTPS 465 o STARTTLS 587"| smtp
```

El asistente solo necesita el puerto 443 hacia el proxy. IMAP y SMTP salen de mcp-correo, en la máquina donde el buzón es alcanzable. La lectura usa `EXAMINE`. La escritura abre la carpeta en lectura-escritura solo dentro de la operación que lo necesita. El `From` de un envío es el usuario de la cuenta.

## Inicio rápido

Hace falta Python 3.11 o superior. Los ejemplos usan `example.com` y contraseñas ficticias. No abras IMAP hasta que sustituyas el host por el de tu buzón: con el ejemplo, `tools/list` arranca igual.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export MCP_BEARER_TOKEN="$(openssl rand -base64 48)"
export MAIL_PRINCIPAL_PASSWORD='contraseña-ficticia-principal'
export MAIL_ARCHIVO_PASSWORD='contraseña-ficticia-archivo'
export MCP_CONFIG=./accounts.example.toml
export MCP_AUDIT_LOG=./audit.jsonl
.venv/bin/python server.py
```

El proceso queda en `http://127.0.0.1:8765/mcp`.

Docker, también con el ejemplo ficticio y sin publicar el puerto fuera de loopback:

```bash
export MCP_BEARER_TOKEN="$(openssl rand -base64 48)"
export MAIL_PRINCIPAL_PASSWORD='contraseña-ficticia-principal'
export MAIL_ARCHIVO_PASSWORD='contraseña-ficticia-archivo'
docker compose -f docker-compose.yml -f docker-compose.ficticio.yml up --build
```

`docker-compose.ficticio.yml` solo monta `accounts.example.toml`. No lo uses con un buzón real. El despliegue en un servidor está en [docs/despliegue-portainer.md](docs/despliegue-portainer.md) y en [docs/despliegue-systemd.md](docs/despliegue-systemd.md).

## Configuración

Copia [accounts.example.toml](accounts.example.toml) a `accounts.toml` (ese fichero está en `.gitignore`) y cambia los hosts ficticios. La contraseña no se escribe ahí.

```toml
[server]
public_host = "mcp.example.com"
bind_host = "127.0.0.1"
bind_port = 8765
enable_send = false
enable_mark = false
enable_delete = false
enable_drafts = false

[accounts.principal]
label = "Correo principal — ejemplo ficticio"
imap_host = "mail.example.com"
imap_port = 993
imap_ssl = true
smtp_host = "mail.example.com"
smtp_port = 465
username = "ada@example.com"
password_env = "MAIL_PRINCIPAL_PASSWORD"
allow_send = false
allow_mark = false
allow_delete = false
allow_drafts = false
```

| Variable | Uso |
| --- | --- |
| `MCP_BEARER_TOKEN` | Obligatoria. En producción, `openssl rand -base64 48`. |
| `MAIL_PRINCIPAL_PASSWORD`, `MAIL_ARCHIVO_PASSWORD` | Contraseña de cada cuenta del ejemplo. El nombre real es el `password_env` del TOML. |
| `MCP_CONFIG` | Ruta del TOML. Si falta: `./accounts.toml` y luego `/etc/mcp-correo/accounts.toml`. |
| `MCP_AUDIT_LOG` | JSONL. Por defecto `./audit.jsonl`. |
| `MCP_BIND_HOST`, `MCP_BIND_PORT` | Por defecto `127.0.0.1` y `8765`. |
| `MCP_PUBLIC_HOST` | Si está definida, sustituye `public_host` y reconstruye hosts y orígenes permitidos. |
| `MCP_ALLOWED_HOSTS`, `MCP_ALLOWED_ORIGINS` | Listas separadas por comas. Tapan al TOML y a `MCP_PUBLIC_HOST`. |

Los topes (`max_results`, `max_chars`, `max_attachment_bytes`, destinatarios, cupo diario, UID por llamada) viven en `[server]` y el cliente no puede subirlos. El detalle de claves está comentado en el ejemplo.

## Conectar un cliente y probarlo

URL local: `http://127.0.0.1:8765/mcp`. Detrás de un proxy: `https://mcp.example.com/mcp`. Cabecera `Authorization: Bearer <token>`. Transporte Streamable HTTP.

Sin token la respuesta es 401 y el cuerpo no repite lo que se envió:

```bash
curl -i http://127.0.0.1:8765/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{}'
```

Con token, `tools/list` (modo sin estado). Con el ejemplo, son las ocho tools de lectura:

```bash
curl -sS http://127.0.0.1:8765/mcp \
  -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

MCP Inspector:

```bash
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8765/mcp \
  --transport http \
  --header "Authorization: Bearer $MCP_BEARER_TOKEN" \
  --method tools/list
```

En la UI, el mismo transporte, la misma URL y la cabecera `Authorization`. Para el Inspector abierto en el navegador, deja `http://127.0.0.1:*` y `http://localhost:*` en `allowed_origins`.

Un `Host` que no esté permitido responde 421. Un `Origin` que no esté permitido responde 403.

## Estructura

```
server.py                 # MCPServer, Bearer y registro de tools
config.py                 # accounts.toml, interruptores y límites
audit.py                  # JSONL de cada llamada
mail/                     # IMAP, SMTP, MIME, confirmación y escritura
accounts.example.toml     # datos ficticios, escritura apagada
.env.example              # nombres de variables, valores ficticios
Dockerfile                # imagen slim, usuario mcp, sin secretos
docker-compose.yml        # stack de Portainer
docker/                   # entrada del contenedor y rotación del JSONL
deploy/                   # systemd, nginx, Caddy opcional y logrotate
docs/                     # despliegue y checklist
tests/                    # pytest con IMAP y SMTP simulados, sin red
```

## Desarrollo y tests

No hace falta red ni un buzón real. El doble de IMAP marca `\Seen` si alguien pide el cuerpo sin `PEEK`. El doble de SMTP no abre un socket.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

CI hace lo mismo con Python 3.12.

## Hoja de ruta

- Particularidades de buzones Zextras Carbonio (nombres de carpetas y convenciones), sobre el mismo IMAP/SMTP.
- OAuth 2.1, con el SDK como resource server, si un cliente no acepta un Bearer estático.
- Pool de conexiones IMAP. IDLE queda fuera de momento.

## Licencia

[MIT](LICENSE). Copyright 2026 David Neyra.

## Despliegue

Los ejemplos de este repositorio no contienen un buzón real. El token y las contraseñas van en el entorno, nunca en git.

- [Portainer y Docker](docs/despliegue-portainer.md)
- [systemd y nginx](docs/despliegue-systemd.md)
- [Checklist de seguridad](docs/seguridad.md)
