# =============================================================================
# A.R.C.H.I.E. Node Client - Windows Heartbeat Service
# Version: 1.0.0
# Sends periodic heartbeats with system metrics to the ARCHIE platform
# =============================================================================

$CLIENT_VERSION = "1.0.0"
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
# Send Heartbeat
# -----------------------------------------------------------------------------
function Send-Heartbeat {
    param($Config, $Metrics)

    $url = "$($Config.server_url)/tools/bridge/api/nodes/$($Config.node_id)/heartbeat"
    $headers = @{
        "X-Node-API-Key" = $Config.api_key
        "Content-Type"   = "application/json"
    }
    $body = $Metrics | ConvertTo-Json -Depth 5

    try {
        $response = Invoke-RestMethod -Uri $url -Method Post -Headers $headers -Body $body -TimeoutSec 15 -ErrorAction Stop
        return $true
    } catch {
        Write-Log "ERROR" "Heartbeat POST failed: $_"
        return $false
    }
}

# =============================================================================
# Main Loop
# =============================================================================
Write-Log "INFO" "A.R.C.H.I.E. Node Client v$CLIENT_VERSION starting..."
$config = Get-Config
$heartbeatInterval = if ($config.heartbeat_interval) { $config.heartbeat_interval } else { 30 }
$ollamaPort = if ($config.ollama_port) { $config.ollama_port } else { 11434 }
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
            gpu_usage      = if ($null -ne $gpuUsage) { $gpuUsage } else { 0 }
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
            $gpuStr = if ($null -ne $gpuUsage) { "${gpuUsage}%" } else { "N/A" }
            Write-Log "INFO" "Heartbeat sent - CPU: ${cpuUsage}% | RAM: ${memUsage}% | GPU: $gpuStr | Ollama: $($ollama.online) ($modelCount models)"
        } else {
            Write-Log "WARN" "Heartbeat failed - will retry in ${heartbeatInterval}s"
        }
    } catch {
        Write-Log "ERROR" "Unexpected error in heartbeat loop: $_"
    }

    Start-Sleep -Seconds $heartbeatInterval
}
