# SAM 3 Concept Counting MCP

Standalone Dockerized MCP server for local Ultralytics SAM 3 concept
segmentation. It accepts an image plus a required text concept and counts the
SAM 3 masks that match that concept.

This server is SAM 3 only. It does not support SAM 1, SAM 2, FastSAM,
MobileSAM, `sam_b.pt`, `sam_l.pt`, `sam2_*`, or fallback segmentation models.

## Tool

- `count_objects_with_sam3(concept, image_path?, image_base64?, mime_type?, conf?, min_area_pixels?, return_segments?, return_overlay?)`
- `service_info()`

`count_objects_with_sam3` requires exactly one image source: `image_path` or
`image_base64`. The `concept` should be a short noun phrase such as:

- `dog`
- `person`
- `red apple`
- `yellow school bus`
- `person wearing a hat`

## SAM 3 Weights

Ultralytics does not auto-download `sam3.pt`. You must obtain access to the SAM
3 weights from the approved Hugging Face model page, then provide the file or a
Hugging Face token with access.

Build-time options:

```powershell
# Option A: local file copied into the image
mkdir mcp\sam-segmentation-mcp\weights
# place sam3.pt at mcp\sam-segmentation-mcp\weights\sam3.pt

# Option B: gated Hugging Face download during docker compose build
$env:HF_TOKEN="hf_..."
```

If you already ran `hf auth login`, use the helper script instead of manually
setting `HF_TOKEN`:

```powershell
mcp\sam-segmentation-mcp\scripts\build_with_sam3.ps1
```

`docker compose build` defaults `SAM3_PREINSTALL=required`, so the image build
fails early unless `weights/sam3.pt` exists or `HF_TOKEN` can download
`facebook/sam3/sam3.pt`. Do not commit model weights.

## Docker

Build the CPU image:

```powershell
mcp\sam-segmentation-mcp\scripts\build_with_sam3.ps1
```

Run the MCP server. The default compose build bakes `sam3.pt` into the image at
`/models/sam3.pt`, so no `/models` mount is needed:

```powershell
docker run --rm -i `
  -v "${PWD}\mcp\sam-segmentation-mcp\example-images:/input:ro" `
  -e SAM3_MODEL_PATH=/models/sam3.pt `
  -e IMAGE_INPUT_ROOTS=/input `
  openbench/sam-segmentation-mcp:cpu
```

The process speaks MCP over stdio and waits for client requests.

## Environment

| Variable | Default | Notes |
| --- | --- | --- |
| `SAM3_MODEL_PATH` | `/models/sam3.pt` | Required path to SAM 3 weights |
| `SAM3_PREINSTALL` | `required` in compose | Build-time mode: `required`, `auto`, or `skip` |
| `SAM3_HF_REPO` | `facebook/sam3` | Hugging Face repo used for build-time download |
| `SAM3_HF_FILENAME` | `sam3.pt` | Hugging Face filename copied to `/models/sam3.pt` |
| `HF_TOKEN` | unset | Build secret for gated Hugging Face model access |
| `SAM3_CONF` | `0.25` | Default confidence threshold |
| `SAM3_HALF` | `false` | Use half precision where supported |
| `SAM3_DEVICE` | `cpu` | `cpu` or `cuda` |
| `SAM3_VERBOSE` | `false` | Ultralytics logging |
| `MAX_IMAGE_BYTES` | `10485760` | Max image payload size |
| `MAX_IMAGE_PIXELS` | `12000000` | Max decoded image pixels |
| `IMAGE_INPUT_ROOTS` | `data,uploads,/data,/input,/general-chat/uploads` | Allowed local image roots |
| `RETURN_OVERLAY_DEFAULT` | `false` | Include overlay unless explicitly requested |
| `DEBUG_OUTPUT_DIR` | `/tmp/sam-segmentation-debug` | Writable directory for segmentation debug images |
| `DEBUG_OUTPUT_URL_BASE` | unset | Optional browser-accessible URL prefix for debug images |

## Example MCP Request

```json
{
  "concept": "dog",
  "image_path": "/input/dogs.jpg",
  "conf": 0.25,
  "return_segments": true
}
```

## Example Response

```json
{
  "concept": "dog",
  "count": 3,
  "mask_count": 3,
  "model": "sam3",
  "model_path": "/models/sam3.pt",
  "image_width": 1280,
  "image_height": 720,
  "segments": [
    {
      "id": 1,
      "area_pixels": 35120,
      "bbox": [120, 180, 360, 540],
      "confidence": 0.94
    }
  ],
  "debug": {
    "image_path": "/tmp/sam-segmentation-debug/dog-ab12cd34ef.png",
    "bbox_format": "xyxy",
    "segment_count": 1
  },
  "warnings": []
}
```

Segment bounding boxes use `xyxy` format: `[x1, y1, x2, y2]`. Every response
also writes a debug image with detected boxes, labels, confidence scores, and
mask overlays when masks are available. If `DEBUG_OUTPUT_URL_BASE` is set, the
debug object also includes `image_url`.

If no matching masks are found, the tool returns `count: 0`, `mask_count: 0`,
and a warning instead of crashing.

## General Chat

Build the image with `weights/sam3.pt` or `HF_TOKEN`, then start General Chat:

```powershell
mcp\sam-segmentation-mcp\scripts\build_with_sam3.ps1

openbench demo run general-chat-sam-segmentation
```

The older PowerShell helper remains available at
`examples/general-chat/scripts/run_with_sam_segmentation_mcp.ps1` if you need
to set the environment manually. The CLI command mounts
`examples/general-chat/uploads/_sam_debug` into the SAM container and returns
browser-accessible debug URLs under `/uploads/_sam_debug/...`.

Upload an image and ask:

```text
How many dogs are in this image? Use the SAM 3 counting tool.
```

General Chat should call:

```json
{
  "concept": "dog",
  "image_path": "/general-chat/uploads/<file-id>/<filename>"
}
```

## Smoke Test

Discovery does not require real weights:

```powershell
python mcp\sam-segmentation-mcp\scripts\test_mcp_server.py --mode docker --discovery-only
```

Calling `service_info` reports whether `sam3.pt` is present:

```powershell
python mcp\sam-segmentation-mcp\scripts\test_mcp_server.py --mode docker
```

## Troubleshooting

If SAM 3 fails with `No module named 'clip'`, `No module named 'timm'`, or
`TypeError: 'SimpleTokenizer' object is not callable`, rebuild the image. The
Dockerfile installs SAM 3's CLIP and ViT backbone dependencies before the MCP
server starts:

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File mcp\sam-segmentation-mcp\scripts\build_with_sam3.ps1
```

## Known Limitations

- SAM 3 concept counts are model estimates, not ground truth labels.
- CPU inference can be slow, especially on the first request.
- Real inference requires `sam3.pt`; CI tests mock SAM 3 and do not download it.
- This server handles images only, not video.
- No fallback model is available by design.
