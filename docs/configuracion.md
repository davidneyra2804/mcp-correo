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

**Las cuentas, en cambio, vienen de una sola fuente.** Si hay variables
`MCP_ACCOUNT_<CAMPO>_<N>` en el entorno, las cuentas salen de ahí y el TOML no
cuenta. Si no hay ninguna, salen del TOML. Nunca se mezclan, porque una cuenta
a medio configurar es peor que no tenerla. Si existen las dos fuentes, el
entorno gana y el arranque avisa por log.

## Variables del servidor

| Variable | Tipo | Default | Qué hace |
| --- | --- | --- | --- |
| `MCP_BEARER_TOKEN` | texto | — | **Obligatoria.** El secreto que presenta el cliente MCP. Mínimo 16 caracteres. Sin ella el proceso no arranca. |
| `MCP_ACCOUNTS` | CSV de índices | — | Opcional. Comprobación cruzada de qué cuentas existen. |
| `MCP_PUBLIC_HOST` | texto | `127.0.0.1` | El nombre público del servidor, el que va en el certificado TLS. Arma `allowed_hosts` y `allowed_origins`. |
| `MCP_ALLOWED_HOSTS` | CSV | derivado | Cabeceras `Host` permitidas. **Sustituye** a las derivadas de `MCP_PUBLIC_HOST` y a las del TOML. Si la defines y no incluye el host público, el túnel da 421. |
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
| `MCP_SMTP_SECURITY` | `ssl` \| `starttls` | `ssl` | Cómo se abre el SMTP de las cuentas que **no** fijan `SMTP_USE_SSL`. `ssl` es el 465, `starttls` el 587. |
| `MCP_ALLOWED_RECIPIENT_DOMAINS` | CSV de dominios | vacío | Destinatarios permitidos al **enviar**. **Vacío significa cualquier dominio**: conviene rellenarlo. No aplica a los borradores, que no se envían. |
| `MCP_ALLOWED_ATTACHMENT_TYPES` | CSV de tipos MIME | lista por defecto | Adjuntos permitidos. |
| `MCP_AUDIT_LOG` | ruta | `audit.jsonl` | Dónde se escribe el JSONL de auditoría. |
| `MCP_CONFIG` | ruta | — | Dónde está el `accounts.toml`. Si se define y el fichero no existe, se avisa y se sigue con la configuración por entorno. |
| `MCP_ALLOW_NONLOCAL_BIND` | `1` | sin definir | Permite escuchar fuera de loopback. **El compose lo pone**: en el contenedor hace falta, porque el proxy o el túnel llegan por la red de Docker. |

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
| `CLOUDFLARED_VERSION` | `latest` | Versión de la imagen `cloudflared`. |
| `CADDY_HTTP_BIND` / `CADDY_HTTPS_BIND` | `0.0.0.0` | Dónde publica Caddy los puertos 80 y 443. Solo con `docker-compose.proxy.yml`. |

Y dos que solo tienen sentido en el contenedor:

| Variable | Default | Para qué |
| --- | --- | --- |
| `MCP_ACCOUNTS_TOML_B64` | — | El `accounts.toml` en base64, para quien no pueda usar `stack.env`. Sin contraseñas: solo `password_env`. |
| `MCP_ACCOUNTS_TOML` | — | Lo mismo, pero en texto plano en vez de base64. |
| `MCP_GENERATED_CONFIG` | `/tmp/accounts.toml` | Dónde se genera el TOML a partir de lo anterior. Vive en tmpfs, modo `0600`. |

## Variables de cuenta

Las cuentas se **numeran**. El nombre de la variable no cambia de una cuenta
a otra: solo el número final. `MCP_ACCOUNT_<CAMPO>_<N>`, con N = 1, 2, 3...

```bash
MCP_ACCOUNT_USERNAME_1=ada@example.com
MCP_ACCOUNT_INBOX_HOST_1=imap.corp.example.com
MCP_ACCOUNT_PASSWORD_1=la-clave

MCP_ACCOUNT_USERNAME_2=luis@example.com
MCP_ACCOUNT_INBOX_HOST_2=imap.otro.example.com
MCP_ACCOUNT_PASSWORD_2=otra-clave
```

Para añadir una cuenta se copia el bloque y se cambia el número. No hay que
declararla en ninguna lista: el servidor las descubre todas. `MCP_ACCOUNTS` es
**opcional** y sirve como comprobación cruzada: si la defines, tiene que
coincidir con las cuentas que existen. Si no cuadra, **el arranque falla**
(ver [Errores de arranque](#errores-de-arranque)), no avisa y sigue: un
descuadre de cuentas es un error de configuración, no un aviso.

| Campo | Tipo | Default | Qué es |
| --- | --- | --- | --- |
| `NAME` | texto | el correo | Identificador de la cuenta en las rutas. Solo hace falta si dos cuentas comparten correo. |
| `LABEL` | texto | el identificador | Nombre que ve el asistente en `list_accounts`. |
| `INBOX_TYPE` | `imap` | `imap` | Protocolo de entrada. Solo se admite IMAP. |
| `INBOX_HOST` | texto | — | **Obligatorio.** Servidor IMAP. |
| `INBOX_PORT` | entero | `993` | Puerto IMAP. |
| `INBOX_USE_SSL` | bool | `true` | IMAP sobre TLS. `false` es IMAP en claro. |
| `SMTP_HOST` | texto | `INBOX_HOST` | Servidor SMTP. |
| `SMTP_PORT` | entero | `465` | Puerto SMTP. |
| `SMTP_USE_SSL` | bool | `true` | `true` es SMTPS (465). `false` es STARTTLS, normalmente con el 587. |
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
| `BEARER` | texto | — | Credencial propia de la cuenta. Ver [Rutas](#rutas). |

Una capacidad de escritura hace falta **las dos cosas**: el interruptor global
(`MCP_ENABLE_SEND`) y el permiso de la cuenta (`ALLOW_SEND`). Con cualquiera de
los dos apagado, la tool no se registra: no aparece en `tools/list` y no se
puede llamar.

## Rutas

El servidor expone dos formas de entrar:

| Ruta | Credencial | Qué ve |
| --- | --- | --- |
| `/mcp` | `MCP_BEARER_TOKEN` | Todas las cuentas. |
| `/mcp/<cuenta>` | `MCP_BEARER_TOKEN` o el `BEARER` de esa cuenta | Solo esa cuenta. |

`<cuenta>` identifica la cuenta de tres maneras, indistintas:

- el correo (`ada@example.com`),
- el `NAME` que le hayas puesto (`principal`),
- su número (`1`).

Con el bearer global, la ruta acota: `/mcp` ve todas y `/mcp/ada@example.com`
ve una. Con el bearer de una cuenta, la ruta tiene que ser la suya: en
cualquier otra responde **403**. En `/mcp` un bearer de cuenta no vale.

El aislamiento no es cosmético. Una tool que pida una cuenta fuera del ámbito
falla con un error, y `list_accounts` solo devuelve las cuentas de la ruta.

Para dar a un cliente una sola cuenta y que no pueda ver las demás, se le
entrega su `BEARER` y se le apunta a `/mcp/<cuenta>`:

```bash
# En el stack
MCP_ACCOUNT_BEARER_1=bearer-solo-de-la-cuenta-1-0123456789abcdef
```

```bash
# En el cliente
https://mcp.example.com/mcp/ada@example.com
Authorization: Bearer bearer-solo-de-la-cuenta-1-0123456789abcdef
```

El `BEARER` de una cuenta:

- es opcional: sin él, la cuenta solo se alcanza con el bearer global,
- necesita al menos 16 caracteres,
- no puede ser igual al bearer global (si lo fuera, la ruta no aislaría nada),
- no puede repetirse entre cuentas.

| Situación | Respuesta |
| --- | --- |
| Sin cabecera `Authorization` | 401 |
| Bearer que no es ninguno de los conocidos | 401 |
| Bearer de una cuenta en `/mcp` o en la ruta de otra | 403 |
| Bearer global en `/mcp/<cuenta>` de otra | 404 |
| `/health` | 200, sin token |
| Ruta que no es `/mcp`, `/mcp/<algo>` ni `/health` | 404 |


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
| `Variable de cuenta desconocida: MCP_ACCOUNT_INBOX_HOSTNAME_1` | Un nombre de campo mal escrito, o sin el número de cuenta. |
| `La cuenta 2 necesita MCP_ACCOUNT_INBOX_HOST_2` | Falta un campo obligatorio. |
| `La cuenta 2 no tiene contraseña` | Faltan `PASSWORD` y `PASSWORD_ENV`. |
| `La cuenta 2 define MCP_ACCOUNT_PASSWORD_2 y MCP_ACCOUNT_PASSWORD_ENV_2` | Las dos a la vez. |
| `Falta la variable de entorno MAIL_PRINCIPAL_PASSWORD` | `PASSWORD_ENV` apunta a una variable que no existe o está vacía. |
| `El bearer de la cuenta X es el mismo que MCP_BEARER_TOKEN` | El aislamiento por ruta no aislaría nada. |
| `Las cuentas X e Y comparten el mismo bearer` | Cada cuenta necesita el suyo. |
| `MCP_ACCOUNT_BEARER_1 es demasiado corto` | Menos de 16 caracteres. |
| `Dos cuentas comparten el nombre X` | Dos cuentas con el mismo correo. Distingue una con `MCP_ACCOUNT_NAME_<N>`. |
| `MCP_ACCOUNTS no lista la cuenta 2, que sí tiene variables` | La comprobación cruzada no cuadra. |
| `MCP_ENABLE_SEND debe ser true, false, 1 o 0` | Un interruptor mal escrito. |
| `No hay cuentas` | Ni variables de cuenta ni `accounts.toml`. |
| `bind_host '0.0.0.0' no es loopback` | Falta `MCP_ALLOW_NONLOCAL_BIND=1`. En el contenedor lo pone el compose. |

## Cómo ver qué se ha cargado

En el arranque, el proceso dice de dónde salió la configuración:

```
INFO     Escritura activa: ninguna
INFO     Servidor listo: 2 cuentas, escucha 0.0.0.0:8765, escritura=apagada
INFO     mcp-correo 1.0.5 | Configuración: variables de entorno. Cuentas: archivo, principal
```

La línea de capacidades (`Escritura activa: ...`) dice qué tools de escritura
están registradas. Es la forma rápida de comprobar que los interruptores
globales están donde deben.

Y la auditoría, que deja una línea por llamada:

```bash
docker compose exec mcp python -c "print(open('/var/log/mcp-correo/audit.jsonl').read())"
```

`list_accounts` devuelve, por cuenta, lo que puede hacer (`can_send`, `can_mark`,
`can_delete`, `can_draft`). Es la otra forma de comprobar que los permisos por
cuenta están donde deben.

## `accounts.toml`, el camino antiguo

Sigue funcionando, y es lo que usa el despliegue con systemd. Pero en
Portainer no hace falta: `MCP_ACCOUNTS_TOML_B64` y `MCP_ACCOUNTS_TOML` siguen
aceptados como alternativa para quien no pueda usar `stack.env`.

La diferencia entre las dos formas:

| | `accounts.toml` | Variables de entorno |
| --- | --- | --- |
| Tipos | Los distingue el parser | Todos son texto; los valida el código |
| Cuentas | Una tabla `[accounts.clave]` por cuenta | Una variable por campo, numerada |
| Comentarios | Sí | Sí, en el `.env` |
| Errores | En el arranque, con el número de línea | En el arranque, con el nombre de la variable |
| Portainer | Hay que generarlo y codificarlo | Se pega el `.env` |

El proyecto se mueve al entorno porque es lo que permite desplegar en
Portainer sin tocar ficheros.
