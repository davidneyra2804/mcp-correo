# Despliegue con Cloudflare Tunnel

El túnel expone el MCP sin abrir ningún puerto en el host: `cloudflared` sale
hacia Cloudflare por conexiones salientes y el tráfico vuelve al contenedor
por la red del stack.

## Cómo queda

```
Cliente MCP ──HTTPS──▶ Cloudflare (TLS, WAF, Access) ──▶ cloudflared
                                                                │ red del stack
                                                                ▼
                                                        mcp (8765)
```

El contenedor no publica nada en el host. `cloudflared` lo alcanza por el
nombre de servicio: `http://mcp:8765`.

## 1. Crear el túnel

En el panel de Cloudflare, **Networking → Tunnels → Create a tunnel**. Ponle un
nombre y elige la opción de ejecución en Docker. El panel te da un comando con
un token; ese token es lo que va en `CLOUDFLARE_TUNNEL_TOKEN`.

Es un túnel **administrado a distancia**: la configuración de las rutas vive en
el panel, no en un fichero dentro del contenedor. Eso es lo que permite
desplegarlo sin tocar ficheros.

## 2. La ruta publicada

**Tunnel → tu túnel → Routes → Add route → Published application**.

- **Subdomain y dominio**: el hostname público, por ejemplo `mcp.example.com`.
- **Service URL**: `http://mcp:8765`.

El Service URL es el nombre del servicio en la red de Compose, no
`127.0.0.1`: dentro del contenedor `cloudflared`, el loopback es el suyo.

## 3. Las variables

En las variables del stack de Portainer:

```bash
# El hostname público. Tiene que coincidir con la ruta de arriba.
MCP_PUBLIC_HOST=mcp.example.com

# El token del panel.
CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiXXXX...
```

`MCP_PUBLIC_HOST` no es opcional en este escenario, y no es cosmético:

- `cloudflared` reenvía la cabecera `Host` original del cliente. El transporte
  MCP la valida contra `allowed_hosts`. Si `MCP_PUBLIC_HOST` no es el hostname
  público, la respuesta es **421 Misdirected Request**.
- El origen `https://mcp.example.com` tiene que estar en `allowed_origins`.
  `MCP_PUBLIC_HOST` lo añade solo. Si lo sustituyes por
  `MCP_ALLOWED_ORIGINS`, incluye el origen con esquema.

Si necesitas más hosts, defínelos explícitamente:

```bash
MCP_ALLOWED_HOSTS=mcp.example.com,mcp.example.com:*,127.0.0.1:*
MCP_ALLOWED_ORIGINS=https://mcp.example.com,http://127.0.0.1:*
```

Un `Host` que no esté permitido responde 421. Un `Origin` que no esté
permitido responde 403.

## 4. Desplegar

En Portainer, el stack de Git con **Additional paths** → añade
`docker-compose.tunnel.yml`. Es la misma semántica que dos ficheros `-f`:

```bash
docker compose -f docker-compose.yml -f docker-compose.tunnel.yml up -d --build
```

El overlay añade el servicio `cloudflared` con el token desde el entorno. El
compose base no cambia.

El puerto que el compose base publica en `127.0.0.1:8765` no molesta: es
loopback y sirve para depurar con `curl` desde el host. Si prefieres que no
exista en absoluto, quita el bloque `ports:` del servicio `mcp` en
`docker-compose.yml`.

## 5. Comprobar

```bash
# El túnel está conectado
docker compose logs cloudflared

# El MCP responde por el túnel
curl -i https://mcp.example.com/mcp \
  -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Y en los logs del contenedor, la línea de arranque:

```
INFO     Servidor listo: 2 cuentas, escucha 0.0.0.0:8765, escritura=apagada
INFO     Configuración: variables de entorno. Cuentas: archivo, principal
```

Si el `curl` responde **421**, `MCP_PUBLIC_HOST` no coincide con el hostname
público. Si responde **403**, falta el origen en `MCP_ALLOWED_ORIGINS`. Si
responde **401**, el token no es el del stack.

## 6. Cloudflare Access (opcional)

Access pone una segunda capa delante del Bearer: el edge de Cloudflare decide
quién pasa, con reglas por IP, por correo o por identidad.

Para un agente automatizado, lo que funciona es un **Service Token**:

1. En el panel: **Access → Applications → Add an application** →
   *Self-hosted*, con el hostname `mcp.example.com`.
2. En la política, en vez de un correo o un grupo, elige **Service Token** y
   crea uno.
3. El cliente MCP tiene que enviar las dos cabeceras del token además del
   Bearer:

   ```
   CF-Access-Client-Id: <id>.access
   CF-Access-Client-Secret: <secreto>
   Authorization: Bearer <MCP_BEARER_TOKEN>
   ```

   Configúralas en el cliente MCP. La mayoría acepta cabeceras adicionales;
   si el tuyo solo admite `Authorization`, usa un proxy pequeño delante o
   renuncia a Access y quédate con el Bearer.

Sin Access, el endpoint es público y el único secreto es el Bearer del MCP.
Un token de 48 bytes aleatorios es una barrera serie, pero no da registro de
accesos, ni listas de IP, ni rate limit en el edge.

## 7. Qué hacer en el edge

El túnel no hereda el rate limit que trae el ejemplo de nginx
(`deploy/nginx-mcp.conf`, 60 peticiones por minuto por IP). Si usas Access, pon
la política ahí. Si no, la primera línea de defensa es el WAF de Cloudflare:

- **Rate limiting** por IP sobre la ruta del túnel.
- **Reglas de WAF** que bloqueen por patrón, útil contra intentos de fuerza
  bruta del token.
- **Bot Fight Mode** o equivalente, si el tráfico es legítimo de un solo
  cliente.

## 8. Diagnóstico

| Síntoma | Causa probable |
| --- | --- |
| `421 Misdirected Request` | `MCP_PUBLIC_HOST` no coincide con el hostname público. |
| `403 Forbidden` | El `Origin` no está en `MCP_ALLOWED_ORIGINS`. |
| `401 Unauthorized` | El token del cliente no es el del stack. |
| `530` o `502` en el edge | El túnel no está conectado, o el Service URL no resuelve. |
| El túnel conecta pero el MCP no ve nada | `cloudflared` y `mcp` no están en la misma red de Compose. |
| `timeout` en vez de respuesta | `CLOUDFLARE_TUNNEL_PROTOCOL=quic` y la red bloquea UDP. Prueba `http2`. |

## 9. Rotar el token

El token del MCP vive en las variables del stack: edita `MCP_BEARER_TOKEN`,
**Pull and redeploy** y actualiza el cliente. El volumen `audit` y el resto de
secretos se conservan.

El token del túnel se rota en el panel de Cloudflare: genera uno nuevo,
cambia `CLOUDFLARE_TUNNEL_TOKEN` y redespliega.
