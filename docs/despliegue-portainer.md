# Despliegue con Portainer

El stack base ejecuta el MCP, el panel y el rotador de auditoría. El panel
gestiona las cuentas en una base SQLite persistente; no se definen cuentas en
las variables del stack.

1. Copia `.env.example` y sustituye sus tres secretos ficticios por valores
   independientes generados con `openssl rand -base64 48`. La clave
   `MCP_DASHBOARD_KEY` cifra las contraseñas: guárdala aparte de la base.
2. En Portainer crea un stack desde el repositorio y selecciona
   `docker-compose.yml`. Carga el fichero de variables en **Environment
   variables → Load variables from .env file**.
3. Para usar Cloudflare Tunnel, añade `docker-compose.tunnel.yml` como
   **Additional path** y configura `CLOUDFLARE_TUNNEL_TOKEN` y
   `MCP_PUBLIC_HOST`. Consulta [la guía del túnel](despliegue-tunel-cloudflare.md).
4. Despliega el stack. Conserva el volumen `data`: contiene la base de datos.
   El volumen `audit` contiene la auditoría.
5. Accede al panel mediante un canal privado en `127.0.0.1:8766`, inicia
   sesión con `MCP_DASHBOARD_TOKEN` y crea dominios y cuentas. Prueba la
   conexión antes de guardar y copia el token mostrado una sola vez.

Los puertos del MCP y del panel se publican en loopback por defecto. No
expongas el panel directamente a Internet. Para publicar el MCP usa TLS o el
túnel. Las opciones completas están en [configuración](configuracion.md) y el
flujo del panel en [dashboard](dashboard.md).
