# Plan: panel de control y cuentas dinámicas

Este documento es el plan de integración de una segunda superficie HTTP, la
del **panel de control**, y del paso de las cuentas de "variables de entorno"
a "base de datos consultable en tiempo real".

No está implementado. Es el contrato que se va a seguir al escribir código,
y la lista de cosas que hay que decidir antes de empezar.

## 1. El objetivo, en una frase

Que las cuentas de correo se puedan **crear, cambiar y quitar desde una
interfaz web**, sin reiniciar el servidor, y que en cuanto existen estén
expuestas en `/mcp` con su propio aislamiento y su propia credencial.

## 2. La idea, traducida a este código

Lo que se pide tiene cinco piezas. Cada una encaja con algo que ya existe:

| Lo que se pide | Qué es en este repositorio hoy | Qué hay que cambiar |
| --- | --- | --- |
| Un segundo puerto, solo para el panel | El servidor MCP escucha en `MCP_BIND_PORT` (8765) y expone `/mcp` y `/health` | Un segundo servidor HTTP, en otro puerto, con su propia autenticación |
| Gestión dinámica de las cuentas | Las cuentas son `MCP_ACCOUNT_<CAMPO>_<N>` en el entorno, fijas al arrancar | Las cuentas pasan a una base de datos; el proceso las lee en cada petición |
| SQLite | No hay base de datos | Un fichero SQLite, con esquema, migraciones y cifrado |
| Organizar por dominios | No hay el concepto de dominio | Una tabla de dominios y otra de cuentas, muchas cuentas por dominio |
| Exposición en tiempo real por `/mcp` | El enrutado resuelve contra un diccionario congelado al arrancar | El enrutado resuelve contra una fuente que se recarga |
| Token por cuenta | `MCP_ACCOUNT_BEARER_<N>` ya existe | Se genera y se rota desde el panel; sigue valiendo solo en su ruta |
| Token por dominio | No existe | Un token que abre todas las cuentas de un dominio, y solo en sus rutas |

Lo importante: **nada de esto rompe lo que ya funciona**. El panel es
opt-in. Si no se activa, el servidor se comporta exactamente igual que hoy,
con las cuentas del entorno y sin base de datos.

## 3. Decisiones que toma este plan

Cada una con su porqué. Las que quedan abiertas están al final (§16).

### 3.1 El panel es opt-in

Se activa con una sola variable: `MCP_DASHBOARD_DB` (la ruta del fichero
SQLite). Si no está, no hay panel, no hay base de datos y el arranque es el
de hoy.

El motivo es concreto: el despliegue actual (Portainer + túnel) funciona y
está en producción. Una cambios de contrato de configuración no puede
convertir un despliegue existente en uno que no arranca.

### 3.2 Un proceso, dos puertos

El MCP sigue siendo el proceso principal. El panel se levanta como un
segundo servidor `uvicorn` en un hilo aparte, dentro del mismo proceso.

La alternativa (dos contenedores) también es posible con el mismo código: el
panel es un módulo ejecutable y la base de datos es un fichero. Se deja la
puerta abierta, pero el proceso único es el recomendado por dos razones:

- El **token de confirmación** y el **cupo diario de envíos** viven en
  memoria. Con dos procesos habría que compartirlos o duplicarlos, y el
  duplicado es un cupo que se cuenta dos veces.
- La invalidación de la caché de cuentas es una llamada a una función, no un
 Watcher de ficheros.

Que el panel viva en el mismo contenedor **no significa que esté
expuesto**: el puerto se publica solo en loopback, o no se publica.

### 3.3 La base de datos es la única fuente de las cuentas

Cuando el panel está activo, las cuentas salen de la base de datos. Las del
entorno no se mezclan: mezclarlas es exactamente el problema que ya está
resuelto hoy con el TOML ("una cuenta a medio configurar es peor que no
tenerla").

Al primer arranque, si la base de datos está **vacía**, las cuentas del
entorno o del TOML se **importan** (una por dominio de correo) para que un
despliegue existente no se quede sin buzones. A partir de ahí, la base de
datos manda y el entorno se ignora, y el arranque lo dice:

```
INFO     Cuentas importadas del entorno: 2 (dominio corp.example.com).
INFO     La base de datos es la fuente de las cuentas. Las del entorno se ignoran.
```

### 3.4 Las contraseñas se cifran en reposo

La base de datos guarda contraseñas de correo. En claro en un fichero, se
pueden leer con un `cat`, y además acabaría en una copia de seguridad sin
protección.

Se cifran con una clave que **no está en la base de datos**: la variable
`MCP_DASHBOARD_KEY`, obligatoria cuando el panel está activo. Se deriva con
HKDF y se cifra con AES-GCM (`cryptography`, que ya está en el entorno como
dependencia de `imapclient`, pero se declarará en `requirements.txt`).

Si la clave no corresponde a la base de datos, el arranque para y dice
exactamente eso. Perder la clave significa perder las contraseñas de la
base: no hay recuperación, y por eso el panel muestra la clave solo al
crearla y avisa de que hay que guardarla.

### 3.5 La clave de cifrado se valida contra la base de datos

En la tabla de metadatos se guarda una fila conocida, cifrada con la clave.
Al arrancar se descifra: si falla, la clave es otra y el proceso para con un
mensaje que lo diga. Sin esto, el síntoma sería "las cuentas no funcionan" y
nadie sabría si es la clave o el servidor IMAP.

### 3.6 La cadena de permisos grows un nivel: global → dominio → cuenta

Hoy la cadena es global → cuenta. Con los dominios, el dominio entra en
medio, y con la misma forma: el valor de arriba manda, el de abajo es un
override opcional, y "sin definir" significa heredar.

| | `MCP_ENABLE_SEND` (global) | `allow_send` del dominio | `allow_send` de la cuenta | Resultado |
| --- | --- | --- | --- | --- |
| 1 | `false` | lo que sea | lo que sea | **Apagada** |
| 2 | `true` | sin definir | sin definir | **Encendida** (hereda) |
| 3 | `true` | sin definir | `false` | **Apagada** para esa cuenta |
| 4 | `true` | `false` | lo que sea | **Apagada** en el dominio |
| 5 | `true` | `false` | `true` | **Apagada**: manda el dominio |

La regla vive en **un solo sitio** (`config.py`), que es la que usan tanto
el registro de tools como la comprobación por llamada. El dominio añade un
nivel, no una segunda implementación.

### 3.7 Los tokens siguen siendo de la cuenta, y el del dominio es una tercera capa

Tres niveles, con la misma idea que ya hay:

| Nivel | Dónde vive | Abre | En qué rutas vale |
| --- | --- | --- | --- |
| Global | `MCP_BEARER_TOKEN` | Todas las cuentas | `/mcp`, `/mcp/<cuenta>`, `/mcp/<dominio>` |
| De dominio | `domains.bearer` | Las cuentas de ese dominio | `/mcp/<dominio>`, `/mcp/<cuenta>` de ese dominio |
| De cuenta | `accounts.bearer` | Esa cuenta | `/mcp/<cuenta>` |

Reglas que se mantienen del diseño actual:

- Un token de cuenta en `/mcp` responde **403** (no es el global).
- Un token de dominio en `/mcp` responde **403** (tampoco es el global).
- Un token de cuenta en la ruta de otro dominio o de otra cuenta: **403**.
- Un token de dominio en la ruta de otro dominio: **403**.
- Un token que no existe: **401**.

Y una regla nueva, que es la que hace útil el token de dominio: el ámbito
de una ruta es la **intersección** de lo que la ruta expone y lo que el
token permite. Nunca la unión. Es el mismo principio que ya aplica el
aislamiento por cuenta, ampliado.

### 3.8 Los tokens no se repiten, en ningún nivel

Un token repetido entre dos cuentas, o entre una cuenta y un dominio, hace
que la ruta no aísle nada. Hoy eso aborta el arranque. En el panel, donde
los tokens se crean en caliente, no puede abortar el arranque: el alta se
rechaza con un mensaje que dice con qué choca.

### 3.9 El nombre de la cuenta es único en todo el servidor

La ruta es global (`/mcp/<cuenta>`), así que el identificador de cuenta no
puede repetirse: ni entre dominios, ni con el nombre de un dominio. El
panel lo rechaza al dar de alta.

### 3.10 El panel se ata al loopback y no se publica por defecto

El panel ve las contraseñas. Por defecto se escucha en `127.0.0.1` y el
compose no publica su puerto. Publicarlo es una decisión consciente, y
recomendada: solo detrás de Cloudflare Access o de un proxy con
autenticación propia.

### 3.11 El panel tiene su propia credencial, distinta de la del MCP

`MCP_DASHBOARD_TOKEN`, obligatoria con el panel activo, y distinta del
bearer global. El token del MCP no abre el panel, y el del panel no abre
`/mcp`. Son dos superficies con dos superficies de credencial.

## 4. Arquitectura: los dos puertos

```
                    ┌──────────────────────────────────────┐
                    │            proceso mcp-correo         │
   cliente MCP ────▶│ :8765  /mcp  /mcp/<cuenta>            │
                    │        /mcp/<dominio>  /health        │
                    │                                      │
   navegador ──────▶│ :8766  /  /api/...  /health          │
                    │        (sesión propia, CSRF)          │
                    └───────────────┬──────────────────────┘
                                    │
                              ┌─────▼─────┐
                              │  SQLite   │  (WAL)
                              │  cuentas  │
                              └───────────┘
```

- **:8765** — el MCP. Sin cambios en su contrato: `/mcp`, `/mcp/<cuenta>`,
  `/health`. Sigue siendo la superficie que consume un asistente.
- **:8766** — el panel. Solo interfaz web y su API. **No** registra tools,
  no habla con el SDK de MCP y no puede ejecutar nada del buzón.

El panel **no** puede leer ni escribir un buzón: solo gestiona la
configuración (dominios, cuentas, tokens). Esa frontera se mantiene a
propósito: un panel abierto no debe poder enviar correo.

### 4.1 Variables de escucha

| Variable | Default | Para qué |
| --- | --- | --- |
| `MCP_DASHBOARD_BIND_HOST` | `127.0.0.1` | Dirección de escucha del panel |
| `MCP_DASHBOARD_BIND_PORT` | `8766` | Puerto de escucha del panel |

Fuera de loopback exige `MCP_ALLOW_NONLOCAL_BIND=1`, como el MCP.

## 5. La base de datos

### 5.1 Fichero, permisos y modo

- Ruta: `MCP_DASHBOARD_DB`. En el contenedor, `/var/lib/mcp-correo/cuentas.db`,
  sobre un volumen.
- Permisos: `0600`, y el directorio `0700`. El usuario del sistema del
  contenedor (uid 10001) es el dueño.
- `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`,
  `PRAGMA busy_timeout=5000`.
- Una conexión por hilo (`threading.local`). Nunca se comparte una conexión
  entre el hilo del MCP y el del panel.

### 5.2 Esquema

```sql
CREATE TABLE domains (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,     -- corp.example.com
    label         TEXT    NOT NULL DEFAULT '',
    bearer        TEXT,                       -- NULL = sin token propio
    allow_send    INTEGER,                    -- NULL = sin definir (hereda)
    allow_mark    INTEGER,
    allow_delete  INTEGER,
    allow_drafts  INTEGER,
    imap_host     TEXT    NOT NULL DEFAULT '', -- default del dominio
    imap_port     INTEGER,
    imap_ssl      INTEGER,
    smtp_host     TEXT    NOT NULL DEFAULT '',
    smtp_port     INTEGER,
    smtp_security TEXT,
    created_at    TEXT    NOT NULL
);

CREATE TABLE accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id       INTEGER NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL UNIQUE,   -- identificador de ruta
    label           TEXT    NOT NULL DEFAULT '',
    sender          TEXT    NOT NULL DEFAULT '',
    username        TEXT    NOT NULL UNIQUE,
    password        BLOB    NOT NULL,          -- cifrado
    imap_host       TEXT    NOT NULL DEFAULT '',-- vacío = hereda el dominio
    imap_port       INTEGER,
    imap_ssl        INTEGER,
    smtp_host       TEXT    NOT NULL DEFAULT '',
    smtp_port       INTEGER,
    smtp_security   TEXT,
    drafts_folder   TEXT    NOT NULL DEFAULT '',
    sent_folder     TEXT    NOT NULL DEFAULT '',
    trash_folder    TEXT    NOT NULL DEFAULT '',
    allow_send      INTEGER,
    allow_mark      INTEGER,
    allow_delete    INTEGER,
    allow_drafts    INTEGER,
    bearer          TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

En `meta` van la versión del esquema (`schema_version`) y el **contador de
revisiones** (`revision`).

### 5.3 El contador de revisiones: cómo se sabe que algo cambió

Cada escritura del panel incrementa `meta.revision` en la misma transacción
que el cambio. El lector guarda la revisión que tiene en memoria y, antes
de servir una petición, la compara con la de la base de datos.

Es una consulta de una fila. Si ha cambiado, se recarga el conjunto de
cuentas y se rehacen los digest de los tokens.

Sirve igual dentro del proceso (el panel escribe, el MCP lee) y entre
procesos (dos contenedores sobre el mismo volumen), porque el contador está
en la base de datos, no en la memoria del proceso.

### 5.4 Migraciones

El esquema tiene versión. Al arrancar:

1. Se crea el esquema si no existe.
2. Se aplican las migraciones pendientes, en orden, cada una en su
   transacción.
3. La versión final se escribe en `meta.schema_version`.

Las migraciones son funciones numeradas en `store/db.py`, cada una con su
prueba. Una migración que falla deja la base como estaba: se aborta el
arranque con el nombre de la migración.

## 6. La cadena de permisos, en un solo sitio

Hoy `config.account_allows()` decide, y `MailboxWriter._gated()` la usa en
cada llamada. `write_capabilities()` la usa para registrar las tools.

Con el dominio de en medio, la regla se reparte en dos niveles distintos,
y cada nivel tiene su sitio:

- **Nivel global → dominio → cuenta**: qué valor gana. Vive en
  `config.resolve_permission(valor_cuenta, valor_dominio)`, que devuelve el
  tri-estado (`True` / `False` / `None` = heredar). La usa el cargador de la
  base de datos al construir cada `Account`, y no en ningún otro sitio.
- **Nivel "global apagado manda"**: ya existe, en `account_allows()`. No
  cambia.

El resultado es que `Account.allow_send` sigue siendo un tri-estado, y
`account_allows()` **no cambia una línea**. El cargador de la base de
datos deja el tri-estado ya resuelto: si la cuenta lo dice, el de la cuenta;
si no, el del dominio; si no, `None`.

## 7. Cuentas en tiempo real: el punto exacto del cambio

Hoy hay tres sitios que miran el conjunto de cuentas, y los tres reciben un
`dict` congelado al arrancar:

1. `MailService.accounts` — para resolver la cuenta de una llamada.
2. `BearerAuth._accounts` — para saber qué token es el presentado y qué
   rutas existen.
3. `build_mcp` — para registrar las tools de escritura.

El cambio es que los tres reciben una **fuente de cuentas**, no un
diccionario:

```python
class AccountSource(Protocol):
    def accounts(self) -> Mapping[str, Account]: ...
```

Dos implementaciones:

- `StaticAccounts` — el diccionario del entorno o del TOML. Inmutable.
  Es exactamente el comportamiento de hoy.
- `DatabaseAccounts` — lee de SQLite, cachea, y recarga cuando cambia la
  revisión.

`MailService.accounts` pasa a ser una propiedad que pregunta a la fuente.
Los tres call sites no cambian de forma, solo de origen.

### 7.1 Cuándo se recarga

En **cada petición** que llega al enrutador (`BearerAuth.__call__`), antes
de resolver la ruta. El coste es una lectura de una fila de `meta`. Con
decenas de cuentas, la recarga completa (cuando la hay) es de milisegundos.

Así, una cuenta creada en el panel está en `/mcp/<cuenta>` en la siguiente
petición. No hay reinicio, no hay caché que expire, no hay ventana de
inconsistencia.

### 7.2 Las tools de escritura y el registro

`build_mcp` decide qué tools de escritura se registran, y esa decisión se
toma **una vez**, al arrancar. Con cuentas dinámicas, el conjunto de cuentas
puede cambiar después, así que la regla del registro tiene que cambiar con
él.

- **Modo estático** (hoy): se registra una tool si el interruptor global
  está encendido **y alguna cuenta lo permite**. Si ninguna lo permite, la
  tool no existe.
- **Modo dinámico** (panel): se registra si el interruptor global está
  encendido. El permiso por cuenta se comprueba **en cada llamada**, que es
  donde se comprueba de todos modos (`MailboxWriter._gated`).

La diferencia es de descubrimiento, no de seguridad: en modo dinámico, una
tool puede existir y responder "el envío está desactivado para la cuenta X".
El permiso sigue decidiéndose en el servidor, en cada llamada.

La alternativa (volver a registrar las tools cuando cambia la base de
datos) se descarta a propósito: el registro de tools del SDK no es seguro
para cambios en caliente desde otro hilo, y el beneficio es de claridad, no
de control.

### 7.3 La auditoría conoce los secretos de las cuentas nuevas

`AuditLog` recibe hoy la lista de secretos al construirlo, y con eso
cifra (sustituye por `***`) cualquier aparición de una contraseña o un token
en la línea de auditoría.

Con cuentas dinámicas, esa lista cambia. `AuditLog` pasa a tener un
conjunto de secretos con cerrojo, y la fuente de cuentas da de alta los
nuevos cada vez que recarga. Sin esto, el token de una cuenta creada
después del arranque podría aparecer en el log.

## 8. Rutas y tabla de respuestas

Las rutas del MCP pasan a ser tres formas:

| Ruta | Qué expone |
| --- | --- |
| `/mcp` | Todas las cuentas |
| `/mcp/<cuenta>` | Una cuenta |
| `/mcp/<dominio>` | Las cuentas de un dominio |

`<cuenta>` se resuelve, en este orden:

1. El `name` de la cuenta (idéntico, sin distinguir mayúsculas).
2. El `username` de la cuenta.
3. El `name` de un dominio → todas sus cuentas.
4. Un número → el `id` de la cuenta.

Un `name` de cuenta tiene prioridad sobre un nombre de dominio, y el panel
no deja crear una cuenta con el nombre de un dominio ni al revés (§3.9).

### 8.1 Respuestas

| Situación | Respuesta |
| --- | --- |
| Sin cabecera `Authorization` | 401 |
| Token que no es ninguno de los conocidos | 401 |
| Token de cuenta en `/mcp` | 403 |
| Token de cuenta en `/mcp/<cuenta>` de otra | 403 |
| Token de cuenta en `/mcp/<dominio>` | 403 |
| Token de dominio en `/mcp` | 403 |
| Token de dominio en `/mcp/<dominio>` de otro | 403 |
| Token de dominio en `/mcp/<cuenta>` de otro dominio | 403 |
| Token global en `/mcp/<cuenta>` que no existe | 404 |
| Token global en `/mcp/<dominio>` que no existe | 404 |
| Ruta que no es `/mcp`, `/mcp/<algo>` ni `/health` | 404 |

El 403 y el 404 se mantienen como están: el 403 dice "tu credencial no vale
aquí" y el 404 dice "aquí no hay nada". No se mezclan.

## 9. El panel

### 9.1 Rutas

| Ruta | Método | Qué hace |
| --- | --- | --- |
| `/` | GET | El panel (o el login, si no hay sesión) |
| `/login` | GET | El formulario de acceso |
| `/login` | POST | Comprueba el token y abre sesión |
| `/logout` | POST | Cierra la sesión |
| `/api/domains` | GET | Lista los dominios con sus cuentas |
| `/api/domains` | POST | Crea un dominio |
| `/api/domains/{id}` | PATCH | Cambia un dominio |
| `/api/domains/{id}` | DELETE | Borra un dominio y sus cuentas |
| `/api/accounts` | POST | Crea una cuenta |
| `/api/accounts/{id}` | PATCH | Cambia una cuenta |
| `/api/accounts/{id}` | DELETE | Borra una cuenta |
| `/api/accounts/{id}/token` | POST | Genera un token nuevo para la cuenta |
| `/api/domains/{id}/token` | POST | Genera un token nuevo para el dominio |
| `/health` | GET | Sonda del panel |

La API **nunca** devuelve una contraseña. Al leer una cuenta, el campo de
la contraseña es `"password_set": true`. Al editarla, la contraseña solo se
cambia si se manda una nueva.

### 9.2 Autenticación

- `MCP_DASHBOARD_TOKEN`, obligatoria con el panel activo, mínimo 16
  caracteres, distinta del bearer global.
- El login compara con `hmac.compare_digest`.
- La sesión es una cookie firmada con HMAC (la misma clave del token), con
  caducidad, `HttpOnly` y `SameSite=Strict`.
- Las peticiones que mutan exigen una cabecera `X-MCP-Dashboard: 1`. Un
  formulario de otro sitio no puede poner una cabecera a medida, así que el
  CSRF queda cerrado sin token anti-CSRF adicional.

### 9.3 La interfaz

Una sola página, sin framework: HTML, CSS y JavaScript planos, servidos
como estáticos desde la imagen.

- Los dominios se listan como secciones, cada una con sus cuentas.
- Alta, edición y baja de dominio y de cuenta, en la misma página.
- Los tokens se generan con un botón y **se muestran una sola vez**.
- Las contraseñas se escriben en un campo de contraseña y nunca se
  devuelven.

El JavaScript es pequeño a propósito: el panel es una herramienta de
operación, no una aplicación.

### 9.4 Todo lo que hace el panel queda auditado

Cada alta, cambio, baja y rotación de token escribe una línea en el mismo
JSONL de auditoría, con `tool` propio (`dashboard_add_account`, etc.) y sin
secretos. La auditoría es el mismo sitio donde ya se mira qué ha pasado.

## 10. Mapa de módulos

Ficheros nuevos:

```
store/
  __init__.py
  db.py         # conexión, esquema, migraciones, revisión
  crypto.py     # cifrado y descifrado de contraseñas
  models.py     # dataclasses de dominio y de cuenta
  accounts.py   # DatabaseAccounts: la fuente de cuentas
  errors.py     # errores del panel, con mensajes accionables
dashboard/
  __init__.py
  app.py        # la app Starlette y el enrutado
  auth.py       # sesión firmada y comprobación de CSRF
  api.py        # los handlers JSON
  ui.py         # el HTML
  runner.py     # el segundo servidor uvicorn
  static/
    panel.html
    panel.css
    panel.js
```

Ficheros que cambian:

| Fichero | Qué cambia |
| --- | --- |
| `config.py` | `Account` gana `domain`; `resolve_permission()`; `write_capabilities(..., dynamic=)`; los ajustes del panel; `load_config()` no aborta sin cuentas en modo panel |
| `server.py` | `BearerAuth` consulta la fuente; token de dominio; resolución de la ruta; el hilo del panel |
| `mail/imap.py` | `MailService` recibe una fuente en vez de un diccionario |
| `audit.py` | Los secretos pasan a ser un conjunto con cerrojo, con `add_secret()` |
| `docker/entrypoint.py` | Nada: sigue preparando el TOML, y el panel no lo necesita |
| `docker/healthcheck.py` | Nuevo: comprueba el MCP y, si está, el panel |
| `Dockerfile` | Copia los paquetes nuevos y los estáticos; crea `/var/lib/mcp-correo`; `EXPOSE 8766` |
| `docker-compose.yml` | Variables del panel, volumen de datos, puerto del panel |

`scope.py` **no cambia**: el ámbito ya es un `frozenset` de claves de cuenta,
y un dominio no es más que un conjunto de cuentas.

## 11. Fases

Cada fase deja el repositorio en verde y se puede revisar por separado.

### Fase 1 — La fuente de cuentas

- `store/accounts.py` con `AccountSource` y `StaticAccounts`.
- `MailService` y `BearerAuth` pasan a consumir la fuente.
- `config.load_config()` sigue igual.

**Sale de aquí:** el conjunto de cuentas deja de ser un diccionario
congelado, sin cambiar ningún comportamiento. **Pruebas:** las existentes
siguen pasando sin tocarlas.

### Fase 2 — La base de datos

- `store/db.py`, `store/crypto.py`, `store/models.py`.
- El esquema, las migraciones, el cifrado, la validación de la clave.
- `DatabaseAccounts`: lee, cachea, resuelve la cadena de permisos.
- La importación inicial desde el entorno.

**Pruebas:** `tests/test_store.py` — esquema, migración, cifrado
(ida y vuelta, y clave equivocada), unicidad, la cadena de permisos, la
importación.

### Fase 3 — El tiempo real

- La comprobación de la revisión en cada petición.
- La recarga y el alta de secretos en la auditoría.
- El modo dinámico en `write_capabilities`.

**Pruebas:** `tests/test_dinamico.py` — una cuenta creada en la base está
en `/mcp/<cuenta>` en la siguiente petición; al borrarla, la ruta da 404;
el permiso por cuenta se sigue aplicando en la llamada.

### Fase 4 — El token de dominio

- La ruta `/mcp/<dominio>`.
- El token de dominio y la intersección de ámbitos.
- La unicidad de los tokens entre los tres niveles.

**Pruebas:** en `tests/test_dinamico.py`, la tabla de respuestas de §8.1
completa.

### Fase 5 — El panel

- La app, la autenticación, la API, la interfaz.
- La auditoría de las mutaciones.

**Pruebas:** `tests/test_dashboard.py` — login, sesión, CSRF, la API, que
la contraseña nunca sale, la auditoría, la generación de tokens.

### Fase 6 — Empaquetado y documentación

- El `Dockerfile`, el compose, el `healthcheck`.
- `docs/configuracion.md` (las variables nuevas), `docs/dashboard.md` (nuevo),
  el README, el CHANGELOG, el `.env.example`.

**Pruebas:** las de imagen, extendidas (§13).

## 12. Configuración nueva

| Variable | Default | Qué hace |
| --- | --- | --- |
| `MCP_DASHBOARD_DB` | — | Ruta del fichero SQLite. **Si está, el panel está activo.** |
| `MCP_DASHBOARD_KEY` | — | Clave de cifrado de las contraseñas. Obligatoria con el panel. Mínimo 16 caracteres. |
| `MCP_DASHBOARD_TOKEN` | — | Credencial de acceso al panel. Obligatoria con el panel. Mínimo 16 caracteres. |
| `MCP_DASHBOARD_BIND_HOST` | `127.0.0.1` | Dirección de escucha del panel. |
| `MCP_DASHBOARD_BIND_PORT` | `8766` | Puerto de escucha del panel. |
| `MCP_DASHBOARD_PUBLISH_PORT` | `8766` | Puerto publicado en el host. Solo con `MCP_DASHBOARD_PUBLISH=1`. |
| `MCP_DASHBOARD_PUBLISH` | `0` | Publica el puerto del panel. Por defecto no se publica. |

Las tres primeras son obligatorias en modo panel: si falta alguna, el
arranque para diciendo cuál falta y qué hacer. Nunca se arranca a medias.

## 13. Pruebas

Además de las de cada fase:

- **Imagen**: los paquetes `store` y `dashboard`, y los ficheros estáticos
  del panel, tienen que estar en la imagen. El test actual (`test_docker.py`)
  comprueba los módulos `.py` de la raíz; hay que **extenderlo a los
  paquetes y a los estáticos**, que es la trampa de siempre: un módulo que
  no llega a la imagen pasa los tests locales y revienta en el contenedor.
- **Arranque en la imagen**: la prueba que simula `/app` tiene que arrancar
  también el panel (con la base de datos en un `tmp_path`).
- **Healthcheck**: el script nuevo tiene que comprobar los dos puertos.
- **Datos ficticios**: los dominios y correos de las pruebas tienen que ser
  de los reservados (`example.com`, `example.org`, `example.net`, `*.test`).
  `tests/test_ficticio.py` lo comprueba en cada commit.
- **Documentación**: los tests que comprueban que el `.env.example` y el
  compose declaran todas las variables nuevas.

## 14. Seguridad

| Riesgo | Mitigación |
| --- | --- |
| El panel expone contraseñas | Contraseñas cifradas en reposo; el panel nunca las devuelve |
| El panel es una puerta trasera | Token propio, sesión firmada, `SameSite=Strict`, cabecera anti-CSRF, loopback por defecto |
| Un token repetido anula el aislamiento | Unicidad comprobada en los tres niveles, en el alta y en la carga |
| Un token de dominio abre de más | El ámbito es la intersección de la ruta y el token, nunca la unión |
| Fuga por la auditoría | Los secretos de las cuentas nuevas se dan de alta en el `AuditLog` al recargar |
| La base de datos en una copia de seguridad | Cifrada con una clave que no está en el fichero |
| SQLite con dos escritores | WAL, `busy_timeout`, transacciones cortas |
| El panel publica un puerto por error | No se publica por defecto; `MCP_DASHBOARD_PUBLISH=0` |

## 15. Riesgos y trampas

Las trampas que este proyecto ya ha pagado, y cómo se repiten aquí:

- **Un módulo que no llega a la imagen.** `store/` y `dashboard/` tienen que
  estar en el `COPY` del `Dockerfile`, y los estáticos también. El test de
  imagen se extiende para que lo compruebe.
- **Dos módulos con la misma regla y reglas distintas.** La cadena
  global → dominio → cuenta vive en `config.py`. El panel no decide quién
  puede escribir: lo decide `account_allows()`, igual que la tool.
- **Un valor por defecto en la capa más específica anula un global.** El
  dominio trae `imap_host` por defecto; si el dominio lo pone y la cuenta
  no, la cuenta hereda el del dominio. Pero el permiso global sigue
  mandando: el dominio no puede encender una capacidad apagada.
- **Un snapshot que se queda viejo.** El fallo característico de este
  proyecto: el panel añade una cuenta y `/mcp` no la ve. Por eso la
  comprobación de la revisión va en cada petición, y hay una prueba que
  escribe en la base y llama a `/mcp` sin reiniciar nada.
- **El arranque dice lo que ya está puesto.** Los mensajes del arranque
  tienen que decir solo lo que falta: qué variable falta, qué clave no
  corresponde, qué cuenta se ignoró.
- **El 0 es centinela.** Hoy el 0 significa "cuenta del TOML, sin índice". Con
  la base de datos, los identificadores empiezan en 1 y el 0 no enruta a
  nada.
- **La documentación dice lo que el código hace.** `docs/configuracion.md`,
  `docs/dashboard.md`, el README y el CHANGELOG se actualizan en la misma
  entrega, y los tests lo comprueban.

## 16. Decisiones pendientes y supuestos por defecto

Tres cosas que el plan asume y que son decisión de quien opera. Cada una
tiene un **supuesto por defecto**, que es con el que se implementa si no se
dice lo contrario. Cambiar un supuesto es una línea: está aislado en un
sitio, no atraviesa el código.

| Decisión | Supuesto por defecto | Cómo se cambia |
| --- | --- | --- |
| **Token del panel: ¿uno o varios?** | Uno solo: `MCP_DASHBOARD_TOKEN`. Con varios, cada uno sería un usuario con su propio nombre, y la auditoría podría decir quién hizo qué. Es más trabajo y no aporta nada con una sola persona operando. | Una tabla `users` y una sesión por token. El resto no cambia. |
| **¿Se publica el panel?** | No. Se escucha en `127.0.0.1` y el compose no publica el puerto. Se accede por túnel SSH o por un proxy local. | `MCP_DASHBOARD_PUBLISH=1` publica el puerto en el host (siempre en loopback). Si además se expone por el túnel, se recomienda Cloudflare Access delante. |
| **¿El panel sustituye a las variables de entorno?** | Sí: con el panel activo la base de datos es la fuente única, y las cuentas del entorno se importan una vez si la base está vacía. Mantener las dos a la vez es la forma segura de tener dos verdades. | El importador es una función aparte (`store.seed`). Cambiarlo para que no importe, o para que importe en cada arranque, no toca el resto. |

Y una cuarta, de diseño, que se puede aplazar:

4. **¿Los permisos por dominio y por cuenta se editan en el panel?** El plan
   los permite (los campos son tri-estado), pero la interfaz puede exponerlos
   más adelante: la API ya los acepta y la cadena los respeta.

## 17. Fuera de alcance

- **OAuth 2.1** en el MCP: sigue siendo un Bearer estático.
- **Pool de conexiones IMAP** e IDLE: sin cambios.
- **Múltiples instancias del servidor** sobre la misma base de datos: el
  contador de revisiones lo haría posible, pero no se prueba ni se soporta.
- **Historial de cambios**: la auditoría dice qué se hizo, no el antes y el
  después.
- **Cifrado de los tokens**: se guardan en claro, como `MCP_BEARER_TOKEN`
  hoy. Un token es revocable (se borra y se genera otro); una contraseña
  de correo, no.
