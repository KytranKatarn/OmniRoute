# =============================================================================
# A.R.C.H.I.E. Node Client - Windows Update Script
# Usage: iwr -useb http://192.168.1.200:3000/tools/starbase/api/nodes/update.ps1 | iex
# =============================================================================

& {
$ErrorActionPreference = "Stop"
$ARCHIE_DIR = "C:\ProgramData\ARCHIE-Node"
$ARCHIE_BASE_URL = "http://192.168.1.200:3000"

function Write-Step {
    param([string]$Text)
    Write-Host "  >> " -ForegroundColor Cyan -NoNewline
    Write-Host $Text
}

function Write-Ok {
    param([string]$Text)
    Write-Host "  [OK] " -ForegroundColor Green -NoNewline
    Write-Host $Text
}

function Write-Fail {
    param([string]$Text)
    Write-Host "  [FAIL] " -ForegroundColor Red -NoNewline
    Write-Host $Text
}

Write-Host ""
Write-Host "  =========================================" -ForegroundColor Cyan
Write-Host "   A.R.C.H.I.E. Node Client Updater"       -ForegroundColor Cyan
Write-Host "  =========================================" -ForegroundColor Cyan
Write-Host ""

# Check admin
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Fail "Run this as Administrator (right-click PowerShell > Run as Admin)"
    return
}

# Check existing install
if (-not (Test-Path "$ARCHIE_DIR\config.json")) {
    Write-Fail "No existing install found at $ARCHIE_DIR\config.json"
    Write-Host "  Run the full installer instead:" -ForegroundColor Yellow
    Write-Host "  iwr -useb $ARCHIE_BASE_URL/tools/starbase/api/nodes/install.ps1 | iex" -ForegroundColor Yellow
    return
}

# Read current version
$currentVer = "unknown"
$heartbeatPath = "$ARCHIE_DIR\heartbeat.ps1"
if (Test-Path $heartbeatPath) {
    $match = Select-String -Path $heartbeatPath -Pattern 'CLIENT_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match) { $currentVer = $match.Matches[0].Groups[1].Value }
}
Write-Step "Current version: v$currentVer"

# Download new heartbeat script
Write-Step "Downloading latest heartbeat.ps1..."
$newPath = "$env:TEMP\heartbeat-update.ps1"
try {
    Invoke-WebRequest -Uri "$ARCHIE_BASE_URL/tools/starbase/api/nodes/heartbeat.ps1" `
        -OutFile $newPath -UseBasicParsing -TimeoutSec 30
} catch {
    Write-Fail "Download failed: $_"
    return
}

# Check new version
$newVer = "unknown"
$match = Select-String -Path $newPath -Pattern 'CLIENT_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
if ($match) { $newVer = $match.Matches[0].Groups[1].Value }

if ($currentVer -eq $newVer) {
    Write-Step "Same version v$currentVer — replacing anyway to ensure latest"
}

# Backup
if (Test-Path $heartbeatPath) {
    Copy-Item $heartbeatPath "$heartbeatPath.bak" -Force
    Write-Ok "Backed up current script to heartbeat.ps1.bak"
}

# Replace
Copy-Item $newPath $heartbeatPath -Force
Remove-Item $newPath -Force -ErrorAction SilentlyContinue
Write-Ok "Installed heartbeat.ps1 v$newVer"

# Kill any running heartbeat processes
Write-Step "Stopping old heartbeat process..."
$killed = 0
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | ForEach-Object {
    if ($_.CommandLine -and $_.CommandLine -match 'heartbeat\.ps1') {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }
}
if ($killed -gt 0) {
    Write-Ok "Stopped $killed heartbeat process(es)"
} else {
    Write-Ok "No running heartbeat process found"
}
Start-Sleep -Seconds 2

# Restart scheduled task
Write-Step "Starting ARCHIE-Node-Heartbeat task..."
try {
    $task = Get-ScheduledTask -TaskName "ARCHIE-Node-Heartbeat" -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName "ARCHIE-Node-Heartbeat" -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Start-ScheduledTask -TaskName "ARCHIE-Node-Heartbeat"
        Write-Ok "Scheduled task started"
    } else {
        Write-Host "  [!] " -ForegroundColor Yellow -NoNewline
        Write-Host "Scheduled task not found — launching heartbeat directly..."
        Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$heartbeatPath`"" -WindowStyle Hidden
        Write-Ok "Heartbeat launched as background process"
    }
} catch {
    Write-Fail "Could not start task: $_"
    Write-Host "      Starting directly instead..." -ForegroundColor Yellow
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$heartbeatPath`"" -WindowStyle Hidden
    Write-Ok "Heartbeat launched as background process"
}

# Verify heartbeat is running
Write-Step "Verifying heartbeat process..."
Start-Sleep -Seconds 5
$running = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -match 'heartbeat\.ps1'
}
if ($running) {
    Write-Ok "Heartbeat running (PID: $($running.ProcessId))"
} else {
    Write-Fail "Heartbeat not detected — launching manually..."
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$heartbeatPath`"" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    $running = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match 'heartbeat\.ps1'
    }
    if ($running) {
        Write-Ok "Heartbeat now running (PID: $($running.ProcessId))"
    } else {
        Write-Fail "Could not start heartbeat. Run manually in a new window:"
        Write-Host '      powershell -ExecutionPolicy Bypass -File "C:\ProgramData\ARCHIE-Node\heartbeat.ps1"' -ForegroundColor Yellow
    }
}

# Quick connectivity test
Write-Step "Testing connection to starbase..."
try {
    $testUrl = "$ARCHIE_BASE_URL/health"
    $resp = Invoke-RestMethod -Uri $testUrl -Method Get -TimeoutSec 10 -ErrorAction Stop
    Write-Ok "Starbase reachable at $ARCHIE_BASE_URL"
} catch {
    Write-Fail "Cannot reach starbase at $ARCHIE_BASE_URL"
    Write-Host "      Check network/firewall. Node needs access to port 3000." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  =========================================" -ForegroundColor Green
Write-Host "   Update complete! v$currentVer -> v$newVer" -ForegroundColor Green
Write-Host "  =========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Diagnostics (if heartbeat still not connecting):" -ForegroundColor DarkGray
Write-Host "    Get-ScheduledTask -TaskName 'ARCHIE-Node-Heartbeat' | Select State" -ForegroundColor DarkGray
Write-Host "    Get-Content 'C:\ProgramData\ARCHIE-Node\heartbeat.log' -Tail 20" -ForegroundColor DarkGray
Write-Host "    powershell -ExecutionPolicy Bypass -File 'C:\ProgramData\ARCHIE-Node\heartbeat.ps1'" -ForegroundColor DarkGray
Write-Host ""
}
