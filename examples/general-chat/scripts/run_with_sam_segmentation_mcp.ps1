$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$generalChatRoot = Resolve-Path (Join-Path $scriptDir "..")
$repoRoot = Resolve-Path (Join-Path $generalChatRoot "..\..")
$generalChatUploads = Join-Path $generalChatRoot "uploads"
$samDebugUploads = Join-Path $generalChatUploads "_sam_debug"

New-Item -ItemType Directory -Force -Path $generalChatUploads | Out-Null
New-Item -ItemType Directory -Force -Path $samDebugUploads | Out-Null

$env:GENERAL_CHAT_MCP_ENABLED = "1"
$env:GENERAL_CHAT_MCP_MODE = "external"
$env:GENERAL_CHAT_MCP_CONFIG = "mcp/sam-segmentation-docker.yaml"
$env:GENERAL_CHAT_MCP_APPROVED_TOOLS = "sam_segmentation.count_objects_with_sam3"
$env:GENERAL_CHAT_MCP_REGISTRY_ENABLED = "0"

$env:SAM_SEGMENTATION_MCP_UPLOADS_PATH = (Resolve-Path $generalChatUploads).Path.Replace("\", "/")
$env:SAM_SEGMENTATION_MCP_DEBUG_PATH = (Resolve-Path $samDebugUploads).Path.Replace("\", "/")

Set-Location $generalChatRoot
Write-Host "Starting General Chat with sam_segmentation MCP enabled..."
Write-Host "Config : $env:GENERAL_CHAT_MCP_CONFIG"
Write-Host "Tools  : $env:GENERAL_CHAT_MCP_APPROVED_TOOLS"
Write-Host "Registry: disabled for this dedicated MCP run"
Write-Host "Uploads: $env:SAM_SEGMENTATION_MCP_UPLOADS_PATH -> /general-chat/uploads"
Write-Host "Debug  : $env:SAM_SEGMENTATION_MCP_DEBUG_PATH -> /general-chat/uploads/_sam_debug"
Write-Host "Weights: baked into openbench/sam-segmentation-mcp:cpu at /models/sam3.pt"
uvicorn server:app --port 8005 --reload --reload-dir src
