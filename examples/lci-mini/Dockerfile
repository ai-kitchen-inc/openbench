# ============================================================
# LCI Mini — API-only container for Cloud Run
# Frontend is deployed separately to Firebase Hosting and proxies
# API routes here via firebase.json rewrites.
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

# Create data dirs
RUN mkdir -p /app/uploads /app/downloads /app/profiles

ENV PORT=8080
ENV LCI_MINI_UPLOAD_DIR=/app/uploads
ENV LCI_MINI_DOWNLOAD_DIR=/app/downloads
ENV OPENBENCH_EXPORT_DIR=/app/downloads
ENV OPENBENCH_EXPORT_URL_BASE=/downloads
ENV OPENBENCH_PROFILE_DIR=/app/profiles

WORKDIR /app/examples/lci-mini

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
