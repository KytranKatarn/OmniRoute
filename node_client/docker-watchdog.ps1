# ArchieDockerWatchdog - self-heal Docker Desktop boot-race on Starship nodes
# Issue #3956 / KB #275989. Runs every 5 min via Scheduled Task.
# SAFE: does NOTHING when Docker is healthy. Only restarts Docker Desktop after
# >=3 consecutive failed health checks (~15 min sustained down) so it never kills
# a Docker that is merely mid-startup.
$ErrorActionPreference = 'SilentlyContinue'
$dir   = Join-Path $env:LOCALAPPDATA 'archie'
$state = Join-Path $dir 'docker-watchdog.state'
$log   = Join-Path $dir 'docker-watchdog.log'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
function Log($m){ Add-Content -Path $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  ' + $m) }

$docker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
if (-not (Test-Path $docker)) { $docker = 'docker' }

# --- health check: `docker ps` exit code (direct call — the Start-Process wrapper
# false-negatived). NOTE: `ps` not `info` — `docker info` exits non-zero on these
# nodes even when healthy. Engine-down makes `docker ps` fail FAST on Windows
# (missing named pipe), so no timeout machinery is needed. ---
$ok = $false
try {
  & $docker ps -q 2>$null | Out-Null
  $ok = ($LASTEXITCODE -eq 0)
} catch { $ok = $false }

if ($ok) {
  if ((Get-Content $state -ErrorAction SilentlyContinue) -ne '0') { Log 'docker healthy (recovered)' }
  Set-Content -Path $state -Value '0'
  exit 0
}

# --- unhealthy: count consecutive failures; act only after sustained downtime ---
$fails = 0
if (Test-Path $state) { $fails = [int](Get-Content $state) }
$fails++
Set-Content -Path $state -Value $fails
Log "docker unreachable (consecutive=$fails)"
if ($fails -lt 3) { exit 0 }

Log 'RESTART: docker stuck >=3 checks - restarting Docker Desktop'
Get-Process 'Docker Desktop','com.docker.backend','com.docker.build','com.docker.dev-envs' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5
& wsl.exe --shutdown 2>$null
Start-Sleep -Seconds 5
Start-Process -FilePath 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
Set-Content -Path $state -Value '0'
Log 'RESTART: relaunched Docker Desktop'
