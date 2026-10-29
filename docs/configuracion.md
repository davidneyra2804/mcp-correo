# Configuración

El servidor se configura mediante variables de entorno. Los dominios, cuentas,
contraseñas y credenciales específicas se gestionan desde el [panel](dashboard.md)
y se guardan en SQLite. Una instalación nueva empieza sin cuentas.

## Variables obligatorias

| Variable | Uso |
| --- | --- |
| `MCP_BEARER_TOKEN` | Credencial general del MCP, mínimo 16 caracteres. |
| `MCP_DASHBOARD_KEY` | Clave de cifrado de las contraseñas, mínimo 16 caracteres. Guárdala aparte de la base de datos. |
| `MCP_DASHBOARD_TOKEN` | Credencial del panel, mínimo 16 caracteres y distinta del bearer MCP. |

Genera cada secreto de forma independiente con `openssl rand -base64 48`.
Sin la clave de cifrado no se pueden recuperar las contraseñas guardadas.

## Red y panel

| Variable | Valor por defecto | Uso |
| --- | --- | --- |
| `MCP_PUBLIC_HOST` | `127.0.0.1` | Host público usado para derivar hosts y orígenes permitidos. |
| `MCP_ALLOWED_HOSTS` | derivado | Lista separada por comas que sustituye los hosts derivados. |
| `MCP_ALLOWED_ORIGINS` | derivado | Lista separada por comas que sustituye los orígenes derivados. |
| `MCP_BIND_HOST`, `MCP_BIND_PORT` | `127.0.0.1`, `8765` | Escucha del MCP; compose los fija dentro del contenedor. |
| `MCP_DASHBOARD_BIND_HOST`, `MCP_DASHBOARD_BIND_PORT` | `127.0.0.1`, `8766` | Escucha del panel; compose los fija dentro del contenedor. |
| `MCP_ALLOW_NONLOCAL_BIND` | sin definir | `1` permite escuchar fuera de loopback. |
| `MCP_DASHBOARD_DB` | `cuentas.db` | Ruta de SQLite; compose usa `/var/lib/mcp-correo/cuentas.db` en el volumen `data`. |
| `MCP_AUDIT_LOG` | `audit.jsonl` | Ruta del JSONL de auditoría. |

Mantén el panel en loopback o protégelo mediante un acceso privado. La base
debe persistir y respaldarse junto con una copia separada de la clave.

## Permisos y límites

`MCP_ENABLE_SEND`, `MCP_ENABLE_MARK`, `MCP_ENABLE_DELETE`,
`MCP_ENABLE_DRAFTS` y `MCP_ENABLE_DIRECT_SEND` son interruptores globales,
apagados por defecto. Solo admiten `true`, `false`, `1` y `0`. Los permisos
de dominio y cuenta se configuran en el panel y no pueden saltarse un
interruptor global apagado.

`MCP_ENABLE_DIRECT_SEND` habilita el envío en una sola llamada, sin
`confirmation_id` y sin confirmación humana por mensaje. Es para rutinas
automáticas que ya tienen la autorización de antemano. El permiso por
cuenta es `allow_direct_send` y es independiente de `allow_send`: una
cuenta puede tener los dos, o solo uno.

| Variable | Valor por defecto |
| --- | --- |
| `MCP_MAX_RESULTS` | `100` |
| `MCP_MAX_CHARS` | `20000` |
| `MCP_MAX_ATTACHMENT_BYTES` | `5000000` |
| `MCP_MAX_MESSAGE_BYTES` | `15000000` |
| `MCP_IMAP_TIMEOUT` | `20` segundos |
| `MCP_SENT_SCAN_LIMIT` | `300` |
| `MCP_CONFIRM_TTL_SECONDS` | `600` |
| `MCP_MAX_RECIPIENTS` | `10` |
| `MCP_MAX_SENDS_PER_DAY` | `30` |
| `MCP_MAX_DELETE_PER_CALL` | `20` |
| `MCP_MAX_MARK_PER_CALL` | `50` |
| `MCP_SMTP_TIMEOUT` | `30` segundos |
| `MCP_SMTP_SECURITY` | `ssl`; también admite `starttls` |
| `MCP_ALLOWED_RECIPIENT_DOMAINS` | vacío: cualquier dominio; lista separada por comas |
| `MCP_ALLOWED_ATTACHMENT_TYPES` | lista MIME por defecto; se puede sustituir con una lista separada por comas |

## Docker y despliegue

`.env.example` documenta las opciones de Compose, rotación, Cloudflare Tunnel
y Caddy. Copia el ejemplo a `.env` y reemplaza los secretos ficticios. El
compose publica el MCP y el panel en loopback y monta los volúmenes `data` y
`audit`. Para despliegue remoto consulta [Portainer](despliegue-portainer.md)
y [Cloudflare Tunnel](despliegue-tunel-cloudflare.md).

---
mcp-correo 2.1.0 | [Inicio](../README.md)
