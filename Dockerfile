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
    && mkdir -p /var/log/mcp-correo /var/lib/mcp-correo /app \
    && chown mcp:mcp /var/log/mcp-correo /var/lib/mcp-correo

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=mcp:mcp server.py config.py audit.py scope.py version.py /app/
COPY --chown=mcp:mcp mail /app/mail
COPY --chown=mcp:mcp store /app/store
COPY --chown=mcp:mcp dashboard /app/dashboard
COPY --chown=mcp:mcp docker/entrypoint.py docker/rotate_audit.py docker/healthcheck.py /app/docker/
COPY --chown=mcp:mcp accounts.example.toml /app/accounts.example.toml

USER mcp

# La etiqueta tiene que coincidir con version.py. Un test lo comprueba.
ARG MCP_VERSION=2.0.0
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
    MCP_AUDIT_LOG=/var/log/mcp-correo/audit.jsonl \
    MCP_DASHBOARD_BIND_PORT=8766

# 8765: el MCP. 8766: el panel de control (solo si MCP_DASHBOARD_DB está).
EXPOSE 8765 8766

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "/app/docker/healthcheck.py"]

ENTRYPOINT ["python", "/app/docker/entrypoint.py"]
CMD ["python", "server.py"]
