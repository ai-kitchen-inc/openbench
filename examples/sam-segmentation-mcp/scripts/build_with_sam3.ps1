param(
    [ValidateSet("cpu", "gpu", "dev")]
    [string]$Profile = "cpu"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$exampleRoot = Resolve-Path (Join-Path $scriptDir "..")
$composeFile = Join-Path $exampleRoot "docker-compose.yml"

$tokenWasSet = -not [string]::IsNullOrWhiteSpace($env:HF_TOKEN)
if (-not $tokenWasSet) {
    $tokenFile = Join-Path $env:USERPROFILE ".cache\huggingface\token"
    if (Test-Path $tokenFile) {
        $token = (Get-Content -Raw $tokenFile).Trim()
    } else {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $token = (& hf auth token 2>$null).Trim()
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    }
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "No HF_TOKEN environment variable is set, and 'hf auth token' did not return a token. Run 'hf auth login' or place sam3.pt at examples\sam-segmentation-mcp\weights\sam3.pt."
    }
    $env:HF_TOKEN = $token
}

try {
    Write-Host "Building SAM 3 MCP Docker image with profile '$Profile'..."
    if ($tokenWasSet) {
        Write-Host "Using HF_TOKEN from the current environment."
    } else {
        Write-Host "Using the existing Hugging Face CLI login as a Docker build secret."
    }
    Write-Host "The token is not printed or stored in the image."
    docker compose -f $composeFile --profile $Profile build
} finally {
    if (-not $tokenWasSet) {
        Remove-Item Env:\HF_TOKEN -ErrorAction SilentlyContinue
    }
}
