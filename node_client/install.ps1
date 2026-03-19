# =============================================================================
# A.R.C.H.I.E. Unified Node Client — Windows Installer v2.0.0
# Usage: iwr -useb http://YOUR_HUB:3000/tools/starbase/api/nodes/install.ps1 | iex
#   or:  .\install.ps1 -HubUrl https://archie.kytranempowerment.com
# =============================================================================

param(
    [string]$HubUrl = ""
)

$ErrorActionPreference = "Stop"
$ARCHIE_DIR       = "C:\ProgramData\ARCHIE-Node"
$CONFIG_PATH      = "$ARCHIE_DIR\config.json"
$SYNC_SCRIPT      = "$ARCHIE_DIR\node_sync.py"
$CLIENT_VERSION   = "2.0.0"
$OLLAMA_PORT      = 11434
$TASK_NAME        = "ARCHIE-Node-Sync"
$OLD_TASK_NAME    = "ARCHIE-Node-Heartbeat"

# -- Helpers ------------------------------------------------------------------

function Write-Banner {
    Write-Host ""
    Write-Host "  =========================================" -ForegroundColor Cyan
    Write-Host "   A.R.C.H.I.E. Unified Node Installer"    -ForegroundColor Cyan
    Write-Host "   Version $CLIENT_VERSION | Windows"       -ForegroundColor DarkCyan
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
# STEP 1: Require Administrator + Get Hub URL
# =============================================================================

Write-Banner
Write-Step "1/8" "Checking prerequisites..."

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

# Prompt for Hub URL if not provided
if (-not $HubUrl) {
    $HubUrl = Read-Host "  Enter A.R.C.H.I.E. Hub URL (e.g. https://archie.kytranempowerment.com)"
}
if (-not $HubUrl) {
    Write-Fail "Hub URL is required."
    exit 1
}
$HubUrl = $HubUrl.TrimEnd("/")
Write-Ok "Hub URL: $HubUrl"

# Check Python is available
$pythonCmd = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $check = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($check) {
            $ver = & $cmd --version 2>&1
            $pythonCmd = $cmd
            Write-Ok "Python found: $ver"
            break
        }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Fail "Python 3 is required but not found in PATH."
    Write-Host "      Install from https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

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

Write-Step "2/8" "Detecting hardware..."

try {
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $cpuName = $cpu.Name.Trim()
    $cpuCores = $cpu.NumberOfCores
    Write-Ok "CPU: $cpuName ($cpuCores cores)"

    $cs = Get-CimInstance Win32_ComputerSystem
    $ramGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    Write-Ok "RAM: ${ramGB} GB"

    $gpus = Get-CimInstance Win32_VideoController
    $gpuAvailable = $false
    $gpuName = "None"
    $gpuVramGB = 0
    foreach ($gpu in $gpus) {
        if ($gpu.AdapterRAM -and $gpu.AdapterRAM -gt 0) {
            $vram = [math]::Round($gpu.AdapterRAM / 1GB, 1)
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

    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $diskGB = [math]::Round($disk.Size / 1GB, 1)
    Write-Ok "Disk C: ${diskGB} GB total"

    $os = Get-CimInstance Win32_OperatingSystem
    $osInfo = "$($os.Caption) $($os.Version)"
    Write-Ok "OS: $osInfo"
} catch {
    Write-Fail "Hardware detection failed: $_"
    exit 1
}

# =============================================================================
# STEP 3: Detect / Verify Ollama
# =============================================================================

Write-Step "3/8" "Detecting Ollama..."

$ollamaReady = $false
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:$OLLAMA_PORT/api/tags" -Method Get -TimeoutSec 5
    $ollamaReady = $true
    $modelCount = 0
    if ($resp.models) { $modelCount = $resp.models.Count }
    Write-Ok "Ollama responding on localhost:$OLLAMA_PORT ($modelCount models)"
} catch {
    Write-Info "Ollama not detected on localhost:$OLLAMA_PORT"
    Write-Info "Install Ollama from https://ollama.com/download and restart this script."
    Write-Info "Continuing without Ollama verification..."
}

# =============================================================================
# STEP 4: Download node_sync.py from Hub
# =============================================================================

Write-Step "4/8" "Downloading unified node client..."

$syncUrl = "$HubUrl/tools/starbase/api/nodes/node_sync.py"
Write-Info "Downloading from $syncUrl..."
try {
    Invoke-WebRequest -Uri $syncUrl -OutFile $SYNC_SCRIPT -UseBasicParsing
    Write-Ok "Downloaded node_sync.py to $SYNC_SCRIPT"
} catch {
    Write-Fail "Failed to download node_sync.py: $_"
    Write-Host "      Ensure the A.R.C.H.I.E. platform is reachable at $HubUrl" -ForegroundColor Yellow
    exit 1
}

# =============================================================================
# STEP 5: Register with A.R.C.H.I.E. Hub
# =============================================================================

Write-Step "5/8" "Registering node with hub..."

$localIP = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.PrefixOrigin -ne "WellKnown" } |
    Sort-Object -Property InterfaceIndex |
    Select-Object -First 1).IPAddress
if (-not $localIP) { $localIP = "127.0.0.1" }

$nodeName = $env:COMPUTERNAME
$registerUrl = "$HubUrl/tools/starbase/api/nodes/register"

$payload = @{
    node_name        = $nodeName
    vpn_ip           = $localIP
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
    client_version   = $CLIENT_VERSION
    tags             = @("windows")
} | ConvertTo-Json -Depth 3

Write-Info "Registering $nodeName ($localIP)..."

try {
    $response = Invoke-RestMethod -Uri $registerUrl -Method Post `
        -ContentType "application/json" -Body $payload -TimeoutSec 15

    $nodeId  = $response.node_id
    $apiKey  = $response.api_key

    if (-not $nodeId -or -not $apiKey) {
        Write-Fail "Registration response missing node_id or api_key"
        exit 1
    }

    Write-Ok "Registered as node $nodeId"
} catch {
    Write-Fail "Registration failed: $_"
    Write-Host "      Ensure the A.R.C.H.I.E. platform is reachable at $HubUrl" -ForegroundColor Yellow
    exit 1
}

# =============================================================================
# STEP 6: Write config.json
# =============================================================================

Write-Step "6/8" "Writing configuration..."

$config = @{
    node_id            = $nodeId
    hub_url            = $HubUrl
    hub_api_key        = $apiKey
    ollama_host        = "http://localhost:$OLLAMA_PORT"
    heartbeat_interval = 30
    sync_poll_interval = 60
    archie_version     = $CLIENT_VERSION
    client_version     = $CLIENT_VERSION
    node_name          = $nodeName
    registered_at      = (Get-Date -Format "o")
}
if ($response.config) {
    $config["server_config"] = $response.config
}

$config | ConvertTo-Json -Depth 5 | Set-Content -Path $CONFIG_PATH -Encoding UTF8
Write-Ok "Config saved to $CONFIG_PATH"

# =============================================================================
# STEP 7: Create Scheduled Task (replaces old heartbeat task)
# =============================================================================

Write-Step "7/8" "Installing node sync service..."

# Remove old heartbeat task if it exists
try {
    $oldTask = Get-ScheduledTask -TaskName $OLD_TASK_NAME -ErrorAction SilentlyContinue
    if ($oldTask) {
        Unregister-ScheduledTask -TaskName $OLD_TASK_NAME -Confirm:$false
        Write-Ok "Removed old $OLD_TASK_NAME scheduled task"
    }
} catch {}

# Remove existing sync task if present
try {
    $existingTask = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
    if ($existingTask) {
        Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
        Write-Info "Removed previous $TASK_NAME task"
    }
} catch {}

try {
    # node_sync.py is a long-running process — run it directly
    $action = New-ScheduledTaskAction `
        -Execute $pythonCmd `
        -Argument "`"$SYNC_SCRIPT`"" `
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
        -Description "A.R.C.H.I.E. unified node client — heartbeats, sync, and OTA updates" | Out-Null

    # Start the task immediately
    Start-ScheduledTask -TaskName $TASK_NAME
    Write-Ok "Scheduled task '$TASK_NAME' registered and started"
} catch {
    Write-Fail "Failed to create scheduled task: $_"
    Write-Info "You can manually run: $pythonCmd `"$SYNC_SCRIPT`""
}

# =============================================================================
# STEP 8: Verify and Summary
# =============================================================================

Write-Step "8/8" "Verifying..."

Start-Sleep -Seconds 3

$taskStatus = (Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue).State
if ($taskStatus -eq "Running") {
    Write-Ok "Node sync service is running"
} else {
    Write-Info "Task state: $taskStatus (may take a moment to start)"
}

Write-Host ""
Write-Host ""
Write-Host "  =========================================" -ForegroundColor Green
Write-Host "   A.R.C.H.I.E. Node Setup Complete!"      -ForegroundColor Green
Write-Host "  =========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Node ID:      $nodeId"                     -ForegroundColor White
Write-Host "  Node Name:    $nodeName"                    -ForegroundColor White
Write-Host "  Local IP:     $localIP"                     -ForegroundColor White
Write-Host "  Hub URL:      $HubUrl"                      -ForegroundColor White
Write-Host "  Ollama:       http://localhost:$OLLAMA_PORT" -ForegroundColor White
Write-Host "  Config:       $CONFIG_PATH"                 -ForegroundColor White
Write-Host "  Client:       $SYNC_SCRIPT"                 -ForegroundColor White
Write-Host "  Service:      Scheduled Task '$TASK_NAME'"  -ForegroundColor White
Write-Host ""
Write-Host "  The node is now sending heartbeats and polling" -ForegroundColor Gray
Write-Host "  for sync commands. An admin must approve this"  -ForegroundColor Gray
Write-Host "  node on the A.R.C.H.I.E. dashboard."           -ForegroundColor Gray
Write-Host ""
Write-Host "  Management commands:" -ForegroundColor Cyan
Write-Host "    Get-ScheduledTask -TaskName '$TASK_NAME'"      -ForegroundColor White
Write-Host "    Stop-ScheduledTask -TaskName '$TASK_NAME'"     -ForegroundColor White
Write-Host "    Start-ScheduledTask -TaskName '$TASK_NAME'"    -ForegroundColor White
Write-Host ""
