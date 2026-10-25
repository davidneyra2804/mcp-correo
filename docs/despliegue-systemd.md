# Despliegue con systemd

El proceso escucha en `127.0.0.1:8765`. Un proxy en el mismo host termina TLS y publica HTTPS. Conviene una máquina distinta del servidor de correo, para no chocar con el proxy que ese servidor regenere.

Esquema, en Debian 12 o Ubuntu 24.04. Sustituye `mcp.example.com` por el nombre público y el TOML de ejemplo por uno con tus hosts. El token y las contraseñas van en `/etc/mcp-correo/env`, modo `0600`, y no se commitean.

```bash
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx ufw git
sudo useradd --system --home /opt/mcp-correo --shell /usr/sbin/nologin mcpmail
sudo git clone <url-del-repo> /opt/mcp-correo
sudo python3 -m venv /opt/mcp-correo/.venv
sudo /opt/mcp-correo/.venv/bin/pip install -r /opt/mcp-correo/requirements.txt
sudo chown -R root:mcpmail /opt/mcp-correo && sudo chmod -R o-rwx /opt/mcp-correo

sudo install -d -m 0750 -o root -g mcpmail /etc/mcp-correo
sudo install -m 0640 -o root -g mcpmail accounts.example.toml /etc/mcp-correo/accounts.toml
sudo install -m 0600 -o root -g root /dev/null /etc/mcp-correo/env
sudo install -d -m 0750 -o mcpmail -g mcpmail /var/log/mcp-correo
# Editar el TOML con los hosts reales y el env con el token y las contraseñas.

sudo cp deploy/mcp-correo.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now mcp-correo
sudo cp deploy/nginx-mcp.conf /etc/nginx/conf.d/mcp.example.com.conf
sudo certbot --nginx -d mcp.example.com
sudo nginx -t && sudo systemctl reload nginx
sudo cp deploy/logrotate.conf /etc/logrotate.d/mcp-correo
```

`deploy/mcp-correo.service` corre como `mcpmail`, sin privilegios nuevos, con el sistema de archivos en solo lectura salvo `/var/log/mcp-correo`, un tope de 512 MiB y un solo worker. Ese `--workers 1` sujeta los tokens de confirmación y el cupo diario, que no se comparten entre procesos.

`deploy/nginx-mcp.conf` ofrece TLS 1.2+, limita a 60 peticiones por minuto por IP y solo hace proxy de `/mcp` hacia `127.0.0.1:8765`. El `server_name` de ejemplo es `mcp.example.com`. La IP comentada `203.0.113.10` es de documentación (TEST-NET, RFC 5737), no una dirección de nadie.

`deploy/logrotate.conf` rota `/var/log/mcp-correo/audit.jsonl` cada semana, conserva 12 copias y usa `copytruncate` porque el proceso de systemd mantiene el descriptor abierto.

El firewall puede dejar 22 restringido a la IP de administración, más 80 y 443. El puerto 8765 no se publica.

Conexión desde el cliente MCP: URL `https://mcp.example.com/mcp` y cabecera `Authorization: Bearer <token>`.

La alternativa con Docker está en [despliegue-portainer.md](despliegue-portainer.md). Las dos no se usan a la vez sobre el mismo puerto.
