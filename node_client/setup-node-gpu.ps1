###############################################################################
# A.R.C.H.I.E. Starship Node — GPU Pre-Setup (Windows)
# ============================================================================
# Run this ONCE before deploy-node.ps1 on GPU nodes (RTX 3070 / RTX 3080 etc.)
# Configures WSL2 memory limits and verifies NVIDIA Docker support.
#
# Usage (PowerShell as Administrator):
#   .\setup-node-gpu.ps1
#
# Then run:
#   .\deploy-node.ps1 -Fresh -NodeId node_xxx -HubApiKey your-key
###############################################################################

$ErrorActionPreference = 'Continue'

Write-Host ''
Write-Host '==========================================' -ForegroundColor Cyan
Write-Host '  A.R.C.H.I.E. GPU Node Pre-Setup' -ForegroundColor Cyan
Write-Host '==========================================' -ForegroundColor Cyan
Write-Host ''

# =====================================================================
# Step 1: Configure WSL2 memory limits
# =====================================================================
$wslConfig = "$env:USERPROFILE\.wslconfig"
$totalRamGB = [math]::Round((Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum / 1GB)
$wsLRamGB = [math]::Max(8, $totalRamGB - 4)
$cpuCount = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum

Write-Host "System RAM: ${totalRamGB}GB | Allocating ${wsLRamGB}GB to WSL2" -ForegroundColor Cyan
Write-Host "CPU cores: $cpuCount" -ForegroundColor Cyan

$wslContent = "[wsl2]`nmemory=${wsLRamGB}GB`nprocessors=$cpuCount`nswap=0`nlocalhostForwarding=true`n"
Set-Content $wslConfig $wslContent -Encoding UTF8
Write-Host '[OK] .wslconfig written' -ForegroundColor Green

# =====================================================================
# Step 2: Restart WSL2 to apply memory settings
# =====================================================================
Write-Host ''
Write-Host 'Restarting WSL2...' -ForegroundColor Cyan
wsl --shutdown 2>&1 | Out-Null
Start-Sleep -Seconds 3
Write-Host '[OK] WSL2 restarted' -ForegroundColor Green

# =====================================================================
# Step 3: Verify Docker Desktop is running
# =====================================================================
Write-Host ''
Write-Host 'Checking Docker...' -ForegroundColor Cyan
$dockerRunning = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    $dockerExe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) {
        Start-Process $dockerExe
        Write-Host '  Waiting for Docker to start (up to 60s)...' -ForegroundColor Yellow
        $waited = 0
        while ($waited -lt 60) {
            Start-Sleep -Seconds 5
            $waited += 5
            $null = docker info 2>&1
            if ($LASTEXITCODE -eq 0) { break }
        }
    }
}
$null = docker info 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host '[OK] Docker is running' -ForegroundColor Green
} else {
    Write-Host '[WARN] Docker not running — start Docker Desktop and re-run' -ForegroundColor Yellow
}

# =====================================================================
# Step 4: Verify NVIDIA GPU access
# =====================================================================
Write-Host ''
Write-Host 'Checking NVIDIA GPU...' -ForegroundColor Cyan
$gpuCheck = nvidia-smi 2>&1
if ($LASTEXITCODE -eq 0) {
    $gpuName = (nvidia-smi --query-gpu=name --format=csv,noheader 2>$null).Trim()
    $gpuVram = (nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null).Trim()
    Write-Host "[OK] GPU detected: $gpuName (${gpuVram}MB VRAM)" -ForegroundColor Green

    # Test Docker GPU passthrough
    Write-Host '  Testing Docker GPU passthrough...' -ForegroundColor Cyan
    $gpuDocker = docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host '[OK] Docker GPU passthrough working' -ForegroundColor Green
    } else {
        Write-Host '[WARN] Docker GPU passthrough not working — check NVIDIA Container Toolkit' -ForegroundColor Yellow
        Write-Host '  In Docker Desktop: Settings → Docker Engine → add "default-runtime": "nvidia"' -ForegroundColor Gray
    }
} else {
    Write-Host '[WARN] No NVIDIA GPU detected — node will run CPU-only' -ForegroundColor Yellow
}

# =====================================================================
# Summary
# =====================================================================
Write-Host ''
Write-Host '==========================================' -ForegroundColor Green
Write-Host '  Pre-setup complete!' -ForegroundColor Green
Write-Host '==========================================' -ForegroundColor Green
Write-Host ''
Write-Host '  WSL2 memory:' $wsLRamGB'GB allocated' -ForegroundColor White
Write-Host '  Next step: run deploy-node.ps1 -Fresh ...' -ForegroundColor White
Write-Host ''
