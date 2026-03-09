###############################################################################
# A.R.C.H.I.E. Starship Node — Deploy / Update Script (Windows)
# ============================================================================
# Usage:
#   .\deploy-node.ps1                    # Update existing node
#   .\deploy-node.ps1 -Fresh             # Fresh install (writes .env)
#
# Fresh install requires:
#   -NodeId     "node_xxx"
#   -HubUrl     "http://192.168.1.200:3000"
#   -HubApiKey  "your-api-key"
###############################################################################

param(
    [switch]$Fresh,
    [string]$NodeId,
    [string]$HubUrl = "http://192.168.1.200:3000",
    [string]$HubApiKey,
    [string]$DbPassword = "archie_node_default",
    [string]$InstallDir = "C:\archie-node"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  A.R.C.H.I.E. Starship Node Deploy" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# --- Pre-flight checks ---
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Docker not found. Install Docker Desktop first." -ForegroundColor Red
    exit 1
}

$dockerRunning = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker is not running. Start Docker Desktop." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Docker is running" -ForegroundColor Green

# --- Create install directory ---
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Write-Host "[OK] Created $InstallDir" -ForegroundColor Green
}
Set-Location $InstallDir

# --- Fresh install: write .env ---
if ($Fresh) {
    if (-not $NodeId -or -not $HubApiKey) {
        Write-Host "ERROR: Fresh install requires -NodeId and -HubApiKey" -ForegroundColor Red
        Write-Host "  Example: .\deploy-node.ps1 -Fresh -NodeId node_xxx -HubApiKey your-key" -ForegroundColor Yellow
        exit 1
    }

    if (Test-Path ".env") {
        Copy-Item ".env" ".env.backup" -Force
        Write-Host "[OK] Backed up existing .env" -ForegroundColor Yellow
    }

    @"
# A.R.C.H.I.E. Starship Node Configuration
NODE_ID=$NodeId
HUB_URL=$HubUrl
HUB_API_KEY=$HubApiKey
DB_PASSWORD=$DbPassword
OLLAMA_PORT=11434
NODE_API_PORT=3001
HEARTBEAT_INTERVAL=30
"@ | Set-Content .env -Encoding UTF8

    Write-Host "[OK] .env written (node: $NodeId)" -ForegroundColor Green
}
else {
    if (-not (Test-Path ".env")) {
        Write-Host "ERROR: No .env found. Run with -Fresh for first-time setup." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Using existing .env" -ForegroundColor Green
}

# --- Read HUB_URL from .env for downloads ---
$envContent = Get-Content .env -Raw
if ($envContent -match 'HUB_URL=(.+)') {
    $DownloadBase = $Matches[1].Trim()
}
else {
    $DownloadBase = $HubUrl
}
$ApiBase = "$DownloadBase/tools/bridge/api/nodes"

Write-Host ""
Write-Host "Downloading files from $DownloadBase ..." -ForegroundColor Cyan

# --- Stop existing containers ---
if (Test-Path "docker-compose.yml") {
    Write-Host "  Stopping existing containers..." -ForegroundColor Yellow
    docker compose down 2>$null
}

# --- Download node files ---
$files = @(
    @{ Url = "$ApiBase/docker-compose.node.yml"; Out = "docker-compose.yml" },
    @{ Url = "$ApiBase/node_sync.py";            Out = "node_sync.py" },
    @{ Url = "$ApiBase/node_api.py";             Out = "node_api.py" },
    @{ Url = "$ApiBase/Dockerfile.node";         Out = "Dockerfile.node" }
)

foreach ($f in $files) {
    try {
        Invoke-WebRequest -Uri $f.Url -OutFile $f.Out -UseBasicParsing
        Write-Host "  [OK] $($f.Out)" -ForegroundColor Green
    }
    catch {
        Write-Host "  [FAIL] $($f.Out): $_" -ForegroundColor Red
        exit 1
    }
}

# --- Download migrations ---
if (-not (Test-Path "migrations")) {
    New-Item -ItemType Directory -Path "migrations" -Force | Out-Null
}
try {
    Invoke-WebRequest -Uri "$ApiBase/migrations/001_node_schema.sql" -OutFile "migrations\001_node_schema.sql" -UseBasicParsing
    Write-Host "  [OK] migrations\001_node_schema.sql" -ForegroundColor Green
}
catch {
    Write-Host "  [FAIL] migrations\001_node_schema.sql: $_" -ForegroundColor Red
    exit 1
}

# --- Build and start ---
Write-Host ""
Write-Host "Building containers..." -ForegroundColor Cyan
docker compose build --no-cache
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Build failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Starting 4-container stack..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to start containers." -ForegroundColor Red
    exit 1
}

# --- Verify ---
Write-Host ""
Write-Host "Verifying..." -ForegroundColor Cyan
Start-Sleep -Seconds 5
docker compose ps

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Starship Node deployed successfully!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Ollama:   http://localhost:11434" -ForegroundColor White
Write-Host "  Node API: http://localhost:3001/health" -ForegroundColor White
Write-Host ""
Write-Host "  Logs:  docker compose logs -f" -ForegroundColor Gray
Write-Host "  Stop:  docker compose down" -ForegroundColor Gray
Write-Host ""
