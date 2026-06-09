FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DATA_PATH=/data
ENV INDEX_PATH=/data/index
ENV MODEL_CACHE_PATH=/models
ENV PREVIEW_PATH=/data/previews
ENV DEVICE=auto
ENV VECTOR_BACKEND=auto
ENV HF_HUB_DISABLE_PROGRESS_BARS=1
ENV TRANSFORMERS_VERBOSITY=error

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin image-search \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY openbench-skill ./openbench-skill
COPY README.md ./

RUN mkdir -p /data /models && chown -R image-search:image-search /app /data /models
USER image-search

CMD ["python", "-m", "app.mcp_server", "--transport", "stdio"]

FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime AS gpu

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DATA_PATH=/data
ENV INDEX_PATH=/data/index
ENV MODEL_CACHE_PATH=/models
ENV PREVIEW_PATH=/data/previews
ENV DEVICE=cuda
ENV VECTOR_BACKEND=auto
ENV HF_HUB_DISABLE_PROGRESS_BARS=1
ENV TRANSFORMERS_VERBOSITY=error

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin image-search \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY openbench-skill ./openbench-skill
COPY README.md ./

RUN mkdir -p /data /models && chown -R image-search:image-search /app /data /models
USER image-search

CMD ["python", "-m", "app.mcp_server", "--transport", "stdio"]
