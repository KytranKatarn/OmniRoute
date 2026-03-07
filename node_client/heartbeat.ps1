# =============================================================================
# A.R.C.H.I.E. Node Client - Windows Heartbeat Service
# Version: 1.0.0
# Sends periodic heartbeats with system metrics to the ARCHIE platform
# =============================================================================

$CLIENT_VERSION = "1.1.2"
$CONFIG_PATH = "C:\ProgramData\ARCHIE-Node\config.json"
$LOG_PATH = "C:\ProgramData\ARCHIE-Node\heartbeat.log"
$MAX_LOG_LINES = 1000

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
function Write-Log {
    param([string]$Level, [string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $entry = "[$timestamp] [$Level] $Message"
    Write-Host $entry

    # Ensure log directory exists
    $logDir = Split-Path -Parent $LOG_PATH
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    # Append to log file
    Add-Content -Path $LOG_PATH -Value $entry -ErrorAction SilentlyContinue

    # Trim log to last MAX_LOG_LINES
    try {
        if (Test-Path $LOG_PATH) {
            $lines = Get-Content $LOG_PATH -ErrorAction SilentlyContinue
            if ($lines.Count -gt $MAX_LOG_LINES) {
                $lines | Select-Object -Last $MAX_LOG_LINES | Set-Content $LOG_PATH -ErrorAction SilentlyContinue
            }
        }
    } catch {
        # Ignore log trimming errors
    }
}

# -----------------------------------------------------------------------------
# Load Configuration
# -----------------------------------------------------------------------------
function Get-Config {
    if (-not (Test-Path $CONFIG_PATH)) {
        Write-Log "ERROR" "Config file not found at $CONFIG_PATH"
        Write-Log "ERROR" "Copy config.example.json to $CONFIG_PATH and fill in your values."
        exit 1
    }
    try {
        $config = Get-Content $CONFIG_PATH -Raw | ConvertFrom-Json
        if (-not $config.node_id -or -not $config.api_key -or -not $config.server_url) {
            Write-Log "ERROR" "Config missing required fields: node_id, api_key, server_url"
            exit 1
        }
        return $config
    } catch {
        Write-Log "ERROR" "Failed to parse config: $_"
        exit 1
    }
}

# -----------------------------------------------------------------------------
# Collect CPU Usage
# -----------------------------------------------------------------------------
function Get-CpuUsage {
    try {
        $cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
        if ($null -eq $cpu) { return 0 }
        return [math]::Round($cpu, 1)
    } catch {
        Write-Log "WARN" "Failed to get CPU usage: $_"
        return 0
    }
}

# -----------------------------------------------------------------------------
# Collect Memory Usage
# -----------------------------------------------------------------------------
function Get-MemoryUsage {
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $totalMem = $os.TotalVisibleMemorySize
        $freeMem = $os.FreePhysicalMemory
        if ($totalMem -gt 0) {
            $usedPercent = (($totalMem - $freeMem) / $totalMem) * 100
            return [math]::Round($usedPercent, 1)
        }
        return 0
    } catch {
        Write-Log "WARN" "Failed to get memory usage: $_"
        return 0
    }
}

# -----------------------------------------------------------------------------
# Collect GPU Usage (NVIDIA only)
# -----------------------------------------------------------------------------
function Get-GpuUsage {
    try {
        $nvidiaSmi = Get-Command "nvidia-smi" -ErrorAction SilentlyContinue
        if (-not $nvidiaSmi) {
            # Try the default install path
            $defaultPath = "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
            if (-not (Test-Path $defaultPath)) { return $null }
            $nvidiaSmi = $defaultPath
        } else {
            $nvidiaSmi = $nvidiaSmi.Source
        }
        $output = & $nvidiaSmi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) {
            $gpuVal = ($output.Trim() -split "`n")[0].Trim()
            return [math]::Round([double]$gpuVal, 1)
        }
        return $null
    } catch {
        return $null
    }
}

# -----------------------------------------------------------------------------
# Check Ollama Status and Models
# -----------------------------------------------------------------------------
function Get-OllamaStatus {
    param([int]$OllamaPort = 11434)
    $result = @{ online = $false; models = @() }
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:${OllamaPort}/api/tags" -Method Get -TimeoutSec 5 -ErrorAction Stop
        $result.online = $true
        if ($response.models) {
            foreach ($model in $response.models) {
                $modelInfo = @{ name = $model.name }
                if ($model.size) {
                    $modelInfo.size = $model.size
                }
                $result.models += $modelInfo
            }
        }
    } catch {
        # Ollama not running or unreachable
        $result.online = $false
    }
    return $result
}

# -----------------------------------------------------------------------------
# Get System Uptime
# -----------------------------------------------------------------------------
function Get-SystemUptime {
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $uptime = (Get-Date) - $os.LastBootUpTime
        return [math]::Round($uptime.TotalSeconds)
    } catch {
        return 0
    }
}

# -----------------------------------------------------------------------------
# Send Heartbeat (captures response for update signals)
# -----------------------------------------------------------------------------
$script:LastHeartbeatResponse = $null
function Send-Heartbeat {
    param($Config, $Metrics)

    $url = "$($Config.server_url)/tools/bridge/api/nodes/$($Config.node_id)/heartbeat"
    $headers = @{
        "X-Node-API-Key" = $Config.api_key
        "Content-Type"   = "application/json"
    }
    $body = $Metrics | ConvertTo-Json -Depth 5

    try {
        $script:LastHeartbeatResponse = Invoke-RestMethod -Uri $url -Method Post -Headers $headers -Body $body -TimeoutSec 15 -ErrorAction Stop
        return $true
    } catch {
        Write-Log "ERROR" "Heartbeat POST failed: $_"
        $script:LastHeartbeatResponse = $null
        return $false
    }
}

# -----------------------------------------------------------------------------
# Self-Update: download new heartbeat script, replace, restart
# -----------------------------------------------------------------------------
function Invoke-SelfUpdate {
    param($Config, $UpdateUrl)

    $fullUrl = "$($Config.server_url)$UpdateUrl"
    $installDir = "C:\ProgramData\ARCHIE-Node"
    $updateDir = "$env:TEMP\archie-node-update"
    $selfPath = $MyInvocation.ScriptName
    if (-not $selfPath) { $selfPath = "$installDir\heartbeat.ps1" }

    Write-Log "INFO" "=== SELF-UPDATE STARTING ==="
    Write-Log "INFO" "Downloading from: $fullUrl"

    # Clean up any previous update attempt
    if (Test-Path $updateDir) { Remove-Item $updateDir -Recurse -Force }
    New-Item -ItemType Directory -Path $updateDir -Force | Out-Null

    try {
        # Download the heartbeat script directly
        $scriptUrl = "$($Config.server_url)/tools/bridge/api/nodes/heartbeat.ps1"
        $newScript = "$updateDir\heartbeat.ps1"
        Invoke-WebRequest -Uri $scriptUrl -OutFile $newScript -TimeoutSec 60 -ErrorAction Stop

        # Verify it looks like a valid PowerShell script
        $content = Get-Content $newScript -Raw -ErrorAction Stop
        if ($content -notmatch 'CLIENT_VERSION') {
            Write-Log "ERROR" "Downloaded file doesn't look like a valid heartbeat script"
            return $false
        }

        # Backup current script
        if (Test-Path $selfPath) {
            Copy-Item $selfPath "$selfPath.bak" -Force
            Write-Log "INFO" "Backed up current script to $selfPath.bak"
        }

        # Replace with new version
        Copy-Item $newScript $selfPath -Force
        Write-Log "INFO" "Updated heartbeat script"

        # Clean up
        Remove-Item $updateDir -Recurse -Force -ErrorAction SilentlyContinue

        Write-Log "INFO" "=== SELF-UPDATE COMPLETE - RESTARTING ==="

        # Restart: launch new script then exit current
        Start-Process powershell.exe -ArgumentList "-ExecutionPolicy Bypass -File `"$selfPath`"" -WindowStyle Hidden
        exit 0

    } catch {
        Write-Log "ERROR" "Self-update failed: $_"
        Remove-Item $updateDir -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }
}

# =============================================================================
# Main Loop
# =============================================================================
Write-Log "INFO" "A.R.C.H.I.E. Node Client v$CLIENT_VERSION starting..."
$config = Get-Config
$heartbeatInterval = $(if ($config.heartbeat_interval) { $config.heartbeat_interval } else { 30 })
$ollamaPort = $(if ($config.ollama_port) { $config.ollama_port } else { 11434 })
Write-Log "INFO" "Node ID: $($config.node_id)"
Write-Log "INFO" "Server:  $($config.server_url)"
Write-Log "INFO" "Interval: ${heartbeatInterval}s"

while ($true) {
    try {
        # Collect metrics
        $cpuUsage = Get-CpuUsage
        $memUsage = Get-MemoryUsage
        $gpuUsage = Get-GpuUsage
        $ollama = Get-OllamaStatus -OllamaPort $ollamaPort
        $uptime = Get-SystemUptime
        $hostname = $env:COMPUTERNAME

        # Build payload
        $payload = @{
            status         = "online"
            current_load   = $cpuUsage
            cpu_usage      = $cpuUsage
            memory_usage   = $memUsage
            gpu_usage      = $(if ($null -ne $gpuUsage) { $gpuUsage } else { 0 })
            ollama_online  = $ollama.online
            ollama_models  = $ollama.models
            client_version = $CLIENT_VERSION
            details        = @{
                uptime   = $uptime
                hostname = $hostname
            }
        }

        # Send heartbeat
        $success = Send-Heartbeat -Config $config -Metrics $payload
        if ($success) {
            $modelCount = $ollama.models.Count
            if ($null -ne $gpuUsage) { $gpuStr = "${gpuUsage}%" } else { $gpuStr = "N/A" }
            Write-Log "INFO" "Heartbeat sent - CPU: ${cpuUsage}% | RAM: ${memUsage}% | GPU: ${gpuStr} | Ollama: $($ollama.online) ${modelCount} models"

            # Check if server is requesting a self-update
            if ($script:LastHeartbeatResponse -and $script:LastHeartbeatResponse.update_available -eq $true) {
                $updateUrl = $script:LastHeartbeatResponse.update_url
                $latestVer = $script:LastHeartbeatResponse.latest_version
                Write-Log "INFO" "Server requested update to v$latestVer"
                if ($updateUrl) {
                    $updated = Invoke-SelfUpdate -Config $config -UpdateUrl $updateUrl
                    if (-not $updated) {
                        Write-Log "WARN" "Self-update failed, continuing with current version"
                    }
                }
            }
        } else {
            Write-Log "WARN" "Heartbeat failed - will retry in ${heartbeatInterval}s"
        }
    } catch {
        Write-Log "ERROR" "Unexpected error in heartbeat loop: $_"
    }

    Start-Sleep -Seconds $heartbeatInterval
}
