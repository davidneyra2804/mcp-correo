# Configuración por variables de entorno

Todo el servidor se configura con variables de entorno. No hace falta ningún
fichero de configuración en la máquina: en Portainer se pega un `.env` en
*Environment variables → Load variables from .env file* y ya está.

## Dos fuentes, y cuál gana

| Fuente | Cuándo se usa | Precedencia |
| --- | --- | --- |
| Variables de entorno | Siempre que estén definidas | **Alta** |
| `accounts.toml` | Si existe y no hay cuentas por entorno | Baja |
| Defaults del código | Lo que no está en ninguna de las dos | Última |

Cada clave del servidor se resuelve por separado: entorno, luego TOML, luego
el default. Se pueden mezclar sin problema.

**Las cuentas, en cambio, vienen de una sola fuente.** Si `MCP_ACCOUNTS` está
definida, todas las cuentas salen del entorno y el TOML no cuenta. Si no está
definida, salen del TOML. Nunca se mezclan, porque una cuenta a medio
configurar es peor que no tenerla. Si existen las dos fuentes, el entorno gana
y el arranque avisa por log.

## Variables del servidor

| Variable | Tipo | Default | Qué hace |
| --- | --- | --- | --- |
| `MCP_BEARER_TOKEN` | texto | — | **Obligatoria.** El secreto que presenta el cliente MCP. Mínimo 16 caracteres. Sin ella el proceso no arranca. |
| `MCP_ACCOUNTS` | CSV de claves | — | Las cuentas configuradas. Sin ella y sin TOML, no hay cuentas. |
| `MCP_PUBLIC_HOST` | texto | `127.0.0.1` | El nombre público del servidor, el que va en el certificado TLS. Arma `allowed_hosts` y `allowed_origins`. |
| `MCP_ALLOWED_HOSTS` | CSV | derivado | Cabeceras `Host` permitidas. **Sustituye** a las derivadas de `MCP_PUBLIC_HOST` y a las del TOML. |
| `MCP_ALLOWED_ORIGINS` | CSV | derivado | Orígenes permitidos. Misma regla que arriba. |
| `MCP_BIND_HOST` | texto | `127.0.0.1` | Dirección de escucha. Fuera de loopback exige `MCP_ALLOW_NONLOCAL_BIND=1`. |
| `MCP_BIND_PORT` | entero | `8765` | Puerto de escucha. |
| `MCP_ENABLE_SEND` | bool | `false` | Interruptor global del envío. |
| `MCP_ENABLE_MARK` | bool | `false` | Interruptor global del marcado. |
| `MCP_ENABLE_DELETE` | bool | `false` | Interruptor global del borrado. |
| `MCP_ENABLE_DRAFTS` | bool | `false` | Interruptor global de los borradores. |
| `MCP_MAX_RESULTS` | entero | `100` | Mensajes por búsqueda. |
| `MCP_MAX_CHARS` | entero | `20000` | Caracteres de cuerpo por mensaje. |
| `MCP_MAX_ATTACHMENT_BYTES` | entero | `5000000` | Tamaño de un adjunto. |
| `MCP_MAX_MESSAGE_BYTES` | entero | `15000000` | Tamaño de un mensaje. |
| `MCP_IMAP_TIMEOUT` | float | `20` | Segundos de espera IMAP. |
| `MCP_SENT_SCAN_LIMIT` | entero | `300` | Mensajes de Enviados que se miran al buscar sin responder. |
| `MCP_CONFIRM_TTL_SECONDS` | entero | `600` | Vida del `confirm_token`. |
| `MCP_MAX_RECIPIENTS` | entero | `10` | Destinatarios por envío. |
| `MCP_MAX_SENDS_PER_DAY` | entero | `30` | Envíos por cuenta y día (UTC). Vive en memoria. |
| `MCP_MAX_DELETE_PER_CALL` | entero | `20` | Mensajes por llamada de borrado. |
| `MCP_MAX_MARK_PER_CALL` | entero | `50` | Mensajes por llamada de marcado. |
| `MCP_SMTP_TIMEOUT` | float | `30` | Segundos de espera SMTP. |
| `MCP_SMTP_SECURITY` | `ssl` \| `starttls` | `ssl` | Cómo se abre el SMTP. `ssl` es el 465, `starttls` el 587. |
| `MCP_ALLOWED_RECIPIENT_DOMAINS` | CSV de dominios | vacío | Destinatarios permitidos. **Vacío significa cualquier dominio**: conviene rellenarlo. |
| `MCP_ALLOWED_ATTACHMENT_TYPES` | CSV de tipos MIME | lista por defecto | Adjuntos permitidos. |
| `MCP_AUDIT_LOG` | ruta | `audit.jsonl` | Dónde se escribe el JSONL de auditoría. |

### Variables de solo Docker

No las lee el proceso, pero el compose las usa:

| Variable | Default | Para qué |
| --- | --- | --- |
| `MCP_IMAGE` | `mcp-correo:local` | Imagen publicada. Requiere `MCP_PULL_POLICY=always`. |
| `MCP_PULL_POLICY` | `build` | `build` en `mcp`, `never` en `audit-rotate`. `always` solo con `MCP_IMAGE`. |
| `MCP_PUBLISH_BIND` | `127.0.0.1` | Dirección del puerto publicado en el host. |
| `MCP_PUBLISH_PORT` | `8765` | Puerto publicado en el host. |
| `MCP_STACK_ENV_FILE` | `stack.env` | Fichero donde Portainer deja las variables del stack. |
| `MCP_AUDIT_MAX_BYTES` | `10485760` | Tamaño que dispara la rotación del JSONL. |
| `MCP_AUDIT_KEEP` | `12` | Copias que se conservan. |
| `MCP_AUDIT_ROTATE_SECONDS` | `3600` | Cada cuánto mira el rotador. |
| `CLOUDFLARE_TUNNEL_TOKEN` | — | Token del túnel, solo con `docker-compose.tunnel.yml`. |
| `CLOUDFLARE_TUNNEL_PROTOCOL` | `quic` | `quic` o `http2`, para redes que bloquean UDP. |

## Variables de cuenta

`MCP_ACCOUNTS` enumera las claves. Los campos van en
`MCP_ACCOUNT_<CLAVE>_<CAMPO>`, con la clave en mayúsculas y el prefijo
`MCP_ACCOUNT_`.

```bash
MCP_ACCOUNTS=principal,archivo
MCP_ACCOUNT_PRINCIPAL_IMAP_HOST=imap.corp.example.com
MCP_ACCOUNT_ARCHIVO_IMAP_HOST=imap.archivo.example.com
```

| Campo | Tipo | Default | Qué es |
| --- | --- | --- | --- |
| `LABEL` | texto | la clave | Nombre que ve el asistente en `list_accounts`. |
| `IMAP_HOST` | texto | — | **Obligatorio.** Servidor IMAP. |
| `IMAP_PORT` | entero | `993` | Puerto IMAP. |
| `IMAP_SSL` | bool | `true` | IMAP sobre TLS. |
| `SMTP_HOST` | texto | `IMAP_HOST` | Servidor SMTP. |
| `SMTP_PORT` | entero | `465` | Puerto SMTP. |
| `SMTP_SECURITY` | `ssl` \| `starttls` | el del servidor | Cómo se abre el SMTP de esta cuenta. |
| `USERNAME` | texto | — | **Obligatorio.** Usuario de la cuenta. |
| `PASSWORD` | texto | — | El secreto. O `PASSWORD_ENV`, nunca los dos. |
| `PASSWORD_ENV` | nombre de variable | — | Nombre de otra variable con el secreto. |
| `DRAFTS_FOLDER` | texto | `Drafts` | Carpeta de borradores. |
| `SENT_FOLDER` | texto | `Sent` | Carpeta de enviados. |
| `TRASH_FOLDER` | texto | — | Carpeta de papelera. Si se deja vacía, se busca una con el flag `\Trash`. |
| `ALLOW_SEND` | bool | `false` | Permite enviar con esta cuenta. |
| `ALLOW_MARK` | bool | `false` | Permite marcar con esta cuenta. |
| `ALLOW_DELETE` | bool | `false` | Permite borrar con esta cuenta. |
| `ALLOW_DRAFTS` | bool | `false` | Permite dejar borradores con esta cuenta. |

Una capacidad de escritura hace falta **las dos cosas**: el interruptor global
(`MCP_ENABLE_SEND`) y el permiso de la cuenta (`ALLOW_SEND`). Con cualquiera de
los dos apagado, la tool no se registra: no aparece en `tools/list` y no se
puede llamar.

## Cómo se interpretan los valores

**Booleanos.** Solo `true`, `false`, `1` y `0`, sin distinguir mayúsculas. Otro
texto aborta el arranque. La razón es concreta: con un fichero TOML, un
interruptor mal escrito era un error de sintaxis; con variables de entorno, un
`MCP_ENABLE_SEND=yes` se convertiría en "apagado" sin que nadie se enterase. El
proceso prefiere no arrancar antes que fingir que una capacidad está apagada.

**Listas.** Separadas por comas. Los espacios sobrantes se ignoran y los
elementos vacíos se descartan. Una lista vacía o ausente equivale a "no
definida": `MCP_ALLOWED_HOSTS` vacío deja que mande `MCP_PUBLIC_HOST`, y
`MCP_ALLOWED_RECIPIENT_DOMAINS` vacío deja pasar cualquier dominio.

**Vacío es "no definido".** Una variable presente pero vacía se trata como si
no existiera. Es lo que permite que el compose pase `MCP_PUBLIC_HOST: ${MCP_PUBLIC_HOST:-}`
sin que eso tape el valor de otra fuente.

**Números.** Enteros y decimales planos. `20`, `20.5`. Nada de `20s`.

## Errores de arranque y qué significan

El proceso no avisa y sigue: para. Cada mensaje dice qué corregir.

| Mensaje | Causa |
| --- | --- |
| `Falta MCP_BEARER_TOKEN` | No hay token, o está vacío. |
| `MCP_BEARER_TOKEN es demasiado corto` | Menos de 16 caracteres. |
| `MCP_ACCOUNTS tiene una clave de cuenta inválida` | Una clave con caracteres que no son letras, dígitos o guion bajo. |
| `MCP_ACCOUNTS repite la cuenta` | La misma clave dos veces. |
| `MCP_ACCOUNTS tiene dos cuentas que se escriben igual en mayúsculas` | `principal` y `PRINCIPAL` compartirían prefijo de variable. |
| `Variable de cuenta desconocida: MCP_ACCOUNT_PRINCIPAL_SENT_FOLDR` | Un nombre de campo mal escrito. El mensaje lista los válidos. |
| `MCP_ACCOUNT_ARCHIVO_USERNAME define la cuenta 'archivo', que no está en MCP_ACCOUNTS` | Hay campos de una cuenta que no declaraste. |
| `La cuenta 'principal' no tiene contraseña` | Faltan `PASSWORD` y `PASSWORD_ENV`. |
| `La cuenta 'principal' define PASSWORD y PASSWORD_ENV` | Las dos a la vez. |
| `Falta la variable de entorno MAIL_PRINCIPAL_PASSWORD` | `PASSWORD_ENV` apunta a una variable que no existe o está vacía. |
| `MCP_ENABLE_SEND debe ser true, false, 1 o 0` | Un interruptor mal escrito. |
| `No hay cuentas` | Ni `MCP_ACCOUNTS` ni `accounts.toml`. |
| `bind_host '0.0.0.0' no es loopback` | Falta `MCP_ALLOW_NONLOCAL_BIND=1`. En el contenedor lo pone el compose. |

## Cómo ver qué se ha cargado

En el arranque, el proceso dice de dónde salió la configuración:

```
INFO     Servidor listo: 2 cuentas, escucha 0.0.0.0:8765, escritura=apagada
INFO     Configuración: variables de entorno. Cuentas: archivo, principal
```

Y qué capacidades están encendidas, con la lista de cuentas:

```bash
docker compose exec mcp python -c "print(open('/var/log/mcp-correo/audit.jsonl').read())"
```

`list_accounts` devuelve, por cuenta, lo que puede hacer (`can_send`, `can_mark`,
`can_delete`, `can_draft`). Es la forma rápida de comprobar que los
interruptores y los permisos están donde deben.

## `accounts.toml`, el camino antiguo

Sigue funcionando, y es lo que usa el despliegue con systemd. Pero en
Portainer no hace falta: `MCP_ACCOUNTS_TOML_B64` y `MCP_ACCOUNTS_TOML` siguen
aceptados como alternativa para quien no pueda usar `stack.env`.

La diferencia entre las dos formas:

| | `accounts.toml` | Variables de entorno |
| --- | --- | --- |
| Tipos | Los distingue el parser | Todos son texto; los valida el código |
| Comentarios | Sí | Sí, en el `.env` |
| Errores | En el arranque, con el número de línea | En el arranque, con el nombre de la variable |
| Portainer | Hay que generarlo y codificarlo | Se pega el `.env` |

El proyecto se mueve al entorno porque es lo que permite desplegar en
Portainer sin tocar ficheros.
