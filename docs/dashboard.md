# El panel de control

Un panel web para dar de alta las cuentas de correo sin tocar el
despliegue. Escucha en **su propio puerto**, separado del MCP, y tiene su
propia credencial.

Con el panel, las cuentas salen de una base de datos SQLite en vez
de de variables de entorno. Y en cuanto existen, están expuestas en `/mcp`:
**no hay que reiniciar nada**.

## Qué es y qué no es

| | |
| --- | --- |
| Gestiona dominios y cuentas | Sí |
| Genera y rota tokens | Sí |
| Prueba una conexión IMAP o SMTP antes de guardar | Sí |
| Lee o escribe un buzón | **No** |

El panel no registra tools del MCP, no habla con el SDK y no puede tocar
un buzón. Esa frontera es a propósito: un panel abierto no debe poder
enviar correo.

## Activarlo

El panel y la base de datos **siempre están**: son la forma de gestionar las
cuentas. No hay un interruptor que los encienda.

Dos secretos son obligatorios:

```bash
MCP_DASHBOARD_KEY=la-clave-con-la-que-se-cifran-las-contrasenas
MCP_DASHBOARD_TOKEN=la-credencial-de-acceso-al-panel
```

Si falta alguno, el proceso **no arranca** y dice cuál falta. No se arranca
a medias.

La ruta de la base de datos es `MCP_DASHBOARD_DB`, y por defecto es
`cuentas.db`, en el directorio de trabajo. **Ponla donde persista**: en el
contenedor, sobre el volumen de datos.

### En Docker

```yaml
environment:
  MCP_DASHBOARD_DB: /var/lib/mcp-correo/cuentas.db
volumes:
  - data:/var/lib/mcp-correo
```

El contenedor es de solo lectura: sin ese volumen, la base no se puede
escribir y el arranque falla. Y sin volumen, las cuentas se pierden en cada
reinicio.

### La clave

`MCP_DASHBOARD_KEY` cifra las contraseñas de las cuentas con AES-GCM. **No
está en la base de datos**: si se pierde, las contraseñas guardadas no se
pueden descifrar y hay que volver a ponerlas. Guárdala en el mismo sitio
que el resto de secretos.

El arranque comprueba que la clave corresponde a la base: si no, para y lo
dice. Sin esa comprobación, el síntoma sería "las cuentas no funcionan" y
nadie sabría si es la clave o el servidor IMAP.

### El token

`MCP_DASHBOARD_TOKEN` es la credencial del panel, y tiene que ser
distinta de `MCP_BEARER_TOKEN`. Son dos superficies con dos
credenciales: el token del MCP no abre el panel, y el del panel no abre
`/mcp`.

## Las cuentas: dónde están

La base de datos es **la fuente de las cuentas**. Las variables
`MCP_ACCOUNT_<CAMPO>_<N>` (o el `accounts.toml`) son la importación
inicial: se importan **una vez**, y solo si la base está **vacía**. A partir
de ahí, la base manda y el entorno se ignora. El arranque lo dice:

```
INFO     Cuentas importadas del entorno: 2. A partir de aquí la base de datos manda.
```

Si la base ya tenía cuentas y el entorno trae otras, se ignoran las del
entorno:

```
INFO     La base de datos ya tiene cuentas: las 2 del entorno se ignoran.
```

Es a propósito: dos fuentes a la vez son dos verdades, y de dos verdades
sale una que nadie sabe cuál es.

## La interfaz

El panel está en `http://127.0.0.1:8766` (o donde lo publiques). Se entra
con el token y se abre una sesión.

- Los **dominios** se listan como secciones, cada una con sus cuentas.
- Cada cuenta muestra su **ruta**, tal y como se escribe:
  `/mcp/ada@corp.example.com`. Es lo que se le pasa a un cliente.
- Un botón marca el dominio como **por defecto**: es el que abre `/mcp`.
  Solo uno puede estarlo.
- El botón **Token** genera uno nuevo para una cuenta o un dominio, y lo
  muestra **una sola vez**.
- El botón **Probar** valida la conexión IMAP con lo que hay en el
  formulario, sin guardar nada. Si algo está mal (el host, el puerto, el
  SSL, la contraseña), se ve ahí y no cuando el agente intenta leer el
  buzón.
- Una cuenta se puede **desactivar** sin borrarla: deja de exponerse, y
  sus datos siguen ahí.

### Probar antes de guardar

El botón de probar abre una conexión de verdad, hace login, mira las
carpetas y se cierra. No guarda nada, no envía nada y no deja rastro en
el buzón.

Usa el mismo código de conexión que el resto del servidor, así que el
mensaje que sale es el mismo que saldría al leer el buzón. Y la contraseña
no sale en el mensaje de error.

## Las rutas del MCP

Con cuentas en la base, el servidor expone tres rutas:

| Ruta | Ámbito |
| --- | --- |
| `/mcp` | La guía: el catálogo de rutas. Y el dominio por defecto, si lo hay. |
| `/mcp/<dominio>` | Las cuentas de ese dominio. |
| `/mcp/<cuenta>` | Esa cuenta. |

El catálogo lo da `list_accounts`. Un ejemplo:

```json
{
  "route": "/mcp",
  "scope": ["ada@corp.example.com"],
  "default_domain": "corp.example.com",
  "domains": [
    {"domain": "corp.example.com", "route": "/mcp/corp.example.com",
     "default": true, "accounts": ["ada@corp.example.com"]}
  ],
  "accounts": [
    {"account": "ada@corp.example.com", "route": "/mcp/ada@corp.example.com",
     "domain": "corp.example.com", "own_credential": true,
     "can_send": true, "can_mark": true, "can_delete": false, "can_draft": true}
  ]
}
```

El agente recibe esa lista y sabe a dónde ir. La ruta general **no**
expone todos los buzones: para abrir uno hay que nombrarlo.

## Los tokens

Hay tres niveles, y el más específico manda cuando se presenta:

| Nivel | Dónde vive | Abre |
| --- | --- | --- |
| General | `MCP_BEARER_TOKEN` | Todas las cuentas |
| De dominio | `domains.bearer` | Las cuentas de ese dominio |
| De cuenta | `accounts.bearer` | Esa cuenta |

La regla: **la credencial tiene que abrir la ruta**. La de una cuenta no
abre la ruta de un dominio, aunque el dominio tenga una sola cuenta. La de
un dominio no abre la ruta de otro.

El modelo de seguridad es **a nivel de cuenta**: una cuenta, un ámbito,
una credencial. El dominio y la general son cobertura hacia arriba, para
quien la necesite.

## Los permisos

La cadena es la de siempre, con un nivel más:

| | `MCP_ENABLE_SEND` | `allow_send` del dominio | `allow_send` de la cuenta |
| --- | --- | --- | --- |
| 1 | `false` | lo que sea | lo que sea | **Apagada** |
| 2 | `true` | sin definir | sin definir | **Encendida** |
| 3 | `true` | sin definir | `false` | **Apagada** para esa cuenta |
| 4 | `true` | `false` | lo que sea | **Apagada** en el dominio |

El interruptor global sigue siendo el maestro: apagado, nada. El dominio
y la cuenta son overrides opcionales.

## La auditoría

Todo lo que hace el panel queda en el mismo JSONL que las tools del MCP,
con su propio nombre (`dashboard_add_account`, `dashboard_rotate_token`,
`dashboard_test_imap`...). Sin cuerpos y sin secretos: las contraseñas y
los tokens se tapan.

```bash
docker compose exec mcp python -c "print(open('/var/log/mcp-correo/audit.jsonl').read())"
```

## Exponer el panel

Por defecto escucha en `127.0.0.1` y el compose publica el puerto en
loopback. **El panel ve las contraseñas**: publicarlo en abierto es una
decisión que hay que querer.

Si hay que exponerlo, mejor detrás de Cloudflare Access que con el token
solo.

## La base de datos

Un fichero SQLite, en WAL, con las contraseñas cifradas. El esquema tiene
versión y las migraciones se aplican al arrancar. El contador de revisiones
vive en la base, y es lo que permite que el servidor recargue las cuentas
sin reiniciar: escribe el panel, lee el servidor, y se entera.

Para inspeccionarla:

```bash
docker compose exec mcp python -c "import sqlite3; print(sqlite3.connect('/var/lib/mcp-correo/cuentas.db').execute('select id, name, is_default from domains').fetchall())"
```

Las contraseñas se ven cifradas. A propósito.
