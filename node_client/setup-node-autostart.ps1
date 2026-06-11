<#
.SYNOPSIS
  A.R.C.H.I.E. Starship self-heal after an unattended Windows reboot (task #3956).

.DESCRIPTION
  The node's container stack already self-heals IF the Docker engine is running:
    * the ARCHIE-Node-Sync scheduled task runs node_sync.py at startup as SYSTEM (no login needed), and
    * every node container is `restart: unless-stopped` (docker-compose.node.yml).
  The ONLY missing link after a Patch-Tuesday reboot is starting the Docker ENGINE — Docker
  Desktop is a per-user GUI app, so with no one signed in there is no engine for the SYSTEM task
  to talk to and the node stays offline.

  This one-time, run-once-per-Starship script closes that gap (Option A):
    1. Docker Desktop "start when I sign in"  (HKCU Run entry — the same mechanism the toggle uses).
    2. Windows auto-login via Sysinternals Autologon (password stored as an LSA secret, NOT plaintext).
    3. Verifies every archie_node_* container is restart=unless-stopped.

  Reboot chain afterwards: power on -> Windows auto-login -> Docker Desktop launches -> engine up
  -> `unless-stopped` containers restart -> ARCHIE-Node-Sync reconnects. No human at the keyboard.

.NOTES
  Run AS ADMINISTRATOR, signed in as the account that should auto-login (usually the node user).
  The password is typed locally and never leaves the machine. Security tradeoff: the box
  auto-unlocks on boot — acceptable for a dedicated LAN GPU node. Re-run any time; it is idempotent.

.PARAMETER User
  Account to auto-login. Default: the current user.

.PARAMETER SkipAutologon
  Configure only Docker Desktop start-on-login + the container check (no auto-login change).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\setup-node-autostart.ps1
#>
[CmdletBinding()]
param(
    [string]$User = $env:USERNAME,
    [switch]$SkipAutologon
)

$ErrorActionPreference = "Stop"
function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Info($m) { Write-Host "  [..]   $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red; exit 1 }

Write-Host "`n=== A.R.C.H.I.E. Starship reboot self-heal (#3956) ===`n" -ForegroundColor Cyan

# ---- 0. Preconditions ----------------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) { Fail "Must run AS ADMINISTRATOR (auto-login + LSA secret need it)." }

$dockerExe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
if (-not (Test-Path $dockerExe)) { Fail "Docker Desktop not found at '$dockerExe' — install the node first (setup-node.ps1)." }
Ok "Running as admin; Docker Desktop present."

# ---- 1. Docker Desktop: start when this user signs in --------------------------------------
# Docker Desktop's own "Start when you log in" toggle writes exactly this Run entry.
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Set-ItemProperty -Path $runKey -Name "Docker Desktop" -Value "`"$dockerExe`""
Ok "Docker Desktop set to launch at sign-in (HKCU\...\Run)."

# Best-effort: flip the settings flag too if the settings file exists (cosmetic; Run key is primary).
foreach ($cfg in @("$env:APPDATA\Docker\settings-store.json", "$env:APPDATA\Docker\settings.json")) {
    if (Test-Path $cfg) {
        try {
            $j = Get-Content $cfg -Raw | ConvertFrom-Json
            $j.PSObject.Properties.Name -contains "AutoStart" | Out-Null
            $j | Add-Member -NotePropertyName "AutoStart" -NotePropertyValue $true -Force
            ($j | ConvertTo-Json -Depth 30) | Set-Content $cfg -Encoding UTF8
            Ok "Set AutoStart=true in $(Split-Path $cfg -Leaf)."
        } catch { Warn "Could not update $(Split-Path $cfg -Leaf) (non-fatal): $_" }
        break
    }
}

# ---- 2. Windows auto-login (Sysinternals Autologon — LSA-encrypted, not plaintext) ---------
if ($SkipAutologon) {
    Warn "Skipping auto-login (--SkipAutologon). Engine will only start after a manual sign-in."
} else {
    $domain = $env:COMPUTERNAME
    Info "Configuring auto-login for '$domain\$User' via Sysinternals Autologon."
    $tmp  = Join-Path $env:TEMP "archie-autologon"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $zip  = Join-Path $tmp "Autologon.zip"
    $exe  = Join-Path $tmp "Autologon64.exe"
    if (-not (Test-Path $exe)) {
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri "https://download.sysinternals.com/files/Autologon.zip" -OutFile $zip -UseBasicParsing
            Expand-Archive -Path $zip -DestinationPath $tmp -Force
        } catch { Fail "Could not download Sysinternals Autologon: $_  (download Autologon.zip manually to $tmp)" }
    }
    if (-not (Test-Path $exe)) { Fail "Autologon64.exe not found after extract." }

    $sec = Read-Host "  Enter the Windows password for $domain\$User (typed locally; never sent anywhere)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        # Autologon stores the secret as an LSA secret (machine-DPAPI protected) + sets AutoAdminLogon.
        & $exe $User $domain $plain "/accepteula" | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "Autologon returned exit $LASTEXITCODE (wrong password? account name?)." }
        Ok "Auto-login enabled for $domain\$User (password stored as an LSA secret, not plaintext)."
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        $plain = $null
    }
}

# ---- 3. Verify the node containers will restart with the engine ----------------------------
$containers = @("archie_node_ollama","archie_node_db","archie_node_sync","archie_node_api","archie_node_comfyui")
$bad = @()
foreach ($c in $containers) {
    $pol = (& docker inspect -f "{{.HostConfig.RestartPolicy.Name}}" $c 2>$null)
    if ([string]::IsNullOrWhiteSpace($pol)) { Info "$c — not present (skip)" }
    elseif ($pol -in @("unless-stopped","always")) { Ok "$c — restart=$pol" }
    else { Warn "$c — restart=$pol (NOT auto-restart!)"; $bad += $c }
}
if ($bad.Count) {
    Warn "Fix with: cd `$env:USERPROFILE\archie-node ; docker compose -f docker-compose.node.yml up -d"
    Warn "(the committed compose is restart: unless-stopped — re-up to apply if a container drifted)."
}

# ---- Summary -------------------------------------------------------------------------------
Write-Host "`n=== Done ===" -ForegroundColor Cyan
Write-Host "Reboot to test: power-cycle this Starship, wait ~3-5 min, then on the hub confirm the"
Write-Host "node is ONLINE (Department HQ -> Fleet) without anyone signing in here."
Write-Host "Chain: auto-login -> Docker Desktop -> engine -> unless-stopped containers -> ARCHIE-Node-Sync.`n"
