# =============================================================================
# A.R.C.H.I.E. Fleet Node Installer v4.0 — Windows
# Usage:
#   irm http://192.168.1.200:3000/tools/starbase/api/nodes/install.ps1 | iex
#   or: .\install.ps1 -HubUrl http://192.168.1.200:3000 -NodeToken "xxx"
#
# Kytran Empowerment Technologies
# =============================================================================

param(
    [string]$HubUrl = "",
    [string]$NodeToken = "",
    [string]$NodeName = "",
    [switch]$SkipGpu,
    [switch]$SkipComfyUI
)

$ErrorActionPreference = "Stop"
$ARCHIE_DIR       = "C:\ProgramData\ARCHIE-Node"
$CLIENT_VERSION   = "4.0.0"
$OLLAMA_PORT      = 11434
$TASK_NAME        = "ARCHIE-Node-Sync"
$OLD_TASK_NAME    = "ARCHIE-Node-Heartbeat"

# -- Helpers ------------------------------------------------------------------

function Write-Banner {
    Write-Host ""
    Write-Host "     _    ____   ____ _   _ ___ _____" -ForegroundColor Cyan
    Write-Host "    / \  |  _ \ / ___| | | |_ _| ____|" -ForegroundColor Cyan
    Write-Host "   / _ \ | |_) | |   | |_| || ||  _|" -ForegroundColor Cyan
    Write-Host "  / ___ \|  _ <| |___|  _  || || |___" -ForegroundColor Cyan
    Write-Host " /_/   \_\_| \_\\____|_| |_|___|_____|" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   Fleet Node Installer v$CLIENT_VERSION" -ForegroundColor White -BackgroundColor DarkCyan
    Write-Host "   Kytran Empowerment Technologies" -ForegroundColor DarkCyan
    Write-Host ""
}

function Write-Step {
    param([string]$Number, [string]$Text)
    Write-Host ""
    Write-Host "  === Step $Number`: $Text ===" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Text)
    Write-Host "    [OK] " -ForegroundColor Green -NoNewline
    Write-Host $Text
}

function Write-Warn {
    param([string]$Text)
    Write-Host "    [WARN] " -ForegroundColor Yellow -NoNewline
    Write-Host $Text
}

function Write-Fail {
    param([string]$Text)
    Write-Host "    [FAIL] " -ForegroundColor Red -NoNewline
    Write-Host $Text -ForegroundColor Red
    exit 1
}

function Write-Info {
    param([string]$Text)
    Write-Host "    ... " -ForegroundColor DarkGray -NoNewline
    Write-Host $Text -ForegroundColor Gray
}

# =============================================================================
# STEP 0: Prerequisites
# =============================================================================

Write-Banner
Write-Step "0" "Prerequisites"

# Administrator check
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Fail "Must run as Administrator. Right-click PowerShell > Run as Administrator."
}
Write-Ok "Running as Administrator"

# Hub URL
if (-not $HubUrl) {
    $HubUrl = Read-Host "  Enter Hub URL (e.g. http://192.168.1.200:3000)"
}
if (-not $HubUrl) { Write-Fail "Hub URL is required." }
$HubUrl = $HubUrl.TrimEnd("/")
Write-Ok "Hub: $HubUrl"

# Node Token
if (-not $NodeToken) {
    $NodeToken = Read-Host "  Enter Node Token (from Starbase > Network > Add Node)"
}
if (-not $NodeToken) { Write-Fail "Node Token is required." }
Write-Ok "Token provided"

# Node Name
if (-not $NodeName) { $NodeName = $env:COMPUTERNAME }

# =============================================================================
# STEP 1: Hardware Detection
# =============================================================================

Write-Step "1" "Hardware Detection"

try {
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $cpuName = $cpu.Name.Trim()
    $cpuCores = $cpu.NumberOfCores
    Write-Ok "CPU: $cpuName ($cpuCores cores)"

    $cs = Get-CimInstance Win32_ComputerSystem
    $ramGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 0)
    Write-Ok "RAM: ${ramGB}GB"

    $gpuAvailable = $false
    $gpuName = "none"
    $gpuVramGB = 0
    if (-not $SkipGpu) {
        $gpus = Get-CimInstance Win32_VideoController
        foreach ($gpu in $gpus) {
            if ($gpu.AdapterRAM -and $gpu.AdapterRAM -gt 0) {
                $vram = [math]::Round($gpu.AdapterRAM / 1GB, 0)
                if ($vram -gt $gpuVramGB) {
                    $gpuAvailable = $true
                    $gpuName = $gpu.Name.Trim()
                    $gpuVramGB = $vram
                }
            }
        }
    }
    if ($gpuAvailable) {
        Write-Ok "GPU: $gpuName (${gpuVramGB}GB VRAM)"
    } else {
        Write-Info "GPU: None detected (CPU inference only)"
    }

    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $diskGB = [math]::Round($disk.FreeSpace / 1GB, 0)
    Write-Ok "Disk: ${diskGB}GB free"

    $os = Get-CimInstance Win32_OperatingSystem
    $osInfo = "$($os.Caption) $($os.Version)"
    Write-Ok "OS: $osInfo"
} catch {
    Write-Fail "Hardware detection failed: $_"
}

# =============================================================================
# STEP 2: Docker Setup
# =============================================================================

Write-Step "2" "Docker Setup"

$dockerAvailable = $false
try {
    $dockerVer = docker --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $dockerAvailable = $true
        Write-Ok "Docker: $dockerVer"
    }
} catch {}

if (-not $dockerAvailable) {
    Write-Warn "Docker not found. Please install Docker Desktop from https://www.docker.com/products/docker-desktop/"
    Write-Info "After installing Docker Desktop, restart this script."
    Write-Info "Continuing without Docker (native Ollama mode)..."
}

$dockerComposeAvailable = $false
if ($dockerAvailable) {
    try {
        docker compose version 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $dockerComposeAvailable = $true
            Write-Ok "Docker Compose available"
        }
    } catch {}
}

# Check for native Ollama
$ollamaReady = $false
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:$OLLAMA_PORT/api/tags" -Method Get -TimeoutSec 5
    $ollamaReady = $true
    $modelCount = 0
    if ($resp.models) { $modelCount = $resp.models.Count }
    Write-Ok "Ollama responding ($modelCount models loaded)"
} catch {
    Write-Info "Ollama not detected on localhost:$OLLAMA_PORT"
    if (-not $dockerAvailable) {
        Write-Info "Install Ollama from https://ollama.com/download"
    }
}

# =============================================================================
# STEP 3: Register with Hub
# =============================================================================

Write-Step "3" "Hub Registration"

$localIP = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.PrefixOrigin -ne "WellKnown" } |
    Sort-Object -Property InterfaceIndex |
    Select-Object -First 1).IPAddress
if (-not $localIP) { $localIP = "127.0.0.1" }

$registerUrl = "$HubUrl/tools/starbase/api/nodes/register"
$payload = @{
    token            = $NodeToken
    node_name        = $NodeName
    hostname         = $localIP
    port             = $OLLAMA_PORT
    gpu_available    = $gpuAvailable
    gpu_model        = $gpuName
    gpu_vram_gb      = $gpuVramGB
    cpu_cores        = $cpuCores
    cpu_model        = $cpuName
    ram_gb           = $ramGB
    disk_gb          = $diskGB
    os_info          = $osInfo
    ollama_available = $ollamaReady
    docker_available = $dockerAvailable
    client_version   = $CLIENT_VERSION
    tags             = @("windows")
} | ConvertTo-Json -Depth 3

Write-Info "Registering $NodeName ($localIP)..."

try {
    $response = Invoke-RestMethod -Uri $registerUrl -Method Post `
        -ContentType "application/json" -Body $payload -TimeoutSec 15

    $nodeId  = $response.node_id
    $apiKey  = $response.api_key
    $headscaleAuthkey = $response.headscale_authkey
    $headscaleUrl = $response.headscale_url

    if (-not $nodeId -or -not $apiKey) {
        Write-Fail "Registration response missing node_id or api_key"
    }

    Write-Ok "Registered as: $nodeId"
    if ($headscaleAuthkey) {
        Write-Ok "Mesh auth key received"
    } else {
        Write-Warn "No mesh auth key — LAN-only mode"
    }
} catch {
    Write-Fail "Registration failed: $_"
}

# =============================================================================
# STEP 4: Tailscale Mesh VPN
# =============================================================================

Write-Step "4" "Mesh VPN Setup"

$meshIP = ""
if ($headscaleAuthkey) {
    # Check if Tailscale is installed
    $tailscaleInstalled = $false
    try {
        $tsVer = tailscale version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $tailscaleInstalled = $true
            Write-Ok "Tailscale already installed"
        }
    } catch {}

    if (-not $tailscaleInstalled) {
        Write-Info "Installing Tailscale..."
        try {
            # Download Tailscale MSI installer
            $tsUrl = "https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi"
            $tsInstaller = "$env:TEMP\tailscale-setup.msi"
            Invoke-WebRequest -Uri $tsUrl -OutFile $tsInstaller -UseBasicParsing
            Start-Process msiexec.exe -ArgumentList "/i `"$tsInstaller`" /qn" -Wait -NoNewWindow
            Start-Sleep -Seconds 5
            Write-Ok "Tailscale installed"
            $tailscaleInstalled = $true
        } catch {
            Write-Warn "Tailscale install failed: $_"
            Write-Info "Install manually from https://tailscale.com/download/windows"
        }
    }

    if ($tailscaleInstalled) {
        Write-Info "Joining mesh at $headscaleUrl..."
        try {
            tailscale up --login-server=$headscaleUrl --authkey=$headscaleAuthkey --hostname=$NodeName --ssh 2>&1 | Out-Null
            Start-Sleep -Seconds 5
            $meshIP = (tailscale ip -4 2>&1).Trim()
            if ($meshIP) {
                Write-Ok "Mesh VPN connected ($meshIP)"

                # Report mesh IP back to hub
                try {
                    $meshPayload = @{ mesh_ip = $meshIP } | ConvertTo-Json
                    Invoke-RestMethod -Uri "$HubUrl/tools/starbase/api/nodes/$nodeId/mesh-ip" `
                        -Method Post -ContentType "application/json" `
                        -Headers @{ "X-Node-API-Key" = $apiKey } `
                        -Body $meshPayload -TimeoutSec 5 | Out-Null
                    Write-Ok "Mesh IP reported to hub"
                } catch {
                    Write-Warn "Could not report mesh IP: $_"
                }
            } else {
                Write-Warn "Tailscale connected but no IP yet"
            }
        } catch {
            Write-Warn "Mesh join failed: $_"
        }
    }
} else {
    Write-Info "Skipping mesh VPN — no auth key provided"
}

# =============================================================================
# STEP 5: Directory Structure
# =============================================================================

Write-Step "5" "Directory Setup"

foreach ($dir in @($ARCHIE_DIR, "$ARCHIE_DIR\data", "$ARCHIE_DIR\logs", "$ARCHIE_DIR\migrations")) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}
Write-Ok "Created $ARCHIE_DIR\"

# =============================================================================
# STEP 6: Download Stack Files
# =============================================================================

Write-Step "6" "Download Stack"

# Download node_sync.py
$syncScript = "$ARCHIE_DIR\node_sync.py"
try {
    Invoke-WebRequest -Uri "$HubUrl/tools/starbase/api/nodes/node_sync.py" `
        -OutFile $syncScript -UseBasicParsing
    Write-Ok "Downloaded node_sync.py"
} catch {
    Write-Fail "Failed to download node_sync.py: $_"
}

# Download docker-compose if Docker available
if ($dockerComposeAvailable) {
    try {
        Invoke-WebRequest -Uri "$HubUrl/tools/starbase/api/nodes/docker-compose.node.yml" `
            -OutFile "$ARCHIE_DIR\docker-compose.yml" -UseBasicParsing
        Write-Ok "Downloaded docker-compose.yml"
    } catch {
        Write-Warn "Could not download docker-compose.yml"
    }
}

# Download node_api.py
try {
    Invoke-WebRequest -Uri "$HubUrl/tools/starbase/api/nodes/node_api.py" `
        -OutFile "$ARCHIE_DIR\node_api.py" -UseBasicParsing
    Write-Ok "Downloaded node_api.py"
} catch {
    Write-Warn "Could not download node_api.py"
}

# =============================================================================
# STEP 7: Configuration
# =============================================================================

Write-Step "7" "Configuration"

$configPath = "$ARCHIE_DIR\config.json"
$config = @{
    node_id            = $nodeId
    hub_url            = $HubUrl
    hub_api_key        = $apiKey
    ollama_host        = "http://localhost:$OLLAMA_PORT"
    heartbeat_interval = 30
    sync_poll_interval = 60
    archie_version     = $CLIENT_VERSION
    client_version     = $CLIENT_VERSION
    deployment_mode    = "starship"
    node_name          = $NodeName
    mesh_ip            = $meshIP
    headscale_url      = $headscaleUrl
    registered_at      = (Get-Date -Format "o")
}
if ($response.config) {
    $config["server_config"] = $response.config
}

$config | ConvertTo-Json -Depth 5 | Set-Content -Path $configPath -Encoding UTF8
Write-Ok "Config saved to $configPath"

# =============================================================================
# STEP 8: Start Services
# =============================================================================

Write-Step "8" "Start Services"

# Check Python
$pythonCmd = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $check = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($check) { $pythonCmd = $cmd; break }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Warn "Python not found. Install from https://www.python.org/downloads/"
    Write-Info "After installing, run: python `"$syncScript`""
} else {
    # Remove old scheduled tasks
    foreach ($oldName in @($OLD_TASK_NAME, $TASK_NAME)) {
        try {
            $old = Get-ScheduledTask -TaskName $oldName -ErrorAction SilentlyContinue
            if ($old) {
                Unregister-ScheduledTask -TaskName $oldName -Confirm:$false
                Write-Info "Removed old task: $oldName"
            }
        } catch {}
    }

    # Create scheduled task for node_sync.py
    try {
        $action = New-ScheduledTaskAction `
            -Execute $pythonCmd `
            -Argument "`"$syncScript`"" `
            -WorkingDirectory $ARCHIE_DIR

        $trigger = New-ScheduledTaskTrigger -AtStartup

        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -RestartCount 999 `
            -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit (New-TimeSpan -Days 365)

        Register-ScheduledTask `
            -TaskName $TASK_NAME `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -User "SYSTEM" `
            -RunLevel Highest `
            -Description "A.R.C.H.I.E. fleet node — heartbeats, sync, OTA, mesh VPN" | Out-Null

        Start-ScheduledTask -TaskName $TASK_NAME
        Write-Ok "Node sync service started"
    } catch {
        Write-Warn "Scheduled task creation failed: $_"
        Write-Info "Run manually: $pythonCmd `"$syncScript`""
    }
}

# =============================================================================
# STEP 9: Validation & Summary
# =============================================================================

Write-Step "9" "Validation"

Start-Sleep -Seconds 3

$pass = 0
$total = 0

# Ollama
$total++
try {
    $r = Invoke-RestMethod -Uri "http://localhost:$OLLAMA_PORT/api/tags" -TimeoutSec 5
    Write-Ok "Ollama responding on :$OLLAMA_PORT"
    $pass++
} catch {
    Write-Warn "Ollama not responding"
}

# Sync service
$total++
$taskState = (Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue).State
if ($taskState -eq "Running") {
    Write-Ok "Sync service running"
    $pass++
} else {
    Write-Warn "Sync service: $taskState"
}

# Mesh VPN
if ($meshIP) {
    $total++
    try {
        $tsStatus = tailscale status 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Mesh VPN connected ($meshIP)"
            $pass++
        } else {
            Write-Warn "Mesh VPN not connected"
        }
    } catch {
        Write-Warn "Cannot check mesh status"
    }
}

Write-Host ""
Write-Info "Validation: $pass/$total checks passed"

# Summary
Write-Host ""
Write-Host ""
Write-Host "  ============================================" -ForegroundColor Green
Write-Host "   A.R.C.H.I.E. Node Successfully Deployed!" -ForegroundColor Green
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Node ID:      $nodeId" -ForegroundColor White
Write-Host "  Node Name:    $NodeName" -ForegroundColor White
Write-Host "  Install Dir:  $ARCHIE_DIR" -ForegroundColor White
Write-Host "  Hub:          $HubUrl" -ForegroundColor White
Write-Host "  Local IP:     $localIP" -ForegroundColor White
if ($meshIP) {
    Write-Host "  Mesh IP:      $meshIP" -ForegroundColor White
}
Write-Host ""
Write-Host "  Services:" -ForegroundColor White
Write-Host "    Ollama:     http://localhost:$OLLAMA_PORT"
Write-Host "    Sync:       Scheduled Task '$TASK_NAME'"
if ($meshIP) {
    Write-Host "    Mesh VPN:   $meshIP"
}
Write-Host ""
Write-Host "  Commands:" -ForegroundColor Cyan
Write-Host "    Get-ScheduledTask '$TASK_NAME'   # Check status"
Write-Host "    Stop-ScheduledTask '$TASK_NAME'  # Stop sync"
Write-Host "    Start-ScheduledTask '$TASK_NAME' # Start sync"
Write-Host ""
Write-Host "  Node will appear in Starbase Command > Network tab" -ForegroundColor DarkCyan
Write-Host "  for approval once the first heartbeat is received." -ForegroundColor DarkCyan
Write-Host ""
