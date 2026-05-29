$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$generalChatRoot = Resolve-Path (Join-Path $scriptDir "..")
$repoRoot = Resolve-Path (Join-Path $generalChatRoot "..\..")
$imageSearchRoot = Join-Path $repoRoot "examples\image-search-mcp"
$imageSearchData = Join-Path $imageSearchRoot "data"
$imageSearchModels = Join-Path $imageSearchRoot "models"
$imageSearchPreviews = Join-Path $imageSearchData "previews"
$generalChatUploads = Join-Path $generalChatRoot "uploads"
$hfCache = Join-Path $env:USERPROFILE ".cache\huggingface"
$hfToken = Join-Path $hfCache "token"

New-Item -ItemType Directory -Force -Path $imageSearchData | Out-Null
New-Item -ItemType Directory -Force -Path $imageSearchModels | Out-Null
New-Item -ItemType Directory -Force -Path $imageSearchPreviews | Out-Null
New-Item -ItemType Directory -Force -Path $generalChatUploads | Out-Null

if (-not (Test-Path $hfToken)) {
    Write-Warning "Hugging Face token not found at $hfToken. Run 'hf auth login' and accept DINOv3 access if live indexing fails."
}

$env:GENERAL_CHAT_MCP_ENABLED = "1"
$env:GENERAL_CHAT_MCP_MODE = "external"
$env:GENERAL_CHAT_MCP_CONFIG = "mcp/image-search-docker.yaml"
$env:GENERAL_CHAT_MCP_APPROVED_TOOLS = "image_search.list_index_stats,image_search.search_similar_images"
$env:GENERAL_CHAT_MCP_REGISTRY_ENABLED = "0"

$env:IMAGE_SEARCH_MCP_DATA_PATH = (Resolve-Path $imageSearchData).Path.Replace("\", "/")
$env:IMAGE_SEARCH_MCP_MODELS_PATH = (Resolve-Path $imageSearchModels).Path.Replace("\", "/")
$env:IMAGE_SEARCH_MCP_UPLOADS_PATH = (Resolve-Path $generalChatUploads).Path.Replace("\", "/")
$env:IMAGE_SEARCH_MCP_HF_CACHE_PATH = (Resolve-Path $hfCache).Path.Replace("\", "/")
$env:GENERAL_CHAT_IMAGE_SEARCH_PREVIEW_DIR = (Resolve-Path $imageSearchPreviews).Path

Set-Location $generalChatRoot
Write-Host "Starting General Chat with image_search MCP enabled..."
Write-Host "Config : $env:GENERAL_CHAT_MCP_CONFIG"
Write-Host "Tools  : $env:GENERAL_CHAT_MCP_APPROVED_TOOLS"
Write-Host "Registry: disabled for this dedicated MCP run"
Write-Host "Uploads: $env:IMAGE_SEARCH_MCP_UPLOADS_PATH -> /general-chat/uploads"
uvicorn server:app --port 8005 --reload
