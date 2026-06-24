$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$generalChatRoot = Resolve-Path (Join-Path $scriptDir "..")
$repoRoot = Resolve-Path (Join-Path $generalChatRoot "..\..")
$srcRoot = Join-Path $repoRoot "src"
$dashboardMcpRoot = Join-Path $repoRoot "mcp\dashboard-generator-mcp"
$downloads = Join-Path $generalChatRoot "downloads"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $downloads | Out-Null

$env:GENERAL_CHAT_MCP_ENABLED = "1"
$env:GENERAL_CHAT_MCP_MODE = "external"
$env:GENERAL_CHAT_MCP_CONFIG = "mcp/dashboard-generator-stdio.yaml"
$env:GENERAL_CHAT_MCP_APPROVED_TOOLS = "dashboard_generator.extract_metadata,dashboard_generator.aggregate_data,dashboard_generator.generate_dashboard"
$env:GENERAL_CHAT_MCP_REGISTRY_ENABLED = "0"
$env:GENERAL_CHAT_DASHBOARD_SKILL_ENABLED = "0"

$env:OPENBENCH_EXPORT_DIR = (Resolve-Path $downloads).Path
$env:OPENBENCH_EXPORT_URL_BASE = "/downloads"
$env:DASHBOARD_RENDER_ADAPTER = if ($env:DASHBOARD_RENDER_ADAPTER) { $env:DASHBOARD_RENDER_ADAPTER } else { "default" }
$env:DASHBOARD_GENERATOR_MCP_PYTHONPATH = ((Resolve-Path $srcRoot).Path + [IO.Path]::PathSeparator + (Resolve-Path $dashboardMcpRoot).Path)
$env:DASHBOARD_GENERATOR_MCP_PYTHON = if (Test-Path $venvPython) { (Resolve-Path $venvPython).Path } else { "python" }

Set-Location $generalChatRoot
Write-Host "Starting General Chat with dashboard_generator MCP enabled..."
Write-Host "Config : $env:GENERAL_CHAT_MCP_CONFIG"
Write-Host "Tools  : $env:GENERAL_CHAT_MCP_APPROVED_TOOLS"
Write-Host "Python : $env:DASHBOARD_GENERATOR_MCP_PYTHON"
Write-Host "SDK dashboard skill: disabled for this MCP-only dashboard run"
Write-Host "Exports: $env:OPENBENCH_EXPORT_DIR -> /downloads"
uvicorn server:app --port 8005 --reload
