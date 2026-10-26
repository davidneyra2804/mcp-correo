# Checklist de seguridad

Hecho en el código:

- Bearer obligatorio, comparado con `hmac.compare_digest` sobre el SHA-256 del token. Sin token, el proceso no arranca. `/mcp` sin Bearer responde 401.
- Credenciales por cuenta: `MCP_ACCOUNT_BEARER_<N>` da acceso a una sola cuenta y solo por su ruta. En `/mcp` o en la ruta de otra cuenta responde 403. No puede ser igual al bearer global ni repetirse entre cuentas.
- El ámbito de la ruta se aplica en un único punto (`MailService._account`), de modo que una tool no puede tocar una cuenta fuera de su ruta.
- Contraseñas solo en el entorno. El TOML guarda el nombre de la variable. `.gitignore` deja fuera `.env`, `accounts.toml` y `audit.jsonl`.
- Configuración por variables de entorno: la contraseña de cada cuenta va en `MCP_ACCOUNT_PASSWORD_<N>` o se referencia con `MCP_ACCOUNT_PASSWORD_ENV_<N>`. Un interruptor mal escrito aborta el arranque en vez de quedarse apagado en silencio.
- `Account.password` y `Account.bearer` con `repr=False`. Los errores que ve el modelo no incluyen la clave ni el texto crudo de IMAP o SMTP.
- Lectura: `EXAMINE`, `BODY.PEEK[]`, lista blanca de tipos y topes de tamaño. El proxy de lectura rechaza comandos de escritura.
- Escritura apagada por defecto, global y por cuenta. Con el interruptor apagado la tool no se registra.
- Enviar y borrar exigen un token de un solo uso, de 10 minutos, ligado a la cuenta y a la operación. El borrado definitivo es un parámetro de la preparación y viaja dentro del token. Marcar es directo y queda auditado.
- Cupo diario, máximo de destinatarios, dominios opcionales, tope de UID por borrado o marcado, y tamaño de adjuntos.
- Auditoría JSONL de cada acción, sin cuerpos, sin `confirm_token` y sin credenciales. Si no se puede escribir, no hay efecto en el buzón.
- Instrucciones del servidor: el correo no es confiable y `send_message` / `delete_message` solo se ejecutan tras una orden explícita en la conversación.
- Un solo worker. Los tokens y el cupo no salen del proceso.
- DNS rebinding: `allowed_hosts` y `allowed_origins`. En Docker, `MCP_PUBLIC_HOST` o las listas `MCP_ALLOWED_*` los ajustan al dominio público.
- Escucha por defecto en `127.0.0.1`. En el contenedor, `0.0.0.0` solo con `MCP_ALLOW_NONLOCAL_BIND=1`, y el compose publica `127.0.0.1:8765`.
- Imagen sin token ni contraseñas. Usuario `mcp` no root, raíz de solo lectura, `cap_drop: ALL` y `no-new-privileges`. `GET /health` no pide token y no devuelve datos del buzón.

Lo aplica quien despliega:

- Token aleatorio (`openssl rand -base64 48`) y rotación. Archivo de entorno `0600`. TOML `0640`.
- App password del buzón. La escritura sigue apagada hasta que se encienda a propósito.
- Certificado TLS, rate limit y, si se conocen, las IP de salida del cliente en el proxy.
- Usuario de servicio sin shell, systemd endurecido o el compose con los límites del repositorio, y rotación del JSONL.
- No publicar el puerto 8765 en una interfaz que no sea loopback, y no exponerlo sin Bearer ni sin TLS.
- En Portainer, token y contraseñas solo en Environment variables. El TOML montado o en `MCP_ACCOUNTS_TOML_B64` no lleva la clave `password`.
- Comprobar en el cliente de correo que `get_message` no pone `\Seen`.

## Con Cloudflare Tunnel

- El túnel no hereda el rate limit del ejemplo de nginx. Si no hay Cloudflare
  Access delante, pon rate limiting y reglas de WAF en el edge.
- `MCP_PUBLIC_HOST` tiene que ser el hostname público del túnel: `cloudflared`
  reenvía la cabecera `Host` del cliente y el transporte MCP la valida. Si no
  coincide, la respuesta es 421.
- Cloudflare Access con Service Token añade una segunda capa: el cliente
  envía `CF-Access-Client-Id` y `CF-Access-Client-Secret` además del Bearer.
  Con un correo o un grupo, el agente no puede autenticarse solo.
- La auditoría no guarda la IP del cliente: solo fecha, tool, cuenta y
  argumentos reducidos. El registro de accesos, si lo quieres, está en el
  panel de Cloudflare, no en el JSONL.

## Lo que el reinicio del contenedor resetea

El cupo diario de envíos y los tokens de confirmación viven en memoria, porque
el proceso es de un solo worker. Un reinicio del contenedor, un OOM o un
redespliegue los pone a cero. El cupo diario es un tope accidental, no una
garantía: si necesita ser un tope real, ponlo en el servidor SMTP o en el
proxy.
