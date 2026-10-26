FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Matplotlib needs a writable config dir under a non-root user.
ENV MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin customfn \
    && mkdir -p /data/functions /tmp/matplotlib \
    && chown -R customfn:customfn /data /tmp/matplotlib

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY README.md ./

RUN chown -R customfn:customfn /app
USER customfn

# The functions dir is volume-mounted read-only by the spawner.
ENV CUSTOM_FN_DIR=/data/functions
ENV CUSTOM_FN_TIMEOUT_SECONDS=20

CMD ["python", "-m", "app.mcp_server", "--transport", "stdio"]
