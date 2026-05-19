# image-search-mcp

Local DINOv3 CIFAR-10 image similarity search tools backed by a persistent
FAISS or HNSW vector index.

## Triggers

- The user wants to search visually similar images.
- The user wants to index CIFAR-10 locally for image retrieval.
- The user wants MCP-compatible image search through OpenBench.

## Tools

- `search_similar_images` - query similar CIFAR-10 train images from one path, base64 image, URL, or CIFAR-10 test index.
- `index_images` - index missing CIFAR-10 train images.
- `rebuild_index` - clear and rebuild the image index.
- `list_index_stats` - inspect index health and persistence paths.
- `remove_image` - remove an indexed image id.

## Dependencies

- mcp[cli]
- torch
- torchvision
- transformers
- Pillow
- numpy
- faiss-cpu or hnswlib

## Version

0.1.0
