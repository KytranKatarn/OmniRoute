# =============================================================================
# A.R.C.H.I.E. Remote Node - Windows Installation Script v1.0.0
# Usage: iwr -useb http://192.168.1.200:3000/tools/bridge/api/nodes/install.ps1 | iex
# =============================================================================

$ErrorActionPreference = "Stop"
$ARCHIE_BASE_URL = "http://192.168.1.200:3000"
$ARCHIE_DIR = "C:\ProgramData\ARCHIE-Node"
$CLIENT_VERSION = "1.0.0"
$OLLAMA_PORT = 11434

# -- Helpers ------------------------------------------------------------------

function Write-Banner {
    Write-Host ""
    Write-Host "  =========================================" -ForegroundColor Cyan
    Write-Host "   A.R.C.H.I.E. Remote Node Installer"      -ForegroundColor Cyan
    Write-Host "   Version $CLIENT_VERSION | Windows"        -ForegroundColor DarkCyan
    Write-Host "  =========================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Number, [string]$Text)
    Write-Host "  [$Number] " -ForegroundColor Yellow -NoNewline
    Write-Host $Text -ForegroundColor White
}

function Write-Ok {
    param([string]$Text)
    Write-Host "      [OK] " -ForegroundColor Green -NoNewline
    Write-Host $Text
}

function Write-Info {
    param([string]$Text)
    Write-Host "      ... " -ForegroundColor DarkGray -NoNewline
    Write-Host $Text -ForegroundColor Gray
}

function Write-Fail {
    param([string]$Text)
    Write-Host "      [FAIL] " -ForegroundColor Red -NoNewline
    Write-Host $Text -ForegroundColor Red
}

# =============================================================================
# STEP 1: Require Administrator
# =============================================================================

Write-Banner
Write-Step "1/7" "Checking administrator privileges..."

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Fail "This script must be run as Administrator."
    Write-Host "      Right-click PowerShell and select 'Run as Administrator'." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}
Write-Ok "Running as Administrator"

# Create working directory
if (-not (Test-Path $ARCHIE_DIR)) {
    New-Item -ItemType Directory -Path $ARCHIE_DIR -Force | Out-Null
    Write-Ok "Created $ARCHIE_DIR"
} else {
    Write-Info "$ARCHIE_DIR already exists"
}

# =============================================================================
# STEP 2: Detect Hardware
# =============================================================================

Write-Step "2/7" "Detecting hardware capabilities..."

try {
    # CPU
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $cpuName = $cpu.Name.Trim()
    $cpuCores = $cpu.NumberOfCores
    Write-Ok "CPU: $cpuName ($cpuCores cores)"

    # RAM
    $cs = Get-CimInstance Win32_ComputerSystem
    $ramGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    Write-Ok "RAM: ${ramGB} GB"

    # GPU
    $gpus = Get-CimInstance Win32_VideoController
    $gpuAvailable = $false
    $gpuName = "None"
    $gpuVramGB = 0

    foreach ($gpu in $gpus) {
        if ($gpu.AdapterRAM -and $gpu.AdapterRAM -gt 0) {
            $vram = [math]::Round($gpu.AdapterRAM / 1GB, 1)
            # AdapterRAM can overflow for large GPUs (returns 4GB max via WMI)
            # Prefer the GPU with the largest reported VRAM
            if ($vram -gt $gpuVramGB) {
                $gpuAvailable = $true
                $gpuName = $gpu.Name.Trim()
                $gpuVramGB = $vram
            }
        }
    }
    if ($gpuAvailable) {
        Write-Ok "GPU: $gpuName (${gpuVramGB} GB VRAM)"
    } else {
        Write-Info "GPU: No dedicated GPU detected (CPU inference only)"
    }

    # Disk
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $diskGB = [math]::Round($disk.Size / 1GB, 1)
    Write-Ok "Disk C: ${diskGB} GB total"

    # OS
    $os = Get-CimInstance Win32_OperatingSystem
    $osInfo = "$($os.Caption) $($os.Version)"
    Write-Ok "OS: $osInfo"
} catch {
    Write-Fail "Hardware detection failed: $_"
    exit 1
}

# =============================================================================
# STEP 3: Install / Verify Ollama
# =============================================================================

Write-Step "3/7" "Setting up Ollama..."

$ollamaInstalled = $false

# Check if ollama is already available
try {
    $ollamaCheck = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCheck) {
        $ollamaInstalled = $true
        Write-Ok "Ollama already installed at $($ollamaCheck.Source)"
    }
} catch {
    $ollamaInstalled = $false
}

# Install Ollama if missing
if (-not $ollamaInstalled) {
    Write-Info "Ollama not found, downloading installer..."
    $installerPath = Join-Path $env:TEMP "OllamaSetup.exe"

    try {
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" `
            -OutFile $installerPath -UseBasicParsing
        Write-Ok "Downloaded OllamaSetup.exe"

        Write-Info "Running silent install (this may take a minute)..."
        $proc = Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT", "/NORESTART" `
            -Wait -PassThru
        if ($proc.ExitCode -ne 0) {
            Write-Fail "Ollama installer exited with code $($proc.ExitCode)"
            exit 1
        }
        # Refresh PATH so we can find ollama
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                     [System.Environment]::GetEnvironmentVariable("Path", "User")
        Write-Ok "Ollama installed successfully"
    } catch {
        Write-Fail "Failed to install Ollama: $_"
        exit 1
    } finally {
        if (Test-Path $installerPath) { Remove-Item $installerPath -Force -ErrorAction SilentlyContinue }
    }
}

# Set OLLAMA_HOST to allow network access
Write-Info "Configuring OLLAMA_HOST=0.0.0.0 for network access..."
try {
    [System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0", "Machine")
    $env:OLLAMA_HOST = "0.0.0.0"
    Write-Ok "OLLAMA_HOST set to 0.0.0.0 (system-wide)"
} catch {
    Write-Fail "Could not set OLLAMA_HOST: $_"
}

# Restart Ollama service to pick up new env
Write-Info "Restarting Ollama service..."
try {
    $svc = Get-Service -Name "Ollama" -ErrorAction SilentlyContinue
    if ($svc) {
        Restart-Service -Name "Ollama" -Force
        Start-Sleep -Seconds 3
        Write-Ok "Ollama service restarted"
    } else {
        Write-Info "Ollama service not found (may run as user process), starting ollama serve..."
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 3
    }
} catch {
    Write-Info "Could not restart Ollama service, attempting to start manually..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

# Verify Ollama is responding
Write-Info "Verifying Ollama API..."
$ollamaReady = $false
for ($i = 0; $i -lt 10; $i++) {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:$OLLAMA_PORT/api/tags" -Method Get -TimeoutSec 5
        $ollamaReady = $true
        $modelCount = 0
        if ($resp.models) { $modelCount = $resp.models.Count }
        Write-Ok "Ollama API responding ($modelCount models loaded)"
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ollamaReady) {
    Write-Fail "Ollama API not responding on port $OLLAMA_PORT after 20 seconds"
    exit 1
}

# =============================================================================
# STEP 4: Pull Starter Models
# =============================================================================

Write-Step "4/7" "Pulling starter models (M4000-friendly)..."

$models = @(
    @{ Name = "qwen2.5:7b";  Desc = "~4.7 GB - primary reasoning model" },
    @{ Name = "llama3.2:3b"; Desc = "~2 GB - fast lightweight model" }
)

foreach ($model in $models) {
    Write-Info "Pulling $($model.Name) ($($model.Desc))..."
    try {
        & ollama pull $model.Name 2>&1 | Out-Null
        Write-Ok "Pulled $($model.Name)"
    } catch {
        Write-Fail "Failed to pull $($model.Name): $_"
        Write-Info "You can pull this model later with: ollama pull $($model.Name)"
    }
}

# =============================================================================
# STEP 5: Register with A.R.C.H.I.E.
# =============================================================================

Write-Step "5/7" "Registering node with A.R.C.H.I.E. platform..."

# Determine local IP (prefer non-loopback IPv4)
$localIP = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.PrefixOrigin -ne "WellKnown" } |
    Sort-Object -Property InterfaceIndex |
    Select-Object -First 1).IPAddress

if (-not $localIP) { $localIP = "127.0.0.1" }

$nodeName = $env:COMPUTERNAME
$registerUrl = "$ARCHIE_BASE_URL/tools/bridge/api/nodes/register"

$payload = @{
    node_name       = $nodeName
    vpn_ip          = $localIP
    hostname        = $nodeName
    port            = $OLLAMA_PORT
    gpu_available   = $gpuAvailable
    gpu_model       = $gpuName
    gpu_vram_gb     = $gpuVramGB
    cpu_cores       = $cpuCores
    cpu_model       = $cpuName
    ram_gb          = $ramGB
    disk_gb         = $diskGB
    os_info         = $osInfo
    ollama_available = $true
    client_version  = $CLIENT_VERSION
    tags            = @("windows", "gaming-rig")
} | ConvertTo-Json -Depth 3

Write-Info "Registering $nodeName ($localIP) ..."

try {
    $response = Invoke-RestMethod -Uri $registerUrl -Method Post `
        -ContentType "application/json" -Body $payload -TimeoutSec 15

    $nodeId  = $response.node_id
    $apiKey  = $response.api_key

    if (-not $nodeId -or -not $apiKey) {
        Write-Fail "Registration response missing node_id or api_key"
        exit 1
    }

    # Save config to disk
    $config = @{
        node_id            = $nodeId
        api_key            = $apiKey
        node_name          = $nodeName
        server_url         = $ARCHIE_BASE_URL
        ollama_port        = $OLLAMA_PORT
        heartbeat_interval = 30
        client_version     = $CLIENT_VERSION
        registered_at      = (Get-Date -Format "o")
    }
    if ($response.config) {
        $config["server_config"] = $response.config
    }

    $configPath = Join-Path $ARCHIE_DIR "config.json"
    $config | ConvertTo-Json -Depth 5 | Set-Content -Path $configPath -Encoding UTF8
    Write-Ok "Registered as node $nodeId"
    Write-Ok "Config saved to $configPath"
} catch {
    Write-Fail "Registration failed: $_"
    Write-Host "      Ensure the A.R.C.H.I.E. platform is reachable at $ARCHIE_BASE_URL" -ForegroundColor Yellow
    exit 1
}

# =============================================================================
# STEP 6: Install Heartbeat Service
# =============================================================================

Write-Step "6/7" "Installing heartbeat service..."

# Copy heartbeat script from same directory as this installer
$scriptDir = $null
if ($PSScriptRoot) {
    $scriptDir = $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    $scriptDir = Split-Path $MyInvocation.MyCommand.Path -Parent
}

$heartbeatDst = Join-Path $ARCHIE_DIR "heartbeat.ps1"

if ($scriptDir) {
    $heartbeatSrc = Join-Path $scriptDir "heartbeat.ps1"
    if (Test-Path $heartbeatSrc) {
        Copy-Item -Path $heartbeatSrc -Destination $heartbeatDst -Force
        Write-Ok "Copied heartbeat.ps1 to $ARCHIE_DIR"
    } else {
        Write-Info "heartbeat.ps1 not found at $heartbeatSrc, downloading from server..."
        try {
            $heartbeatUrl = "$ARCHIE_BASE_URL/tools/bridge/api/nodes/heartbeat.ps1"
            Invoke-WebRequest -Uri $heartbeatUrl -OutFile $heartbeatDst -UseBasicParsing
            Write-Ok "Downloaded heartbeat.ps1 from server"
        } catch {
            Write-Fail "Could not obtain heartbeat.ps1: $_"
            exit 1
        }
    }
} else {
    Write-Info "Running via piped execution, downloading heartbeat.ps1..."
    try {
        $heartbeatUrl = "$ARCHIE_BASE_URL/tools/bridge/api/nodes/heartbeat.ps1"
        Invoke-WebRequest -Uri $heartbeatUrl -OutFile $heartbeatDst -UseBasicParsing
        Write-Ok "Downloaded heartbeat.ps1 from server"
    } catch {
        Write-Fail "Could not download heartbeat.ps1: $_"
        exit 1
    }
}

# Register Scheduled Task to run heartbeat every 30 seconds
# Windows Task Scheduler minimum interval is 1 minute, so we create two triggers offset by 30s
Write-Info "Creating scheduled task ARCHIE-Node-Heartbeat..."

try {
    # Remove existing task if present
    $existingTask = Get-ScheduledTask -TaskName "ARCHIE-Node-Heartbeat" -ErrorAction SilentlyContinue
    if ($existingTask) {
        Unregister-ScheduledTask -TaskName "ARCHIE-Node-Heartbeat" -Confirm:$false
        Write-Info "Removed previous scheduled task"
    }

    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$heartbeatDst`""

    # Two triggers 30 seconds apart achieve ~30-second intervals
    $trigger1 = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes 1)
    $trigger2 = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddSeconds(30)) `
        -RepetitionInterval (New-TimeSpan -Minutes 1)

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)

    Register-ScheduledTask `
        -TaskName "ARCHIE-Node-Heartbeat" `
        -Action $action `
        -Trigger @($trigger1, $trigger2) `
        -Settings $settings `
        -User "SYSTEM" `
        -RunLevel Highest `
        -Description "A.R.C.H.I.E. remote node heartbeat - reports status every 30 seconds" | Out-Null

    Start-ScheduledTask -TaskName "ARCHIE-Node-Heartbeat"
    Write-Ok "Scheduled task registered and started (30-second interval)"
} catch {
    Write-Fail "Failed to create scheduled task: $_"
    Write-Info "You can manually run: powershell -File `"$heartbeatDst`""
}

# =============================================================================
# STEP 7: Poll for Approval
# =============================================================================

Write-Step "7/7" "Waiting for admin approval..."
Write-Host ""
Write-Host "      Node registered! An admin must approve this node on the" -ForegroundColor Yellow
Write-Host "      A.R.C.H.I.E. dashboard before it can accept work." -ForegroundColor Yellow
Write-Host ""

$statusUrl = "$ARCHIE_BASE_URL/tools/bridge/api/nodes/$nodeId/status"
$headers = @{ "X-Node-API-Key" = $apiKey }
$approved = $false
$pollCount = 0

while (-not $approved) {
    $pollCount++
    try {
        $statusResp = Invoke-RestMethod -Uri $statusUrl -Method Get `
            -Headers $headers -TimeoutSec 10

        if ($statusResp.approval_status -eq "approved") {
            $approved = $true
        } else {
            $dots = "." * (($pollCount % 3) + 1)
            Write-Host "`r      Waiting for approval$($dots.PadRight(3))   (poll #$pollCount)" `
                -ForegroundColor DarkGray -NoNewline
            Start-Sleep -Seconds 5
        }
    } catch {
        Write-Host "`r      Polling failed, retrying...          " -ForegroundColor DarkYellow -NoNewline
        Start-Sleep -Seconds 5
    }
}

# =============================================================================
# STEP 8: Deployment Mode
# =============================================================================

$fullStackDeployed = $false

function Install-DockerStack {
    Write-Step "8b" "Installing full-stack Docker deployment..."

    # --- Check Docker ---
    $dockerAvailable = $false
    try {
        $dockerCheck = Get-Command docker -ErrorAction SilentlyContinue
        if ($dockerCheck) {
            $dockerAvailable = $true
            Write-Ok "Docker found at $($dockerCheck.Source)"
        }
    } catch {
        $dockerAvailable = $false
    }

    if (-not $dockerAvailable) {
        Write-Fail "Docker is not installed."
        Write-Host "      Please install Docker Desktop for Windows:" -ForegroundColor Yellow
        Write-Host "      https://docs.docker.com/desktop/install/windows-install/" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "      After installing Docker Desktop, re-run this script and choose Full-stack." -ForegroundColor Yellow
        return
    }

    # --- Check Docker Compose ---
    try {
        $composeVersion = & docker compose version 2>&1
        Write-Ok "Docker Compose available ($composeVersion)"
    } catch {
        Write-Fail "docker compose not available. Please update Docker Desktop."
        return
    }

    # --- Create deployment directory ---
    $deployDir = "C:\ProgramData\ARCHIE-Node\docker"
    if (-not (Test-Path $deployDir)) {
        New-Item -ItemType Directory -Path $deployDir -Force | Out-Null
    }
    Write-Ok "Deployment directory: $deployDir"

    # --- Download docker-compose.node.yml ---
    $composeUrl = "$ARCHIE_BASE_URL/tools/bridge/api/nodes/docker-compose.node.yml"
    Write-Info "Downloading docker-compose.node.yml..."
    try {
        Invoke-WebRequest -Uri $composeUrl -OutFile (Join-Path $deployDir "docker-compose.yml") -UseBasicParsing
        Write-Ok "Downloaded docker-compose.yml"
    } catch {
        Write-Fail "Failed to download docker-compose.node.yml: $_"
        return
    }

    # --- Download node_sync.py ---
    $syncUrl = "$ARCHIE_BASE_URL/tools/bridge/api/nodes/node_sync.py"
    $nodeClientDir = Join-Path $deployDir "node_client"
    if (-not (Test-Path $nodeClientDir)) {
        New-Item -ItemType Directory -Path $nodeClientDir -Force | Out-Null
    }
    Write-Info "Downloading node_sync.py..."
    try {
        Invoke-WebRequest -Uri $syncUrl -OutFile (Join-Path $nodeClientDir "node_sync.py") -UseBasicParsing
        Write-Ok "Downloaded node_sync.py"
    } catch {
        Write-Fail "Failed to download node_sync.py: $_"
        return
    }

    # --- Generate credentials and detect host ---
    $dbPassword = -join ((1..32) | ForEach-Object { [char](Get-Random -Minimum 33 -Maximum 126) })
    $hostIP = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.PrefixOrigin -ne "WellKnown" } |
        Sort-Object -Property InterfaceIndex |
        Select-Object -First 1).IPAddress
    if (-not $hostIP) { $hostIP = "127.0.0.1" }

    Write-Ok "Host IP: $hostIP"

    # --- Create .env file ---
    $envContent = @"
# A.R.C.H.I.E. Business Node Configuration
# Generated by install.ps1 on $(Get-Date -Format "o")
NODE_ID=$nodeId
HUB_URL=$ARCHIE_BASE_URL
HUB_API_KEY=$apiKey
DB_PASSWORD=$dbPassword
ARCHIE_VERSION=$CLIENT_VERSION
HOST_IP=$hostIP
DEPLOYMENT_MODE=business_node
"@
    $envPath = Join-Path $deployDir ".env"
    $envContent | Set-Content -Path $envPath -Encoding UTF8
    Write-Ok "Environment file created at $envPath"

    # --- Pull and start containers ---
    Write-Info "Pulling Docker images (this may take several minutes)..."
    try {
        Push-Location $deployDir
        & docker compose pull
        Write-Ok "Docker images pulled"

        Write-Info "Starting containers..."
        & docker compose up -d
        Write-Ok "Docker stack is running"
        Pop-Location
    } catch {
        Pop-Location
        Write-Fail "Docker deployment failed: $_"
        return
    }

    # --- Print Docker stack info ---
    Write-Host ""
    Write-Host "      --- Full-Stack Deployment Active ---" -ForegroundColor Green
    Write-Host "      Platform:   http://${hostIP}:3000"     -ForegroundColor White
    Write-Host "      Ollama:     http://${hostIP}:$OLLAMA_PORT" -ForegroundColor White
    Write-Host "      Compose:    $deployDir\docker-compose.yml" -ForegroundColor White
    Write-Host "      Env File:   $envPath"                  -ForegroundColor White
    Write-Host ""

    $script:fullStackDeployed = $true
    $script:dockerHostIP = $hostIP
    $script:dockerDeployDir = $deployDir
}

Write-Host ""
Write-Host "  =========================================" -ForegroundColor Cyan
Write-Host "   DEPLOYMENT MODE"                          -ForegroundColor Cyan
Write-Host "  =========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1) Ollama-only (current setup - just LLM serving)" -ForegroundColor White
Write-Host "  2) Full-stack  (complete ARCHIE business node with Docker)" -ForegroundColor White
Write-Host ""

$deployMode = Read-Host "  Choose deployment mode [1/2]"

if ($deployMode -eq "2") {
    Install-DockerStack
}

# -- Done! --------------------------------------------------------------------

Write-Host ""
Write-Host ""
Write-Host "  =========================================" -ForegroundColor Green
Write-Host "   Node approved! Setup complete."          -ForegroundColor Green
Write-Host "  =========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Node ID:    $nodeId"                       -ForegroundColor White
Write-Host "  Node Name:  $nodeName"                     -ForegroundColor White
Write-Host "  Local IP:   $localIP"                      -ForegroundColor White
Write-Host "  Ollama:     http://localhost:$OLLAMA_PORT"  -ForegroundColor White
Write-Host "  Config:     $ARCHIE_DIR\config.json"       -ForegroundColor White
Write-Host "  Heartbeat:  Scheduled task running"        -ForegroundColor White
if ($fullStackDeployed) {
    Write-Host "  Mode:       Full-stack (Docker)"       -ForegroundColor White
    Write-Host "  Platform:   http://${dockerHostIP}:3000" -ForegroundColor White
    Write-Host "  Compose:    $dockerDeployDir\docker-compose.yml" -ForegroundColor White
} else {
    Write-Host "  Mode:       Ollama-only"               -ForegroundColor White
}
Write-Host ""
Write-Host "  The heartbeat service is running. This node will" -ForegroundColor Gray
Write-Host "  automatically receive work assignments from A.R.C.H.I.E." -ForegroundColor Gray
Write-Host ""
