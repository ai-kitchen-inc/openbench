# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS base

ARG SAM3_PREINSTALL=auto
ARG SAM3_HF_REPO=facebook/sam3
ARG SAM3_HF_FILENAME=sam3.pt

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SAM3_MODEL_PATH=/models/sam3.pt
ENV SAM3_DEVICE=cpu
ENV SAM3_CONF=0.25
ENV SAM3_HALF=false
ENV SAM3_VERBOSE=false
ENV MAX_IMAGE_BYTES=10485760
ENV MAX_IMAGE_PIXELS=12000000
ENV IMAGE_INPUT_ROOTS=/general-chat/uploads,/data,/input
ENV DEBUG_OUTPUT_DIR=/tmp/sam-segmentation-debug
ENV YOLO_CONFIG_DIR=/tmp/ultralytics-config
ENV MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin sam-segmentation \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
RUN pip install --no-cache-dir -r requirements.txt
RUN pip uninstall clip -y || true \
    && pip install --no-cache-dir git+https://github.com/ultralytics/CLIP.git \
    && python -c "import clip, timm; print('SAM 3 CLIP and timm dependencies available')"

COPY app ./app
COPY openbench-skill ./openbench-skill
COPY scripts ./scripts
COPY README.md ./
COPY weights ./weights

RUN --mount=type=secret,id=hf_token,required=false \
    mkdir -p /data /input /models /tmp/sam-segmentation-debug /tmp/ultralytics-config /tmp/matplotlib \
    && SAM3_PREINSTALL="${SAM3_PREINSTALL}" SAM3_HF_REPO="${SAM3_HF_REPO}" SAM3_HF_FILENAME="${SAM3_HF_FILENAME}" python scripts/download_sam3_weights.py \
    && chown -R sam-segmentation:sam-segmentation /app /data /input /models /tmp/sam-segmentation-debug /tmp/ultralytics-config /tmp/matplotlib

USER sam-segmentation

CMD ["python", "-m", "app.mcp_server", "--transport", "stdio"]

FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime AS gpu

ARG SAM3_PREINSTALL=auto
ARG SAM3_HF_REPO=facebook/sam3
ARG SAM3_HF_FILENAME=sam3.pt

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SAM3_MODEL_PATH=/models/sam3.pt
ENV SAM3_DEVICE=cuda
ENV SAM3_CONF=0.25
ENV SAM3_HALF=true
ENV SAM3_VERBOSE=false
ENV MAX_IMAGE_BYTES=10485760
ENV MAX_IMAGE_PIXELS=12000000
ENV IMAGE_INPUT_ROOTS=/general-chat/uploads,/data,/input
ENV DEBUG_OUTPUT_DIR=/tmp/sam-segmentation-debug
ENV YOLO_CONFIG_DIR=/tmp/ultralytics-config
ENV MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin sam-segmentation \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip uninstall clip -y || true \
    && pip install --no-cache-dir git+https://github.com/ultralytics/CLIP.git \
    && python -c "import clip, timm; print('SAM 3 CLIP and timm dependencies available')"

COPY app ./app
COPY openbench-skill ./openbench-skill
COPY scripts ./scripts
COPY README.md ./
COPY weights ./weights

RUN --mount=type=secret,id=hf_token,required=false \
    mkdir -p /data /input /models /tmp/sam-segmentation-debug /tmp/ultralytics-config /tmp/matplotlib \
    && SAM3_PREINSTALL="${SAM3_PREINSTALL}" SAM3_HF_REPO="${SAM3_HF_REPO}" SAM3_HF_FILENAME="${SAM3_HF_FILENAME}" python scripts/download_sam3_weights.py \
    && chown -R sam-segmentation:sam-segmentation /app /data /input /models /tmp/sam-segmentation-debug /tmp/ultralytics-config /tmp/matplotlib

USER sam-segmentation

CMD ["python", "-m", "app.mcp_server", "--transport", "stdio"]
