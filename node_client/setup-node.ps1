#Requires -RunAsAdministrator
<#
.SYNOPSIS
    A.R.C.H.I.E. Fleet — Windows Node Setup (Full Installer)
    Sets up everything from bare Windows to running fleet node.

.DESCRIPTION
    Phase 1 (pre-reboot): WSL2, Docker Desktop, firewall rules
    Phase 2 (post-reboot): NVIDIA Container Toolkit, bootstrap, start node

.USAGE
    Run as Administrator in PowerShell:
      irm http://192.168.1.200:3000/tools/starbase/api/nodes/setup-node.ps1 | iex
    Or:
      .\setup-node.ps1
#>

param(
    [string]$HubUrl = "http://192.168.1.200:3000",
    [switch]$Phase2,
    [switch]$SkipReboot
)

$ErrorActionPreference = "Stop"
$ScriptPath = $MyInvocation.MyCommand.Source
$SetupDir = "$env:ProgramData\ARCHIE-Node-Setup"
$Phase2Flag = "$SetupDir\.phase2"

# ── Helpers ─────────────────────────────────────────────────────────
function Write-Step($msg)  { Write-Host "`n  [*] $msg" -ForegroundColor Cyan }
function Write-OK($msg)    { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "  [FAIL] $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   A.R.C.H.I.E. Fleet — Windows Node Full Setup         ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Create setup directory
if (-not (Test-Path $SetupDir)) { New-Item -ItemType Directory -Path $SetupDir -Force | Out-Null }

# ── Detect Phase ────────────────────────────────────────────────────
if ($Phase2 -or (Test-Path $Phase2Flag)) {
    # Phase 2: post-reboot
    if (Test-Path $Phase2Flag) { Remove-Item $Phase2Flag -Force }
    goto_phase2
}

# ════════════════════════════════════════════════════════════════════
# PHASE 1: Pre-Reboot Setup
# ════════════════════════════════════════════════════════════════════

Write-Host "  Phase 1: System Prerequisites" -ForegroundColor Magenta
Write-Host "  ─────────────────────────────" -ForegroundColor DarkGray

# ── Step 1: Check NVIDIA Driver ────────────────────────────────────
Write-Step "Checking NVIDIA driver..."
try {
    $nvSmi = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null
    if ($nvSmi) {
        Write-OK "GPU detected: $($nvSmi.Trim())"
    } else {
        Write-Fail "nvidia-smi found but no GPU detected. Install NVIDIA drivers first."
    }
} catch {
    Write-Fail "nvidia-smi not found. Install NVIDIA drivers first: https://www.nvidia.com/drivers"
}

# ── Step 2: Enable WSL2 ───────────────────────────────────────────
Write-Step "Checking WSL2..."
$wslStatus = wsl --status 2>$null
if ($LASTEXITCODE -ne 0 -or -not $wslStatus) {
    Write-Step "Installing WSL2 + Ubuntu (this may take a few minutes)..."
    wsl --install -d Ubuntu-22.04 --no-launch
    if ($LASTEXITCODE -ne 0) {
        # Fallback: enable features manually
        Write-Step "Enabling Windows features manually..."
        dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
        dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
        Write-Warn "WSL2 features enabled. Reboot required."
    }
    $NeedReboot = $true
    Write-OK "WSL2 installation initiated"
} else {
    Write-OK "WSL2 already installed"
    # Check if Ubuntu is installed
    $distros = wsl --list --quiet 2>$null
    if ($distros -notmatch "Ubuntu") {
        Write-Step "Installing Ubuntu 22.04..."
        wsl --install -d Ubuntu-22.04 --no-launch
        $NeedReboot = $true
    } else {
        Write-OK "Ubuntu already installed"
    }
}

# Set WSL2 as default
wsl --set-default-version 2 2>$null

# ── Step 3: Install Docker Desktop ────────────────────────────────
Write-Step "Checking Docker Desktop..."
$dockerPath = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
if (-not (Test-Path $dockerPath)) {
    Write-Step "Downloading Docker Desktop..."
    $dockerInstaller = "$SetupDir\DockerDesktopInstaller.exe"
    if (-not (Test-Path $dockerInstaller)) {
        Invoke-WebRequest -Uri "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe" `
            -OutFile $dockerInstaller -UseBasicParsing
    }
    Write-Step "Installing Docker Desktop (silent, WSL2 backend)..."
    Start-Process -FilePath $dockerInstaller -ArgumentList "install", "--quiet", "--accept-license" -Wait
    $NeedReboot = $true
    Write-OK "Docker Desktop installed"
} else {
    Write-OK "Docker Desktop already installed"
}

# ── Step 4: Windows Firewall Rules ────────────────────────────────
Write-Step "Configuring firewall rules..."
$rules = @(
    @{ Name = "ARCHIE-Ollama";   Port = 11434 },
    @{ Name = "ARCHIE-KSO";     Port = 8085 },
    @{ Name = "ARCHIE-NodeAPI";  Port = 3001 },
    @{ Name = "ARCHIE-ComfyUI";  Port = 8188 }
)
foreach ($rule in $rules) {
    $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound `
            -Port $rule.Port -Protocol TCP -Action Allow | Out-Null
        Write-OK "Firewall rule: $($rule.Name) (port $($rule.Port))"
    } else {
        Write-OK "Firewall rule exists: $($rule.Name)"
    }
}

# ── Step 5: Install Tailscale ─────────────────────────────────────
Write-Step "Checking Tailscale..."
$tsPath = "${env:ProgramFiles}\Tailscale\tailscale.exe"
if (-not (Test-Path $tsPath)) {
    Write-Step "Downloading Tailscale..."
    $tsInstaller = "$SetupDir\TailscaleInstaller.exe"
    if (-not (Test-Path $tsInstaller)) {
        Invoke-WebRequest -Uri "https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe" `
            -OutFile $tsInstaller -UseBasicParsing
    }
    Write-Step "Installing Tailscale (silent)..."
    Start-Process -FilePath $tsInstaller -ArgumentList "/quiet" -Wait
    Write-OK "Tailscale installed"
} else {
    Write-OK "Tailscale already installed"
}

# ── Reboot Gate ───────────────────────────────────────────────────
if ($NeedReboot -and -not $SkipReboot) {
    Write-Host ""
    Write-Host "  ════════════════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host "  Phase 1 complete. REBOOT REQUIRED." -ForegroundColor Yellow
    Write-Host "  ════════════════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  After reboot:" -ForegroundColor White
    Write-Host "    1. Open Docker Desktop and let it finish starting" -ForegroundColor White
    Write-Host "    2. Open Ubuntu from Start Menu, create a user when prompted" -ForegroundColor White
    Write-Host "    3. Run this script again with -Phase2:" -ForegroundColor White
    Write-Host ""
    Write-Host "       .\setup-node.ps1 -Phase2" -ForegroundColor Cyan
    Write-Host ""

    # Save script for Phase 2
    if ($ScriptPath) {
        Copy-Item $ScriptPath "$SetupDir\setup-node.ps1" -Force
    }
    # Create phase 2 flag
    New-Item -ItemType File -Path $Phase2Flag -Force | Out-Null

    $reboot = Read-Host "  Reboot now? (Y/n)"
    if ($reboot -ne "n") {
        Restart-Computer -Force
    }
    exit 0
}

if (-not $NeedReboot) {
    Write-Host "`n  No reboot needed — proceeding to Phase 2..." -ForegroundColor Green
    # Fall through to Phase 2
}

# ════════════════════════════════════════════════════════════════════
# PHASE 2: Post-Reboot — GPU Toolkit + Node Bootstrap
# ════════════════════════════════════════════════════════════════════

function goto_phase2 {
    Write-Host ""
    Write-Host "  Phase 2: GPU Setup + Node Deployment" -ForegroundColor Magenta
    Write-Host "  ─────────────────────────────────────" -ForegroundColor DarkGray

    # ── Step 6: Verify Docker Desktop Running ─────────────────────
    Write-Step "Checking Docker Desktop..."
    $dockerRunning = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            docker info 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $dockerRunning = $true; break }
        } catch {}
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
    }
    if ($dockerRunning) {
        Write-OK "Docker Desktop is running"
    } else {
        Write-Fail "Docker Desktop not responding. Start it manually and re-run with -Phase2"
    }

    # ── Step 7: Install NVIDIA Container Toolkit in WSL2 ──────────
    Write-Step "Installing NVIDIA Container Toolkit in WSL2..."
    $nctInstall = @"
set -e
if dpkg -l | grep -q nvidia-container-toolkit 2>/dev/null; then
    echo "ALREADY_INSTALLED"
    exit 0
fi
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
sudo apt-get update -qq && sudo apt-get install -y -qq nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
echo "INSTALLED"
"@
    $result = wsl -d Ubuntu-22.04 -- bash -c $nctInstall 2>&1 | Select-Object -Last 1
    if ($result -match "INSTALLED|ALREADY_INSTALLED") {
        Write-OK "NVIDIA Container Toolkit ready"
    } else {
        Write-Warn "NVIDIA Container Toolkit install may have issues — continuing anyway"
    }

    # Restart Docker to pick up nvidia runtime
    Write-Step "Restarting Docker Desktop to load nvidia runtime..."
    Stop-Process -Name "Docker Desktop" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Start-Process "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    Write-Step "Waiting for Docker to start..."
    for ($i = 0; $i -lt 60; $i++) {
        try {
            docker info 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { break }
        } catch {}
        Start-Sleep -Seconds 2
    }
    Write-OK "Docker restarted"

    # ── Step 8: Test GPU in Docker ────────────────────────────────
    Write-Step "Testing GPU passthrough in Docker..."
    $gpuTest = docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "GPU accessible in Docker containers"
    } else {
        Write-Warn "GPU test failed — Ollama will run in CPU mode"
    }

    # ── Step 9: Run WSL2 Bootstrap ────────────────────────────────
    Write-Step "Running fleet bootstrap in WSL2..."
    Write-Host ""
    Write-Host "  Handing off to WSL2 bootstrap script..." -ForegroundColor Cyan
    Write-Host "  You'll be prompted for node name and registration token." -ForegroundColor White
    Write-Host ""

    # Download and run the bootstrap inside WSL2
    wsl -d Ubuntu-22.04 -- bash -c "curl -fsSL ${HubUrl}/tools/starbase/api/nodes/bootstrap-wsl2.sh | bash"

    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
        Write-Host "  ║   Node setup complete!                                  ║" -ForegroundColor Green
        Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Green
        Write-Host ""
        Write-Host "  To manage the node, open WSL2 and run:" -ForegroundColor White
        Write-Host "    cd ~/archie-node && docker compose ps" -ForegroundColor Cyan
        Write-Host ""
    } else {
        Write-Warn "Bootstrap exited with errors. Check output above."
    }
}

# If we didn't reboot, run Phase 2 now
if (-not $NeedReboot) {
    goto_phase2
}
