# Checklist de seguridad

Hecho en el código:

- Bearer obligatorio, comparado con `hmac.compare_digest` sobre el SHA-256 del token. Sin token, el proceso no arranca. `/mcp` sin Bearer responde 401.
- Credenciales por cuenta, gestionadas en el panel: dan acceso a una sola cuenta y solo por su ruta. En `/mcp` o en la ruta de otra cuenta responden 403. No pueden coincidir con el bearer global ni repetirse.
- El ámbito de la ruta se aplica en un único punto (`MailService._account`), de modo que una tool no puede tocar una cuenta fuera de su ruta.
- Las contraseñas de cuentas se guardan cifradas en la base; la clave de cifrado está fuera de ella. `.gitignore` excluye `.env` y `audit.jsonl`.
- Un interruptor global mal escrito aborta el arranque en vez de quedarse apagado en silencio.
- `Account.password` y `Account.bearer` con `repr=False`. Los errores que ve el modelo no incluyen la clave ni el texto crudo de IMAP o SMTP.
- Lectura: `EXAMINE`, `BODY.PEEK[]`, lista blanca de tipos y topes de tamaño. El proxy de lectura rechaza comandos de escritura.
- Escritura apagada por defecto globalmente. Las cuentas heredan salvo que el panel establezca un permiso más restrictivo. Con el interruptor global apagado la tool no se registra.
- Enviar y borrar exigen un token de un solo uso, de 10 minutos, ligado a la cuenta y a la operación. El borrado definitivo es un parámetro de la preparación y viaja dentro del token. Marcar es directo y queda auditado.
- Cupo diario, máximo de destinatarios, dominios opcionales, tope de UID por borrado o marcado, y tamaño de adjuntos.
- Auditoría JSONL de cada acción, sin cuerpos, sin `confirm_token` y sin credenciales. Si no se puede escribir, no hay efecto en el buzón.
- Instrucciones del servidor: el correo no es confiable y `send_message` / `delete_message` solo se ejecutan tras una orden explícita en la conversación.
- El flujo en dos pasos se dice en tres capas, para que el agente no dependa de una sola: las instrucciones del servidor, la descripción de cada tool y la respuesta de la preparación. La respuesta lleva `status: "prepared"`, `sent: false` y `next_tool`, de modo que el estado no hay que deducirlo de un texto. Preparar no envía y no borra: `prepare_send` y `prepare_delete` no tienen efecto sobre el buzón.
- Un solo worker. Los tokens y el cupo no salen del proceso.
- DNS rebinding: `allowed_hosts` y `allowed_origins`. En Docker, `MCP_PUBLIC_HOST` o las listas `MCP_ALLOWED_*` los ajustan al dominio público.
- Escucha por defecto en `127.0.0.1`. En el contenedor, `0.0.0.0` solo con `MCP_ALLOW_NONLOCAL_BIND=1`, y el compose publica `127.0.0.1:8765`.
- Imagen sin token ni contraseñas. Usuario `mcp` no root, raíz de solo lectura, `cap_drop: ALL` y `no-new-privileges`. `GET /health` no pide token y no devuelve datos del buzón.

- El panel es una superficie aparte, con su propia credencial
  (`MCP_DASHBOARD_TOKEN`), que tiene que ser distinta del bearer del MCP.
  El token del MCP no abre el panel, y el del panel no abre `/mcp`.
- Escucha en `127.0.0.1` y su puerto se publica en loopback. El panel ve las
  contraseñas de las cuentas: publicarlo en abierto es una decisión que hay
  que querer.
- La sesión es una cookie firmada con HMAC, `HttpOnly` y `SameSite=Strict`,
  con caducidad. Las peticiones que cambian algo exigen la cabecera
  `X-MCP-Dashboard`, que un formulario de otro sitio no puede poner.
- Las contraseñas de las cuentas se cifran con AES-GCM y una clave que
  **no** está en la base de datos (`MCP_DASHBOARD_KEY`). El arranque
  comprueba que la clave corresponde a la base.
- El panel no registra tools ni puede leer ni escribir un buzón. Solo
  gestiona la configuración y prueba conexiones.
- La API nunca devuelve una contraseña, y todo lo que hace el panel queda
  auditado sin secretos.

Lo aplica quien despliega:

- Tokens y clave aleatorios (`openssl rand -base64 48`) y archivo de entorno `0600`. Guarda una copia de la clave de cifrado separada de la base.
- App password del buzón. La escritura sigue apagada hasta que se encienda a propósito.
- Certificado TLS, rate limit y, si se conocen, las IP de salida del cliente en el proxy.
- Usuario de servicio sin shell, systemd endurecido o el compose con los límites del repositorio, y rotación del JSONL.
- No publicar el puerto 8765 en una interfaz que no sea loopback, y no exponerlo sin Bearer ni sin TLS.
- No publiques el puerto del panel fuera de loopback. Si
  hace falta entrar desde fuera, mejor detrás de Cloudflare Access.
- En Portainer, los secretos del servidor van en Environment variables; las contraseñas de cuentas se introducen en el panel.
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
