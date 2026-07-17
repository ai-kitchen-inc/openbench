FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OPENBENCH_EXPORT_DIR=/outputs
ENV OPENBENCH_EXPORT_URL_BASE=/outputs
ENV OPENBENCH_DASHBOARD_STATE_PATH=/outputs/dashboard_generator_state.json
ENV DASHBOARD_RENDER_ADAPTER=default

WORKDIR /repo

RUN useradd --create-home --shell /usr/sbin/nologin dashboard-mcp

COPY pyproject.toml README.md ./
COPY src ./src
COPY mcp/dashboard-generator-mcp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir -r requirements.txt

COPY mcp/dashboard-generator-mcp ./mcp/dashboard-generator-mcp

RUN mkdir -p /outputs \
    && chown -R dashboard-mcp:dashboard-mcp /repo /outputs
USER dashboard-mcp

WORKDIR /repo/mcp/dashboard-generator-mcp

CMD ["python", "-m", "app.mcp_server", "--transport", "stdio"]
