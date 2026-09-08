# =============================================================================
# A.R.C.H.I.E. DR — hub reachability probe, WINDOWS vantage (1-vantage).
#
# The PowerShell twin of probe_hub.sh. Streamed over SSH by probe_outpost to any
# vantage annotated `|pwsh` in the OUTPOSTS array.
#
# WHY THIS EXISTS (2026-09-08, #3249): the LAN Starships are Windows. They have
# SSH but no bash and no python3, so `bash -s` failed with a non-255 exit — and
# probe_outpost mapped every non-255 failure to "down". Against a verifiably UP
# hub both Starships returned exit=1 -> "down": a host that CANNOT ANSWER was
# indistinguishable from one REPORTING AN OUTAGE. Adding them as vantages would
# have held quorum permanently on phantom votes, so the first mesh hiccup on a
# healthy hub would auto-promote. They were excluded until this probe existed.
#
# Probes the hub MESH IP on BOTH:
#   * TCP  100.64.0.4:5432   (Postgres — matches failover.sh's split-brain guard)
#   * HTTP 100.64.0.4:3000/login
# BOTH must fail to call the hub down from here — a single-port blip is not an
# outage. Mesh IP only: MagicDNS dies with the hub, so never use a hostname.
#
# CONTRACT — identical to probe_hub.sh, and the sentinel is the load-bearing part:
#   prints PROBE_RESULT=up   + exit 0  -> hub reachable from this vantage
#   prints PROBE_RESULT=down + exit 1  -> hub down from this vantage
#   prints NOTHING                     -> the probe could not run; the caller MUST
#                                         read that as "unreachable", never "down".
# The exit code alone is not trustworthy across shells; the sentinel is what
# probe_outpost parses. That is the whole fix for the false-down-vote class.
#
# PowerShell 5.1 compatible (verified live on both Starships, 2026-09-08).
# =============================================================================
$ErrorActionPreference = 'Stop'

$HubMesh     = if ($env:HUB_MESH) { $env:HUB_MESH } else { '100.64.0.4' }
$PgPort      = if ($env:HUB_PG_PORT) { [int]$env:HUB_PG_PORT } else { 5432 }
$HttpPort    = if ($env:HUB_HTTP_PORT) { [int]$env:HUB_HTTP_PORT } else { 3000 }
$TcpTimeout  = if ($env:PROBE_TCP_TIMEOUT) { [int]$env:PROBE_TCP_TIMEOUT } else { 5 }
$HttpTimeout = if ($env:PROBE_HTTP_TIMEOUT) { [int]$env:PROBE_HTTP_TIMEOUT } else { 8 }

# --- TCP probe: Postgres port -------------------------------------------------
# Async connect + WaitOne, because a bare TcpClient.Connect() ignores our timeout
# and can hang far past the watchdog's cycle on a black-holed route.
function Test-TcpPort {
    param([string]$TargetHost, [int]$Port, [int]$TimeoutSec)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne([TimeSpan]::FromSeconds($TimeoutSec))) { return $false }
        $client.EndConnect($async)   # throws if the connect actually failed
        return $client.Connected
    } catch { return $false } finally { $client.Close() }
}

$tcpOk = Test-TcpPort -TargetHost $HubMesh -Port $PgPort -TimeoutSec $TcpTimeout

# --- HTTP probe: /login returns ANY status ------------------------------------
# A 4xx/5xx still proves the server ANSWERED, so it counts as up — same rule as
# probe_hub.sh, which treats urllib's HTTPError as a success.
$httpOk = $false
try {
    $resp = Invoke-WebRequest -Uri ("http://{0}:{1}/login" -f $HubMesh, $HttpPort) `
                              -UseBasicParsing -TimeoutSec $HttpTimeout
    if ($resp.StatusCode) { $httpOk = $true }
} catch [System.Net.WebException] {
    # An HTTP error response means it answered; a timeout/DNS/refusal does not.
    if ($_.Exception.Response -ne $null) { $httpOk = $true }
} catch { $httpOk = $false }

if ($tcpOk -or $httpOk) { Write-Output 'PROBE_RESULT=up';   exit 0 }
Write-Output 'PROBE_RESULT=down'
exit 1
