###############################################################################
# A.R.C.H.I.E. Starship Node  -  Deploy / Update Script (Windows)
# ============================================================================
# Usage:
#   .\deploy-node.ps1                    # Update existing node
#   .\deploy-node.ps1 -Fresh             # Fresh install (writes .env)
#
# Fresh install requires:
#   -NodeId     "node_xxx"
#   -HubUrl     "http://192.168.1.200:3000"  (ALWAYS use LAN mesh IP, never CDN hostname)
#   -HubApiKey  "your-api-key"
#
# Handles: Docker Desktop install, GPU detection, file download, build, start
###############################################################################

param(
    [switch]$Fresh,
    [string]$NodeId,
    [string]$HubUrl = "http://100.64.0.1:3000",
    [string]$HubApiKey,
    [string]$DbPassword = "archie_node_default",
    [string]$InstallDir = "C:\archie-node"
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  A.R.C.H.I.E. Starship Node Deploy" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# =====================================================================
# Pre-flight: Docker Desktop
# =====================================================================
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker Desktop not found. Installing..." -ForegroundColor Yellow

    $installerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
    $installerPath = "$env:TEMP\DockerDesktopInstaller.exe"

    Write-Host "  Downloading Docker Desktop..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    Write-Host "  Running installer (this may take a few minutes)..." -ForegroundColor Cyan
    Start-Process -FilePath $installerPath -ArgumentList "install", "--quiet", "--accept-license" -Wait

    Remove-Item $installerPath -Force -ErrorAction SilentlyContinue

    # Refresh PATH so docker command is available
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host ""
        Write-Host "Docker Desktop installed but requires a RESTART." -ForegroundColor Yellow
        Write-Host "Please restart your computer, then re-run this script." -ForegroundColor Yellow
        exit 0
    }

    Write-Host "[OK] Docker Desktop installed" -ForegroundColor Green
}

# =====================================================================
# Pre-flight: Docker running
# =====================================================================
$dockerRunning = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker Desktop is installed but not running. Starting..." -ForegroundColor Yellow

    $dockerExe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) {
        Start-Process $dockerExe
        Write-Host "  Waiting for Docker to start (up to 90s)..." -ForegroundColor Cyan
        $waited = 0
        while ($waited -lt 90) {
            Start-Sleep -Seconds 5
            $waited += 5
            $null = docker info 2>&1
            if ($LASTEXITCODE -eq 0) { break }
            Write-Host "  ... waiting ($waited`s)" -ForegroundColor Gray
        }
        $null = docker info 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Docker failed to start after 90s. Open Docker Desktop manually and retry." -ForegroundColor Red
            exit 1
        }
    }
    else {
        Write-Host "ERROR: Cannot find Docker Desktop. Open it manually and retry." -ForegroundColor Red
        exit 1
    }
}

Write-Host "[OK] Docker is running" -ForegroundColor Green

# =====================================================================
# Pre-flight: NVIDIA GPU detection
# =====================================================================
$gpuAvailable = $false
try {
    $null = nvidia-smi 2>&1
    if ($LASTEXITCODE -eq 0) {
        $gpuAvailable = $true
        Write-Host "[OK] NVIDIA GPU detected" -ForegroundColor Green
    }
}
catch {}
if (-not $gpuAvailable) {
    Write-Host "[INFO] No NVIDIA GPU detected - Ollama will run on CPU" -ForegroundColor Yellow
}

# =====================================================================
# Create install directory
# =====================================================================
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Write-Host "[OK] Created $InstallDir" -ForegroundColor Green
}
Set-Location $InstallDir

# =====================================================================
# Fresh install: write .env
# =====================================================================
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

    Set-Content .env -Encoding UTF8 -Value @(
        "# A.R.C.H.I.E. Starship Node Configuration",
        "NODE_ID=$NodeId",
        "HUB_URL=$HubUrl",
        "HUB_API_KEY=$HubApiKey",
        "DB_PASSWORD=$DbPassword",
        "OLLAMA_PORT=11434",
        "NODE_API_PORT=3001",
        "HEARTBEAT_INTERVAL=30"
    )

    Write-Host "[OK] .env written (node: $NodeId)" -ForegroundColor Green

    # =====================================================================
    # WSL2 mirrored networking  -  required so Docker containers can reach
    # hub via LAN (192.168.1.x) and Tailscale mesh (100.64.x.x)
    # =====================================================================
    $wslConfig = "$env:USERPROFILE\.wslconfig"
    $needsMirrored = $true
    if (Test-Path $wslConfig) {
        $wslText = Get-Content $wslConfig -Raw
        if ($wslText -match 'networkingMode\s*=\s*mirrored') { $needsMirrored = $false }
    }
    if ($needsMirrored) {
        Write-Host ""
        Write-Host "Configuring WSL2 mirrored networking (required for hub connectivity)..." -ForegroundColor Cyan
        $totalRamGB = [math]::Round((Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum / 1GB)
        $wslRamGB = [math]::Max(8, $totalRamGB - 4)
        $cpuCount = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
        Set-Content $wslConfig -Encoding UTF8 -Value @(
            "[wsl2]",
            "memory=${wslRamGB}GB",
            "processors=$cpuCount",
            "swap=0",
            "localhostForwarding=true",
            "networkingMode=mirrored"
        )
        Write-Host "[OK] .wslconfig written with networkingMode=mirrored" -ForegroundColor Green
        Write-Host "  Restarting WSL2..." -ForegroundColor Yellow
        wsl --shutdown 2>&1 | Out-Null
        Start-Sleep -Seconds 5
        Write-Host "[OK] WSL2 restarted" -ForegroundColor Green
    }
    else {
        Write-Host "[OK] WSL2 mirrored networking already configured" -ForegroundColor Green
    }

    # =====================================================================
    # Auto-join Tailscale mesh (Fresh install only)
    # =====================================================================
    Write-Host ""
    Write-Host "Joining Tailscale mesh..." -ForegroundColor Cyan

    # Request a pre-auth key from the Hub
    $headscaleUrl = "$HubUrl/tools/department-hq/api/nodes/$NodeId/headscale-key"
    $headers = @{ "X-API-Key" = $HubApiKey; "Content-Type" = "application/json" }
    try {
        $keyResp = Invoke-RestMethod -Uri $headscaleUrl -Method Post -Headers $headers -ErrorAction Stop
        $meshAuthKey = $keyResp.auth_key
        $loginServer = $keyResp.login_server

        if ($meshAuthKey) {
            # Install Tailscale if not already present
            if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
                Write-Host "  Installing Tailscale..." -ForegroundColor Yellow
                winget install --id Tailscale.Tailscale --silent --accept-package-agreements --accept-source-agreements 2>$null
                $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            }

            if (Get-Command tailscale -ErrorAction SilentlyContinue) {
                Write-Host "  Joining mesh at $loginServer ..." -ForegroundColor Cyan
                tailscale up --login-server $loginServer --authkey $meshAuthKey --accept-routes --hostname $NodeId 2>&1 | Out-Null
                Start-Sleep -Seconds 3
                $meshIp = (tailscale ip --4 2>$null)
                if ($meshIp) {
                    Write-Host "[OK] Joined mesh  -  mesh IP: $meshIp" -ForegroundColor Green
                    # Report mesh IP back to Hub
                    $vpnBody = @{ vpn_ip = $meshIp } | ConvertTo-Json
                    Invoke-RestMethod -Uri "$HubUrl/tools/department-hq/api/nodes/$NodeId/settings" -Method Put -Headers $headers -Body $vpnBody -ContentType "application/json" -ErrorAction SilentlyContinue | Out-Null
                } else {
                    Write-Host "  [WARN] Tailscale joined but mesh IP not yet assigned" -ForegroundColor Yellow
                }
            } else {
                Write-Host "  [WARN] Tailscale install failed  -  mesh join skipped. Join manually." -ForegroundColor Yellow
            }
        } else {
            Write-Host "  [WARN] Hub returned no auth key  -  mesh join skipped" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "  [WARN] Mesh join failed: $_" -ForegroundColor Yellow
        Write-Host "  Manual join: tailscale up --login-server [hub-url] --authkey [key]" -ForegroundColor Gray
    }
}
else {
    if (-not (Test-Path ".env")) {
        Write-Host "ERROR: No .env found. Run with -Fresh for first-time setup." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Using existing .env" -ForegroundColor Green
}

# =====================================================================
# Read HUB_URL from .env for downloads
# =====================================================================
$envContent = Get-Content .env -Raw
if ($envContent -match 'HUB_URL=(.+)') {
    $DownloadBase = $Matches[1].Trim()
}
else {
    $DownloadBase = $HubUrl
}
$ApiBase = "$DownloadBase/tools/starbase/api/nodes"

Write-Host ""
Write-Host "Downloading files from $DownloadBase ..." -ForegroundColor Cyan

# =====================================================================
# Stop existing containers
# =====================================================================
if (Test-Path "docker-compose.yml") {
    Write-Host "  Stopping existing containers..." -ForegroundColor Yellow
    docker compose down 2>$null
}

# =====================================================================
# Download node files
# =====================================================================
$files = @(
    @{ Url = "$ApiBase/docker-compose.node.yml"; Out = "docker-compose.yml" },
    @{ Url = "$ApiBase/node_sync.py";            Out = "node_sync.py" },
    @{ Url = "$ApiBase/node_api.py";             Out = "node_api.py" },
    @{ Url = "$ApiBase/node_triage.py";          Out = "node_triage.py" },
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

# Download migrations
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

# =====================================================================
# Strip GPU config if no NVIDIA GPU (avoid Docker Compose errors)
# =====================================================================
if (-not $gpuAvailable) {
    Write-Host "  Patching docker-compose.yml for CPU-only mode..." -ForegroundColor Yellow
    $composeContent = Get-Content "docker-compose.yml" -Raw
    # Remove the entire deploy block (GPU reservation)
    $composeContent = $composeContent -replace '(?s)    deploy:\s*\n\s*resources:\s*\n\s*reservations:\s*\n\s*devices:\s*\n\s*- driver: nvidia\s*\n\s*count: all\s*\n\s*capabilities: \[gpu\]\s*\n', ''
    # Remove NVIDIA_VISIBLE_DEVICES env var
    $composeContent = $composeContent -replace '      - NVIDIA_VISIBLE_DEVICES=all\n', ''
    Set-Content "docker-compose.yml" $composeContent -NoNewline
    Write-Host "  [OK] GPU config removed for CPU-only" -ForegroundColor Green
}

# =====================================================================
# Optional: ComfyUI for GPU nodes
# =====================================================================
$comfyEnabled = $false
if ($gpuAvailable) {
    Write-Host ""
    $comfyChoice = Read-Host "Enable image generation with ComfyUI? (Y/n)"
    if ($comfyChoice -ne 'n' -and $comfyChoice -ne 'N') {
        Write-Host "  Enabling ComfyUI service..." -ForegroundColor Cyan
        $composeContent = Get-Content "docker-compose.yml" -Raw
        # Uncomment the ComfyUI service block
        $composeContent = $composeContent -replace '  # comfyui:', '  comfyui:'
        $composeContent = $composeContent -replace '  #   image:', '    image:'
        $composeContent = $composeContent -replace '  #   container_name:', '    container_name:'
        $composeContent = $composeContent -replace '  #   restart:', '    restart:'
        $composeContent = $composeContent -replace '  #   deploy:', '    deploy:'
        $composeContent = $composeContent -replace '  #     resources:', '      resources:'
        $composeContent = $composeContent -replace '  #       reservations:', '        reservations:'
        $composeContent = $composeContent -replace '  #         devices:', '          devices:'
        $composeContent = $composeContent -replace '  #           - driver: nvidia', '            - driver: nvidia'
        $composeContent = $composeContent -replace '  #             count: all', '              count: all'
        $composeContent = $composeContent -replace '  #             capabilities: \[gpu\]', '              capabilities: [gpu]'
        $composeContent = $composeContent -replace '  #   volumes:', '    volumes:'
        $composeContent = $composeContent -replace '  #     - comfyui_data:', '      - comfyui_data:'
        $composeContent = $composeContent -replace '  #   ports:', '    ports:'
        $composeContent = $composeContent -replace '  #     - "\$\{COMFYUI_PORT', '      - "${COMFYUI_PORT'
        $composeContent = $composeContent -replace '  #   networks:', '    networks:'
        $composeContent = $composeContent -replace '  #     - starship_net', '      - starship_net'
        # Uncomment the comfyui_data volume
        $composeContent = $composeContent -replace '  # comfyui_data:', '  comfyui_data:'
        Set-Content "docker-compose.yml" $composeContent -NoNewline
        $comfyEnabled = $true
        Write-Host "  [OK] ComfyUI enabled" -ForegroundColor Green
    } else {
        Write-Host "  [SKIP] ComfyUI not enabled" -ForegroundColor Gray
    }
}

# =====================================================================
# Build and start
# =====================================================================
Write-Host ""
Write-Host "Building containers..." -ForegroundColor Cyan
docker compose build --no-cache
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Build failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
$containerCount = if ($comfyEnabled) { 5 } else { 4 }
Write-Host "Starting $containerCount-container stack..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to start containers." -ForegroundColor Red
    exit 1
}

# =====================================================================
# Verify
# =====================================================================
Write-Host ""
Write-Host "Verifying..." -ForegroundColor Cyan
Start-Sleep -Seconds 8
docker compose ps

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Starship Node deployed successfully!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Ollama:   http://localhost:11434" -ForegroundColor White
Write-Host "  Node API: http://localhost:3001/health" -ForegroundColor White
Write-Host "  GPU:      $(if ($gpuAvailable) {'NVIDIA (enabled)'} else {'CPU only'})" -ForegroundColor White
Write-Host "  ComfyUI:  $(if ($comfyEnabled) {'http://localhost:8188 (enabled)'} else {'Not enabled'})" -ForegroundColor White
Write-Host ""
Write-Host "  Logs:     docker compose logs -f" -ForegroundColor Gray
Write-Host "  Stop:     docker compose down" -ForegroundColor Gray
Write-Host "  Update:   .\deploy-node.ps1" -ForegroundColor Gray
Write-Host ""
