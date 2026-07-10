$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$generalChatRoot = Resolve-Path (Join-Path $scriptDir "..")
$repoRoot = Resolve-Path (Join-Path $generalChatRoot "..\..")
$srcRoot = Join-Path $repoRoot "src"
$dashboardMcpRoot = Join-Path $repoRoot "mcp\dashboard-generator-mcp"
$aggregateMcpRoot = Join-Path $repoRoot "mcp\aggregate-data-mcp"
$downloads = Join-Path $generalChatRoot "downloads"
$stateDir = Join-Path $generalChatRoot ".openbench"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $downloads | Out-Null
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

$env:GENERAL_CHAT_MCP_ENABLED = "1"
$env:GENERAL_CHAT_MCP_MODE = "external"
$env:GENERAL_CHAT_MCP_CONFIG = "mcp/dashboard-generator-stdio.yaml"
$env:GENERAL_CHAT_MCP_APPROVED_TOOLS = "aggregate_data.extract_metadata,aggregate_data.aggregate_data,dashboard_generator.generate_dashboard"
$env:GENERAL_CHAT_MCP_REGISTRY_ENABLED = "0"
$env:GENERAL_CHAT_DASHBOARD_SKILL_ENABLED = "0"

$env:OPENBENCH_EXPORT_DIR = (Resolve-Path $downloads).Path
$env:OPENBENCH_EXPORT_URL_BASE = "/downloads"
$env:OPENBENCH_DASHBOARD_STATE_PATH = (Join-Path (Resolve-Path $stateDir).Path "dashboard_generator_state.json")
$env:DASHBOARD_RENDER_ADAPTER = if ($env:DASHBOARD_RENDER_ADAPTER) { $env:DASHBOARD_RENDER_ADAPTER } else { "default" }
$env:DASHBOARD_GENERATOR_MCP_PYTHONPATH = ((Resolve-Path $srcRoot).Path + [IO.Path]::PathSeparator + (Resolve-Path $dashboardMcpRoot).Path)
$env:AGGREGATE_DATA_MCP_PYTHONPATH = ((Resolve-Path $srcRoot).Path + [IO.Path]::PathSeparator + (Resolve-Path $aggregateMcpRoot).Path)
$env:DASHBOARD_GENERATOR_MCP_PYTHON = if (Test-Path $venvPython) { (Resolve-Path $venvPython).Path } else { "python" }
$env:AGGREGATE_DATA_MCP_PYTHON = $env:DASHBOARD_GENERATOR_MCP_PYTHON

Set-Location $generalChatRoot
Write-Host "Starting General Chat with dashboard_generator and aggregate_data MCP enabled..."
Write-Host "Config : $env:GENERAL_CHAT_MCP_CONFIG"
Write-Host "Tools  : $env:GENERAL_CHAT_MCP_APPROVED_TOOLS"
Write-Host "Python : $env:DASHBOARD_GENERATOR_MCP_PYTHON"
Write-Host "SDK dashboard skill: disabled for this MCP-only dashboard run"
Write-Host "Shared dashboard state: $env:OPENBENCH_DASHBOARD_STATE_PATH"
Write-Host "Exports: $env:OPENBENCH_EXPORT_DIR -> /downloads"
uvicorn server:app --port 8005 --reload --reload-dir src
