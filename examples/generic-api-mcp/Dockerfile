FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV GENERIC_API_TIMEOUT_SECONDS=30

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin generic-api \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY openbench-skill ./openbench-skill
COPY README.md ./

RUN chown -R generic-api:generic-api /app
USER generic-api

CMD ["python", "-m", "app.mcp_server", "--transport", "stdio"]

