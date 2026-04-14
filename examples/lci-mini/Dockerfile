# ============================================================
# Stage 1: Build frontend (chat-ui + lci-mini frontend)
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

# 1b. Build lci-mini frontend
WORKDIR /build/examples/lci-mini/frontend
COPY examples/lci-mini/frontend/package.json examples/lci-mini/frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY examples/lci-mini/frontend/ .
RUN pnpm build

# ============================================================
# Stage 2: Python backend
# ============================================================
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install OpenBench SDK (with chat, google, data, output extras)
COPY pyproject.toml setup.cfg* ./
COPY src/openbench/ src/openbench/
RUN pip install --no-cache-dir ".[chat,google,data,output]" python-multipart pdfplumber

# Install lci-mini
COPY examples/lci-mini/pyproject.toml examples/lci-mini/
COPY examples/lci-mini/src/ examples/lci-mini/src/
COPY examples/lci-mini/server.py examples/lci-mini/

# Copy soul/ and skills/ (persona + project skills)
COPY examples/lci-mini/soul/ examples/lci-mini/soul/
COPY examples/lci-mini/skills/ examples/lci-mini/skills/

RUN pip install --no-cache-dir ./examples/lci-mini/

# Copy frontend build
COPY --from=frontend-builder /build/examples/lci-mini/frontend/dist /app/static

# Create data dirs
RUN mkdir -p /app/uploads /app/downloads /app/profiles

ENV PORT=8080
ENV LCI_MINI_UPLOAD_DIR=/app/uploads
ENV LCI_MINI_DOWNLOAD_DIR=/app/downloads
ENV LCI_MINI_STATIC_DIR=/app/static
ENV OPENBENCH_EXPORT_DIR=/app/downloads
ENV OPENBENCH_EXPORT_URL_BASE=/downloads
ENV OPENBENCH_PROFILE_DIR=/app/profiles

WORKDIR /app/examples/lci-mini

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
