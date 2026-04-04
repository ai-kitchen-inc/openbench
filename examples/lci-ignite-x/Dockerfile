# ============================================================
# Stage 1: Build frontend (chat-ui + lci-ignite-x frontend)
# ============================================================
FROM node:22-slim AS frontend-builder

RUN npm install -g pnpm

WORKDIR /build

# 1a. Build @openbench/chat-ui
COPY studio/chat-ui/package.json studio/chat-ui/pnpm-lock.yaml* studio/chat-ui/
WORKDIR /build/studio/chat-ui
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY studio/chat-ui/ .
RUN pnpm build

# 1b. Build lci-ignite-x frontend
WORKDIR /build/examples/lci-ignite-x/frontend
COPY examples/lci-ignite-x/frontend/package.json examples/lci-ignite-x/frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY examples/lci-ignite-x/frontend/ .
RUN pnpm build

# ============================================================
# Stage 2: Python backend
# ============================================================
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install OpenBench SDK
COPY pyproject.toml setup.cfg* ./
COPY src/openbench/ src/openbench/
RUN pip install --no-cache-dir ".[chat,google,data]" python-multipart

# Install lci-ignite-x
COPY examples/lci-ignite-x/pyproject.toml examples/lci-ignite-x/
COPY examples/lci-ignite-x/src/ examples/lci-ignite-x/src/
COPY examples/lci-ignite-x/server.py examples/lci-ignite-x/
RUN pip install --no-cache-dir ./examples/lci-ignite-x/

# Copy frontend build
COPY --from=frontend-builder /build/examples/lci-ignite-x/frontend/dist /app/static

# Create uploads dir
RUN mkdir -p /app/uploads

ENV PORT=8080
ENV LCI_UPLOAD_DIR=/app/uploads
ENV LCI_STATIC_DIR=/app/static

WORKDIR /app/examples/lci-ignite-x

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
