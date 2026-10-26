"""Prepare SAM 3 weights for the Docker image.

The official SAM 3 weights are gated on Hugging Face, so this script supports
two build-time paths:

1. Copy a local weights/sam3.pt file into /models/sam3.pt.
2. Download sam3.pt from Hugging Face using a build secret or HF_TOKEN.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _read_token() -> str | None:
    secret_path = Path("/run/secrets/hf_token")
    if secret_path.exists():
        token = secret_path.read_text(encoding="utf-8").strip()
        if token:
            return token
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        token = os.getenv(name)
        if token and token.strip():
            return token.strip()
    return None


def _copy_local(source: Path, output: Path) -> bool:
    if not source.exists():
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    print(f"Copied local SAM 3 weights from {source} to {output}")
    return True


def _download_from_hugging_face(output: Path, repo_id: str, filename: str, token: str) -> None:
    from huggingface_hub import hf_hub_download

    output.parent.mkdir(parents=True, exist_ok=True)
    downloaded = hf_hub_download(repo_id=repo_id, filename=filename, token=token)
    shutil.copy2(downloaded, output)
    print(f"Downloaded SAM 3 weights from {repo_id}/{filename} to {output}")


def main() -> int:
    output = Path(_env("SAM3_MODEL_PATH", "/models/sam3.pt"))
    local_source = Path(_env("SAM3_LOCAL_WEIGHTS", "/app/weights/sam3.pt"))
    repo_id = _env("SAM3_HF_REPO", "facebook/sam3")
    filename = _env("SAM3_HF_FILENAME", "sam3.pt")
    mode = _env("SAM3_PREINSTALL", "auto").lower()

    if output.exists():
        print(f"SAM 3 weights already present at {output}")
        return 0

    if _copy_local(local_source, output):
        return 0

    if mode in {"0", "false", "no", "skip", "off"}:
        print("SAM3_PREINSTALL is disabled and no local weights were copied.")
        return 0

    token = _read_token()
    if not token:
        message = (
            "SAM 3 weights are required for this image but were not found. "
            "Place sam3.pt at mcp/sam-segmentation-mcp/weights/sam3.pt, "
            "or set HF_TOKEN after receiving access to https://huggingface.co/facebook/sam3. "
            "Ultralytics does not auto-download sam3.pt."
        )
        if mode in {"required", "require", "1", "true", "yes", "on"}:
            raise SystemExit(message)
        print(f"{message} Skipping download because SAM3_PREINSTALL={mode!r}.")
        return 0

    try:
        _download_from_hugging_face(output, repo_id, filename, token)
    except Exception as exc:
        raise SystemExit(
            "Failed to download SAM 3 weights from Hugging Face. Confirm that "
            "your account has accepted the facebook/sam3 access terms, HF_TOKEN "
            f"is valid, and {filename!r} exists in {repo_id!r}. Original error: {exc}"
        ) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
