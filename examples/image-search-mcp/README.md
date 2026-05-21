# Local DINOv3 CIFAR-10 MCP Image Search

This example is a fully local MCP server for image similarity search. It uses
DINOv3 to embed images, persists CIFAR-10 embeddings into FAISS or
hnswlib, and answers queries by embedding only the query image before ANN
nearest-neighbor search.

## Architecture

The important performance rule is simple: DINOv3 never runs over the whole
corpus per query.

1. `index_images` downloads CIFAR-10 if needed, embeds the train and test splits in
   batches, normalizes vectors, writes previews, and persists the vector index.
2. `search_similar_images` loads one query image from a path, base64 string,
   URL, or CIFAR-10 test index.
3. The query image is embedded once with DINOv3.
4. FAISS or hnswlib returns the nearest normalized vectors by cosine
   similarity.

DINOv3 is a good default backbone because it is a general image feature
extractor. The default model is the small
`facebook/dinov3-vits16-pretrain-lvd1689m` model instead of a 7B model, which
keeps local MCP usage reasonable.

## Setup

```bash
cd examples/image-search-mcp
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The DINOv3 model card may require accepting Meta's terms on Hugging Face. If the
model download fails with an access error, run:

```bash
huggingface-cli login
```

You can also pre-populate `models/` and run fully from local cache.

## Run The MCP Server

Stdio, for local MCP clients:

```bash
python -m app.mcp_server --transport stdio
```

Streamable HTTP, for development:

```bash
python -m app.mcp_server --transport streamable-http --host 127.0.0.1 --port 8000
```

## Tools

- `index_images(batch_size?, max_items?, write_previews?)`
- `rebuild_index(batch_size?, max_items?, write_previews?)`
- `list_index_stats()`
- `search_similar_images(image_path?, image_base64?, image_url?, cifar10_test_index?, top_k?, threshold?)`
- `remove_image(image_id)`

`search_similar_images` requires exactly one query source. It caps `top_k` to
`TOP_K_MAX` and returns only renderable preview URLs plus metadata (`image_id`,
class label, rank, similarity score, split, and dataset index).
Search can run against any initialized non-empty index. A partial smoke-test
index, such as 16 images, is marked `complete=False` and `partial=True`, but it
is still searchable. Full 60,000-image indexing is recommended for best coverage.

## Index CIFAR-10

For a quick partial indexing smoke test:

```bash
python -c "from app.service import get_service; s=get_service(); print(s.index_images(max_items=256, batch_size=32, write_previews=False)); print(s.list_index_stats())"
```

For the full CIFAR-10 corpus:

```bash
python -c "from app.service import get_service; print(get_service().index_images())"
```

`index_images()` and `rebuild_index()` show an inline progress bar when run from
an interactive terminal. If your shell does not display it, force progress output:

```bash
IMAGE_SEARCH_PROGRESS=1 python -c "from app.service import get_service; print(get_service().rebuild_index(batch_size=64))"
```

PowerShell:

```powershell
$env:IMAGE_SEARCH_PROGRESS="1"
python -c "from app.service import get_service; print(get_service().rebuild_index(batch_size=64))"
```

Verify the corpus before searching:

```bash
python -c "from app.service import get_service; print(get_service().list_index_stats())"
```

Any non-empty initialized index should report `healthy=True`. A full index should
also report `active_count=60000`, `train_count=50000`, `test_count=10000`, and
`complete=True`. Partial indexes report `complete=False` and `partial=True`.
Dataset metadata is cached under `data/cifar10/openbench_cifar10_manifest.json`;
vector metadata and the ANN index are cached under `data/index/`.

## MCP Client Config

Use `mcp-client.example.json` as a starting point:

```json
{
  "servers": {
    "image_search": {
      "command": "python",
      "args": ["-m", "app.mcp_server", "--transport", "stdio"],
      "cwd": "examples/image-search-mcp",
      "type": "stdio"
    }
  }
}
```

## OpenBench Bridge

The OpenBench project skill wrapper lives in `openbench-skill/`.

```bash
openbench mcp list-tools --config examples/image-search-mcp/openbench-mcp.yaml
openbench mcp serve --config examples/image-search-mcp/openbench-mcp.yaml --transport stdio
```

## Docker

CPU:

```bash
docker compose --profile cpu build
docker compose --profile cpu run --rm image-search-mcp-cpu
```

GPU:

```bash
docker compose --profile gpu build
docker compose --profile gpu run --rm image-search-mcp-gpu
```

The GPU profile requires NVIDIA Container Toolkit. If `DEVICE=cuda` is set but
CUDA is unavailable, the embedder falls back to CPU.

Development HTTP server:

```bash
docker compose --profile dev up --build
```

## Docker MCP Toolkit

Docker MCP Toolkit clients can connect through the Gateway over stdio:

```bash
docker mcp gateway run --profile my_profile
```

For direct container-based MCP usage, configure a client command like:

```json
{
  "servers": {
    "image_search": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-v",
        "./data:/data",
        "-v",
        "./models:/models",
        "openbench/image-search-mcp:cpu"
      ],
      "type": "stdio"
    }
  }
}
```

`docker-mcp-server.example.json` documents the server metadata shape for a
custom Docker MCP catalog entry.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `DINO_MODEL_ID` | `facebook/dinov3-vits16-pretrain-lvd1689m` | Hugging Face model id |
| `DEVICE` | `auto` | `auto`, `cpu`, or `cuda` |
| `DATA_PATH` | `data` | CIFAR-10 and preview root |
| `INDEX_PATH` | `data/index` | Vector index directory |
| `MODEL_CACHE_PATH` | `models` | Hugging Face model cache |
| `BATCH_SIZE` | `64` | Indexing batch size |
| `TOP_K_DEFAULT` | `10` | Default search result count |
| `TOP_K_MAX` | `50` | Maximum visual similarity results returned |
| `VECTOR_BACKEND` | `auto` | `auto`, `faiss`, or `hnswlib` |

## Testing

Fast mocked tests:

```bash
pytest tests -q
```

Standalone MCP protocol smoke test, bypassing Codex MCP auto-loading:

```bash
python scripts/test_mcp_server.py --mode docker
```

If you only want to verify MCP handshake and tool discovery:

```bash
python scripts/test_mcp_server.py --mode docker --discovery-only
```

If Docker is the problem, test the local Python stdio server instead:

```bash
python scripts/test_mcp_server.py --mode local
```

To run the full real indexing/search path through MCP, add `--real-index`. This
may download CIFAR-10 and DINOv3 weights:

```bash
python scripts/test_mcp_server.py --mode docker --real-index --batch-size 64
```

For a partial indexing smoke test that intentionally skips search:

```bash
python scripts/test_mcp_server.py --mode docker --real-index --max-items 16 --batch-size 4
```

For Docker tests, the script automatically mounts your host Hugging Face token
cache read-only when `hf auth login` has created `~/.cache/huggingface/token`.
This lets gated DINOv3 downloads work inside the container without printing your
token.

Opt-in live DINOv3/CIFAR-10 test:

```bash
$env:RUN_DINO_CIFAR_LIVE="1"
pytest tests -q
```

## Troubleshooting

- Empty or uninitialized index error: run `index_images` or `rebuild_index`,
  then verify `list_index_stats()["healthy"]` is `True`.
- Hugging Face access error: accept the DINOv3 model terms and run
  `hf auth login`. For Docker, confirm `~/.cache/huggingface/token` exists on
  the host so the tester can mount it into the container.
- FAISS install issue: set `VECTOR_BACKEND=hnswlib`.
- CUDA unavailable: set `DEVICE=cpu` or install NVIDIA Container Toolkit for
  Docker GPU runs.
- Slow first query: the first tool call loads DINOv3 weights into memory.
