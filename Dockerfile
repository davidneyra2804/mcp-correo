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
    && mkdir -p /var/log/vyr-mail-mcp /app \
    && chown mcp:mcp /var/log/vyr-mail-mcp

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=mcp:mcp server.py config.py audit.py /app/
COPY --chown=mcp:mcp mail /app/mail
COPY --chown=mcp:mcp docker/entrypoint.py docker/rotate_audit.py /app/docker/
COPY --chown=mcp:mcp accounts.example.toml /app/accounts.example.toml

USER mcp

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_BIND_HOST=0.0.0.0 \
    MCP_BIND_PORT=8765 \
    MCP_ALLOW_NONLOCAL_BIND=1 \
    MCP_CONFIG=/config/accounts.toml \
    MCP_AUDIT_LOG=/var/log/vyr-mail-mcp/audit.jsonl

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; p=os.environ.get('MCP_BIND_PORT','8765'); urllib.request.urlopen('http://127.0.0.1:'+p+'/health')"

ENTRYPOINT ["python", "/app/docker/entrypoint.py"]
CMD ["python", "server.py"]
