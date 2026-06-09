Place `sam3.pt` in this directory before building if you want the Docker image
to include the SAM 3 weights at `/models/sam3.pt`.

Do not commit `sam3.pt` to git.

Alternatively, set `HF_TOKEN` after receiving access to
https://huggingface.co/facebook/sam3 and run Docker Compose. The build downloads
`facebook/sam3/sam3.pt` into the image when `SAM3_PREINSTALL=required` or
`SAM3_PREINSTALL=auto`.

You can also mount the weights at runtime for custom Docker runs:

```bash
docker run --rm -i -v /local/path/to/sam3.pt:/models/sam3.pt:ro openbench/sam-segmentation-mcp:cpu
```
