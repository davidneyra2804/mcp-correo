# Imagen para Portainer. No incluye tokens, contraseñas ni accounts.toml real.
# Un solo worker: los tokens de confirmación y el cupo diario viven en memoria.

FROM python:3.12-slim AS build

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim

RUN groupadd --system --gid 10001 mcp \
    && useradd --system --uid 10001 --gid 10001 \
        --no-create-home --shell /usr/sbin/nologin mcp \
    && mkdir -p /var/log/mcp-correo /app \
    && chown mcp:mcp /var/log/mcp-correo

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=mcp:mcp server.py config.py audit.py scope.py version.py /app/
COPY --chown=mcp:mcp mail /app/mail
COPY --chown=mcp:mcp docker/entrypoint.py docker/rotate_audit.py /app/docker/
COPY --chown=mcp:mcp accounts.example.toml /app/accounts.example.toml

USER mcp

# La etiqueta tiene que coincidir con version.py. Un test lo comprueba.
ARG MCP_VERSION=1.0.5
LABEL org.opencontainers.image.version="${MCP_VERSION}" \
      org.opencontainers.image.title="mcp-correo" \
      org.opencontainers.image.description="Servidor MCP de correo sobre IMAP y SMTP" \
      org.opencontainers.image.source="https://github.com/davidneyra2804/mcp-correo" \
      org.opencontainers.image.licenses="MIT"

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_BIND_HOST=0.0.0.0 \
    MCP_BIND_PORT=8765 \
    MCP_ALLOW_NONLOCAL_BIND=1 \
    MCP_AUDIT_LOG=/var/log/mcp-correo/audit.jsonl

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; p=os.environ.get('MCP_BIND_PORT','8765'); urllib.request.urlopen('http://127.0.0.1:'+p+'/health')"

ENTRYPOINT ["python", "/app/docker/entrypoint.py"]
CMD ["python", "server.py"]
