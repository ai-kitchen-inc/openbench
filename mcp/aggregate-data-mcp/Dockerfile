FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /repo

RUN useradd --create-home --shell /usr/sbin/nologin aggregate-mcp

COPY pyproject.toml README.md ./
COPY src ./src
COPY mcp/aggregate-data-mcp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir -r requirements.txt

COPY mcp/aggregate-data-mcp ./mcp/aggregate-data-mcp

RUN chown -R aggregate-mcp:aggregate-mcp /repo
USER aggregate-mcp

WORKDIR /repo/mcp/aggregate-data-mcp

CMD ["python", "-m", "app.mcp_server", "--transport", "stdio"]
