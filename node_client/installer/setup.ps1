#Requires -Version 5.1
<#
.SYNOPSIS
    A.R.C.H.I.E. Node Setup v4.0 — by Kytran Empowerment
    PowerShell + WPF first-run configuration script.
    Called by Inno Setup after file installation.

.DESCRIPTION
    Phase 2 of the two-phase installer:
    1. Detect hardware (CPU, RAM, GPU with registry VRAM fix)
    2. Verify Docker Desktop is running
    3. Configure firewall rules
    4. Register with hub via HTTP
    5. Set up Tailscale mesh VPN (optional)
    6. Write docker-compose.yml and .env
    7. Pull and start containers
    8. Wait for hub approval
    9. Download AI models (GPU nodes only)
    10. Verify deployment
#>

param(
    [string]$HubUrl = "https://archie.kytranempowerment.com",
    [string]$InstallDir = "C:\ARCHIE-Node"
)

$ErrorActionPreference = "Stop"
$ClientVersion = "4.0.0"
$TotalSteps = 10
$ResumeFile = Join-Path $InstallDir "resume_state.json"

# ── LCARS Color Palette ──────────────────────────────────────────────────────
$Colors = @{
    BgDark   = "#0a0a12"
    BgPanel  = "#12121f"
    BgInput  = "#1e293b"
    Cyan     = "#00e5ff"
    Orange   = "#f97316"
    Green    = "#10b981"
    Red      = "#ef4444"
    Yellow   = "#fbbf24"
    TextPri  = "#e0e0e0"
    TextDim  = "#666680"
    Border   = "#1e3a5f"
}

# ── State ────────────────────────────────────────────────────────────────────
$script:NodeId = $null
$script:ApiKey = $null
$script:HeadscaleKey = $null
$script:HwInfo = @{}
$script:CancelFlag = $false

# ── WPF GUI ──────────────────────────────────────────────────────────────────
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

[xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="A.R.C.H.I.E. Node Setup v4.0" Height="580" Width="700"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        Background="$($Colors.BgDark)">
    <Grid Margin="20">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Title -->
        <StackPanel Grid.Row="0" Margin="0,0,0,8">
            <TextBlock Text="A.R.C.H.I.E. Node v4.0" Foreground="$($Colors.Cyan)"
                       FontSize="22" FontFamily="Consolas" FontWeight="Bold"/>
            <TextBlock Text="by Kytran Empowerment" Foreground="$($Colors.TextDim)"
                       FontSize="11" FontFamily="Consolas" Margin="0,2,0,0"/>
            <Border Height="2" Background="$($Colors.Cyan)" Margin="0,6,0,0"/>
        </StackPanel>

        <!-- Hub URL -->
        <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="0,8,0,4">
            <TextBlock Text="Hub URL:" Foreground="$($Colors.TextDim)" FontFamily="Consolas"
                       FontSize="11" VerticalAlignment="Center" Margin="0,0,8,0"/>
            <TextBox Name="HubUrlBox" Width="500" FontFamily="Consolas" FontSize="12"
                     Background="$($Colors.BgInput)" Foreground="$($Colors.TextPri)"
                     BorderBrush="$($Colors.Border)" Padding="6,4"
                     Text="$HubUrl"/>
        </StackPanel>

        <!-- Hardware Panel -->
        <Border Grid.Row="2" BorderBrush="$($Colors.Border)" BorderThickness="1"
                Background="$($Colors.BgPanel)" CornerRadius="4" Margin="0,8,0,0" Padding="12,8">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/><ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="*"/><ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <StackPanel Grid.Column="0">
                    <TextBlock Text="CPU" Foreground="$($Colors.TextDim)" FontFamily="Consolas" FontSize="9"/>
                    <TextBlock Name="HwCpu" Text="--" Foreground="$($Colors.TextPri)" FontFamily="Consolas" FontSize="10"/>
                </StackPanel>
                <StackPanel Grid.Column="1">
                    <TextBlock Text="RAM" Foreground="$($Colors.TextDim)" FontFamily="Consolas" FontSize="9"/>
                    <TextBlock Name="HwRam" Text="--" Foreground="$($Colors.TextPri)" FontFamily="Consolas" FontSize="10"/>
                </StackPanel>
                <StackPanel Grid.Column="2">
                    <TextBlock Text="GPU" Foreground="$($Colors.TextDim)" FontFamily="Consolas" FontSize="9"/>
                    <TextBlock Name="HwGpu" Text="--" Foreground="$($Colors.TextPri)" FontFamily="Consolas" FontSize="10"/>
                </StackPanel>
                <StackPanel Grid.Column="3">
                    <TextBlock Text="DISK" Foreground="$($Colors.TextDim)" FontFamily="Consolas" FontSize="9"/>
                    <TextBlock Name="HwDisk" Text="--" Foreground="$($Colors.TextPri)" FontFamily="Consolas" FontSize="10"/>
                </StackPanel>
            </Grid>
        </Border>

        <!-- Progress -->
        <StackPanel Grid.Row="3" Margin="0,12,0,0">
            <TextBlock Name="StepLabel" Text="Ready to install" Foreground="$($Colors.TextDim)"
                       FontFamily="Consolas" FontSize="10" Margin="0,0,0,4"/>
            <ProgressBar Name="ProgressBar" Height="16" Minimum="0" Maximum="$TotalSteps"
                         Value="0" Foreground="$($Colors.Cyan)" Background="$($Colors.BgInput)"/>
        </StackPanel>

        <!-- Log -->
        <Border Grid.Row="4" BorderBrush="$($Colors.Border)" BorderThickness="1"
                Background="$($Colors.BgPanel)" CornerRadius="4" Margin="0,12,0,0">
            <ScrollViewer Name="LogScroll" VerticalScrollBarVisibility="Auto">
                <TextBlock Name="LogText" FontFamily="Consolas" FontSize="10"
                           Foreground="$($Colors.TextDim)" TextWrapping="Wrap" Padding="8"/>
            </ScrollViewer>
        </Border>

        <!-- Buttons -->
        <StackPanel Grid.Row="5" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,12,0,0">
            <Button Name="CancelBtn" Content="CANCEL" FontFamily="Consolas" FontSize="11"
                    Background="$($Colors.BgInput)" Foreground="$($Colors.TextDim)"
                    BorderBrush="$($Colors.Border)" Padding="16,6" Margin="0,0,8,0" Cursor="Hand"/>
            <Button Name="InstallBtn" Content="INSTALL" FontFamily="Consolas" FontSize="11" FontWeight="Bold"
                    Background="$($Colors.Cyan)" Foreground="$($Colors.BgDark)"
                    BorderThickness="0" Padding="24,6" Cursor="Hand"/>
        </StackPanel>
    </Grid>
</Window>
"@

$reader = New-Object System.Xml.XmlNodeReader $xaml
$window = [Windows.Markup.XamlReader]::Load($reader)

# Find controls
$hubUrlBox  = $window.FindName("HubUrlBox")
$hwCpu      = $window.FindName("HwCpu")
$hwRam      = $window.FindName("HwRam")
$hwGpu      = $window.FindName("HwGpu")
$hwDisk     = $window.FindName("HwDisk")
$stepLabel  = $window.FindName("StepLabel")
$progressBar = $window.FindName("ProgressBar")
$logText    = $window.FindName("LogText")
$logScroll  = $window.FindName("LogScroll")
$installBtn = $window.FindName("InstallBtn")
$cancelBtn  = $window.FindName("CancelBtn")

# ── Thread-safe UI helpers ───────────────────────────────────────────────────
function Update-UI {
    param([scriptblock]$Action)
    $window.Dispatcher.Invoke([Action]$Action, [System.Windows.Threading.DispatcherPriority]::Background)
}

function Write-Log {
    param([string]$Message, [string]$Color = $Colors.TextDim)
    Update-UI {
        $logText.Inlines.Add((New-Object System.Windows.Documents.Run -Property @{
            Text = "$Message`r`n"
            Foreground = [System.Windows.Media.BrushConverter]::new().ConvertFromString($Color)
        }))
        $logScroll.ScrollToEnd()
    }
}

function Set-Step {
    param([int]$Num, [string]$Desc)
    Update-UI {
        $stepLabel.Text = "Step $Num/$TotalSteps  $Desc"
        $progressBar.Value = $Num
    }
    Write-Log ">> $Desc" $Colors.Cyan
}

function Set-HwLabel {
    param([string]$Key, [string]$Value)
    Update-UI {
        switch ($Key) {
            "CPU"  { $hwCpu.Text = $Value }
            "RAM"  { $hwRam.Text = $Value }
            "GPU"  { $hwGpu.Text = $Value }
            "DISK" { $hwDisk.Text = $Value }
        }
    }
}

# ── Network helpers ──────────────────────────────────────────────────────────
function Invoke-HubGet {
    param([string]$Path, [int]$Timeout = 30)
    $url = "$($hubUrlBox.Text.TrimEnd('/'))$Path"
    $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec $Timeout -UseBasicParsing
    return $resp
}

function Invoke-HubPost {
    param([string]$Path, [hashtable]$Body, [int]$Timeout = 30)
    $url = "$($hubUrlBox.Text.TrimEnd('/'))$Path"
    $json = $Body | ConvertTo-Json -Depth 5
    $resp = Invoke-RestMethod -Uri $url -Method Post -Body $json -ContentType "application/json" -TimeoutSec $Timeout -UseBasicParsing
    return $resp
}

function Get-LocalIP {
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
            $_.InterfaceAlias -notmatch "Loopback" -and $_.IPAddress -ne "127.0.0.1"
        } | Select-Object -First 1).IPAddress
        return $ip
    } catch { return "0.0.0.0" }
}

# ── Step 1: Prerequisites ────────────────────────────────────────────────────
function Step-Prerequisites {
    # Admin check
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        throw "This installer must be run as Administrator."
    }
    Write-Log "[OK] Running as Administrator" $Colors.Green

    # Internet check
    try {
        $hubUrl = $hubUrlBox.Text.TrimEnd('/')
        Invoke-WebRequest -Uri $hubUrl -Method Head -TimeoutSec 10 -UseBasicParsing | Out-Null
        Write-Log "[OK] Hub reachable: $hubUrl" $Colors.Green
    } catch {
        throw "Cannot reach hub at $hubUrl. Check your internet connection and Hub URL."
    }

    # Create install directory
    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }
    Write-Log "[OK] Install directory: $InstallDir" $Colors.Green
}

# ── Step 2: Hardware Detection ───────────────────────────────────────────────
function Step-Hardware {
    # CPU
    $cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1)
    $cpuName = $cpu.Name.Trim()
    $cpuCores = $cpu.NumberOfLogicalProcessors
    $displayCpu = if ($cpuName.Length -gt 30) { $cpuName.Substring(0, 30) + "..." } else { $cpuName }
    Set-HwLabel "CPU" "$displayCpu ($($cpuCores)c)"
    Write-Log "[OK] CPU: $cpuName ($cpuCores cores)" $Colors.Green
    $script:HwInfo.cpu_model = $cpuName
    $script:HwInfo.cpu_cores = $cpuCores

    # RAM
    $ramBytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
    $ramGb = [math]::Round($ramBytes / 1GB, 1)
    Set-HwLabel "RAM" "$ramGb GB"
    Write-Log "[OK] RAM: $ramGb GB" $Colors.Green
    $script:HwInfo.ram_gb = $ramGb

    # GPU — detect ALL discrete GPUs (NVIDIA, AMD, Intel Arc)
    # Skip integrated/virtual: Microsoft Basic, VMware, VirtualBox, Intel UHD/HD Graphics
    $gpuAvailable = $false
    $gpuModel = $null
    $gpuVramGb = $null
    $allGpus = @()
    $gpus = Get-CimInstance Win32_VideoController | Where-Object {
        $_.Name -and
        $_.Name -notmatch "Microsoft Basic|VMware|VirtualBox|Remote Desktop" -and
        $_.AdapterRAM -gt 0
    }
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    foreach ($gpu in $gpus) {
        $vram = $gpu.AdapterRAM
        # Registry fix for VRAM >4GB (uint32 overflow)
        Get-ChildItem $regPath -ErrorAction SilentlyContinue | ForEach-Object {
            $driverDesc = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).'DriverDesc'
            if ($driverDesc -eq $gpu.Name) {
                $qwMem = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).'HardwareInformation.qwMemorySize'
                if ($qwMem -and $qwMem -gt $vram) { $vram = $qwMem }
            }
        }
        $vramGb = [math]::Round($vram / 1GB, 1)
        $isDiscrete = $gpu.Name -match "NVIDIA|AMD|Radeon RX|Intel Arc|GeForce|Quadro|RTX|Tesla"
        $allGpus += @{ Name = $gpu.Name; VramGb = $vramGb; Discrete = $isDiscrete }
        Write-Log "[OK] GPU: $($gpu.Name) ($vramGb GB VRAM)$(if($isDiscrete){' [DISCRETE]'})" $Colors.Green
    }
    # Pick best discrete GPU for primary assignment (prefer NVIDIA for CUDA, then AMD, then Intel)
    $discrete = $allGpus | Where-Object { $_.Discrete } | Sort-Object { $_.VramGb } -Descending
    if ($discrete) {
        $best = $discrete[0]
        $gpuAvailable = $true
        $gpuModel = $best.Name
        $gpuVramGb = $best.VramGb
        $displayGpu = if ($gpuModel.Length -gt 25) { $gpuModel.Substring(0, 25) + "..." } else { $gpuModel }
        Set-HwLabel "GPU" "$displayGpu ($($gpuVramGb)GB)"
        if ($discrete.Count -gt 1) {
            Write-Log "[OK] $($discrete.Count) discrete GPUs found — primary: $gpuModel" $Colors.Green
        }
    } elseif ($allGpus.Count -gt 0) {
        # Only integrated GPU found
        $igpu = $allGpus[0]
        Set-HwLabel "GPU" "$($igpu.Name) (integrated)"
        Write-Log "[~] Only integrated GPU found — CPU-only mode for LLM" $Colors.Yellow
    } else {
        Set-HwLabel "GPU" "None detected"
        Write-Log "[~] No GPU detected — CPU-only mode" $Colors.Yellow
    }
    $script:HwInfo.gpu_available = $gpuAvailable
    $script:HwInfo.gpu_model = $gpuModel
    $script:HwInfo.gpu_vram_gb = $gpuVramGb
    $script:HwInfo.all_gpus = $allGpus | ForEach-Object { @{ name = $_.Name; vram_gb = $_.VramGb } }

    # Disk
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $diskFreeGb = [math]::Round($disk.FreeSpace / 1GB, 1)
    $diskTotalGb = [math]::Round($disk.Size / 1GB, 1)
    Set-HwLabel "DISK" "$diskFreeGb GB free"
    Write-Log "[OK] Disk: $diskFreeGb GB free / $diskTotalGb GB total" $Colors.Green
    $script:HwInfo.disk_free_gb = $diskFreeGb
    $script:HwInfo.os_info = "Windows $([Environment]::OSVersion.Version.ToString()) $([Environment]Is64BitOperatingSystem ? 'x64' : 'x86')"
    $script:HwInfo.hostname = $env:COMPUTERNAME
}

# ── Step 3: Docker Check ─────────────────────────────────────────────────────
function Step-Docker {
    $dockerOk = $false
    try {
        $v = docker --version 2>&1
        if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
    } catch {}

    if (-not $dockerOk) {
        Write-Log "[!] Docker Desktop not found. Installing via winget..." $Colors.Orange
        try {
            winget install --exact --id Docker.DockerDesktop --accept-source-agreements --accept-package-agreements --silent 2>&1 | ForEach-Object { Write-Log "    $_" }
            Write-Log "[OK] Docker Desktop installed" $Colors.Green
            Write-Log "[!] Docker Desktop requires a RESTART to enable WSL2." $Colors.Yellow
            Write-Log "[!] After restart, run this setup again." $Colors.Yellow

            # Save resume state
            @{ step = 3; hub_url = $hubUrlBox.Text; hw_info = $script:HwInfo } |
                ConvertTo-Json | Set-Content $ResumeFile -Encoding UTF8

            $result = [System.Windows.MessageBox]::Show(
                "Docker Desktop was installed and requires a restart.`n`nRestart now?",
                "Restart Required", "YesNo", "Warning")
            if ($result -eq "Yes") {
                shutdown /r /t 10 /c "Restarting for Docker Desktop setup"
            }
            return
        } catch {
            # Fallback: direct download
            Write-Log "[!] winget failed, trying direct download..." $Colors.Orange
            $dockerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
            $dockerExe = Join-Path $env:TEMP "DockerDesktopInstaller.exe"
            Write-Log "    Downloading Docker Desktop..." $Colors.TextDim
            Invoke-WebRequest -Uri $dockerUrl -OutFile $dockerExe -UseBasicParsing
            Write-Log "    Running installer (this may take a few minutes)..." $Colors.TextDim
            Start-Process -FilePath $dockerExe -ArgumentList "install --quiet --accept-license" -Wait
            Remove-Item $dockerExe -ErrorAction SilentlyContinue

            @{ step = 3; hub_url = $hubUrlBox.Text; hw_info = $script:HwInfo } |
                ConvertTo-Json | Set-Content $ResumeFile -Encoding UTF8

            $result = [System.Windows.MessageBox]::Show(
                "Docker Desktop installed. A restart is required.`n`nRestart now?",
                "Restart Required", "YesNo", "Warning")
            if ($result -eq "Yes") {
                shutdown /r /t 10 /c "Restarting for Docker Desktop setup"
            }
            return
        }
    }

    Write-Log "[OK] Docker Desktop found: $v" $Colors.Green

    # Check if Docker daemon is running
    $running = $false
    try { docker ps 2>&1 | Out-Null; if ($LASTEXITCODE -eq 0) { $running = $true } } catch {}

    if (-not $running) {
        Write-Log "[~] Docker not running, starting Docker Desktop..." $Colors.Yellow
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 18; $i++) {
            Start-Sleep -Seconds 5
            try { docker ps 2>&1 | Out-Null; if ($LASTEXITCODE -eq 0) { $running = $true; break } } catch {}
            Write-Log "    Waiting for Docker daemon... ($($i * 5)s)" $Colors.TextDim
        }
        if (-not $running) {
            throw "Docker Desktop did not start within 90 seconds. Start it manually and re-run setup."
        }
    }
    Write-Log "[OK] Docker daemon is running" $Colors.Green
}

# ── Step 4: Firewall ─────────────────────────────────────────────────────────
function Step-Firewall {
    $rules = @(
        @{ Name = "ARCHIE Beacon (3001)";  Port = 3001; Protocol = "TCP" },
        @{ Name = "ARCHIE ComfyUI (8188)"; Port = 8188; Protocol = "TCP" },
        @{ Name = "ARCHIE Ollama (11434)"; Port = 11434; Protocol = "TCP" }
    )
    foreach ($rule in $rules) {
        $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
        if (-not $existing) {
            New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound `
                -LocalPort $rule.Port -Protocol $rule.Protocol -Action Allow -Profile Any | Out-Null
            Write-Log "[OK] Firewall: $($rule.Name) opened" $Colors.Green
        } else {
            Write-Log "[OK] Firewall: $($rule.Name) already exists" $Colors.Green
        }
    }
    # ICMP ping
    $ping = Get-NetFirewallRule -DisplayName "ARCHIE Ping (ICMPv4)" -ErrorAction SilentlyContinue
    if (-not $ping) {
        New-NetFirewallRule -DisplayName "ARCHIE Ping (ICMPv4)" -Direction Inbound `
            -Protocol ICMPv4 -IcmpType 8 -Action Allow -Profile Any | Out-Null
        Write-Log "[OK] Firewall: ICMPv4 ping enabled" $Colors.Green
    }
}

# ── Step 5: Register with Hub ────────────────────────────────────────────────
function Step-Register {
    $localIp = Get-LocalIP
    $payload = @{
        node_name      = $env:COMPUTERNAME
        hostname       = $localIp
        port           = 11434
        gpu_available  = $script:HwInfo.gpu_available
        gpu_model      = $script:HwInfo.gpu_model
        gpu_vram_gb    = $script:HwInfo.gpu_vram_gb
        all_gpus       = $script:HwInfo.all_gpus
        cpu_cores      = $script:HwInfo.cpu_cores
        cpu_model      = $script:HwInfo.cpu_model
        ram_gb         = $script:HwInfo.ram_gb
        disk_gb        = $script:HwInfo.disk_free_gb
        os_info        = $script:HwInfo.os_info
        client_version = $ClientVersion
        tags           = @("windows")
    }

    try {
        $resp = Invoke-HubPost -Path "/tools/starbase/api/nodes/register" -Body $payload
        if ($resp.success) {
            $script:NodeId = $resp.node_id
            $script:ApiKey = $resp.api_key
            $script:HeadscaleKey = $resp.headscale_authkey
            Write-Log "[OK] Registered with hub. Node ID: $($script:NodeId)" $Colors.Green
        } else {
            throw "Hub returned: $($resp.error)"
        }
    } catch {
        throw "Registration failed: $_"
    }
}

# ── Step 6: Tailscale VPN ────────────────────────────────────────────────────
function Step-Tailscale {
    if (-not $script:HeadscaleKey) {
        Write-Log "[~] No mesh VPN key — running in LAN-only mode" $Colors.Yellow
        return
    }

    $tsExe = $null
    foreach ($p in @("$env:ProgramFiles\Tailscale\tailscale.exe", "${env:ProgramFiles(x86)}\Tailscale\tailscale.exe")) {
        if (Test-Path $p) { $tsExe = $p; break }
    }
    if (-not $tsExe) { $tsExe = (Get-Command tailscale -ErrorAction SilentlyContinue).Source }

    if (-not $tsExe) {
        Write-Log "    Installing Tailscale..." $Colors.TextDim
        $msiUrl = "https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi"
        $msiPath = Join-Path $env:TEMP "tailscale-setup.msi"
        Invoke-WebRequest -Uri $msiUrl -OutFile $msiPath -UseBasicParsing
        Start-Process msiexec -ArgumentList "/i `"$msiPath`" /qn" -Wait
        Remove-Item $msiPath -ErrorAction SilentlyContinue
        $tsExe = "$env:ProgramFiles\Tailscale\tailscale.exe"
    }

    Write-Log "    Authenticating with mesh VPN..." $Colors.TextDim
    & $tsExe up --authkey=$script:HeadscaleKey 2>&1 | ForEach-Object { Write-Log "    $_" }
    Write-Log "[OK] Tailscale VPN connected" $Colors.Green
}

# ── Step 7: Write Compose & Config ───────────────────────────────────────────
function Step-WriteConfig {
    $hubUrl = $hubUrlBox.Text.TrimEnd('/')

    # .env file
    $envContent = @"
NODE_ID=$($script:NodeId)
API_KEY=$($script:ApiKey)
HUB_URL=$hubUrl
NODE_NAME=$($env:COMPUTERNAME)
OLLAMA_HOST=0.0.0.0
OLLAMA_KEEP_ALIVE=24h
"@
    Set-Content (Join-Path $InstallDir ".env") $envContent -Encoding UTF8
    Write-Log "[OK] Environment config written" $Colors.Green

    # docker-compose.yml — copy from installed files or download
    $composeSrc = Join-Path $InstallDir "docker-compose.node.yml"
    $composeDst = Join-Path $InstallDir "docker-compose.yml"
    if (Test-Path $composeSrc) {
        Copy-Item $composeSrc $composeDst -Force
        Write-Log "[OK] docker-compose.yml ready" $Colors.Green
    } else {
        # Download from hub
        try {
            $composeUrl = "$hubUrl/static/downloads/docker-compose.node.yml"
            Invoke-WebRequest -Uri $composeUrl -OutFile $composeDst -UseBasicParsing
            Write-Log "[OK] docker-compose.yml downloaded from hub" $Colors.Green
        } catch {
            throw "Could not find docker-compose.yml. Re-run the Inno Setup installer first."
        }
    }

    # Helper scripts
    $scripts = @{
        "start.bat"  = "@echo off`r`ncd /d `"$InstallDir`"`r`ndocker compose up -d`r`npause"
        "stop.bat"   = "@echo off`r`ncd /d `"$InstallDir`"`r`ndocker compose down`r`npause"
        "update.bat" = "@echo off`r`ncd /d `"$InstallDir`"`r`ndocker compose pull`r`ndocker compose up -d`r`npause"
    }
    foreach ($name in $scripts.Keys) {
        $path = Join-Path $InstallDir $name
        if (-not (Test-Path $path)) {
            Set-Content $path $scripts[$name] -Encoding ASCII
        }
    }
    Write-Log "[OK] Helper scripts ready (start/stop/update)" $Colors.Green
}

# ── Step 8: Pull & Start Containers ──────────────────────────────────────────
function Step-StartContainers {
    Set-Location $InstallDir
    Write-Log "    Pulling Docker images (this may take several minutes)..." $Colors.TextDim
    $pullOutput = docker compose pull 2>&1
    foreach ($line in $pullOutput) { Write-Log "    $line" }
    if ($LASTEXITCODE -ne 0) { throw "Docker compose pull failed." }
    Write-Log "[OK] Images pulled" $Colors.Green

    Write-Log "    Starting containers..." $Colors.TextDim
    docker compose up -d 2>&1 | ForEach-Object { Write-Log "    $_" }
    if ($LASTEXITCODE -ne 0) { throw "Docker compose up failed." }

    Start-Sleep -Seconds 5
    $containers = docker compose ps -q 2>&1
    $count = ($containers | Measure-Object).Count
    Write-Log "[OK] $count container(s) running" $Colors.Green
}

# ── Step 9: Wait for Approval ────────────────────────────────────────────────
function Step-WaitApproval {
    Write-Log "    Waiting for hub approval (check Starship Command on hub)..." $Colors.TextDim
    for ($i = 0; $i -lt 60; $i++) {
        if ($script:CancelFlag) { return }
        try {
            $resp = Invoke-HubGet -Path "/tools/starbase/api/nodes/$($script:NodeId)/status" -Timeout 10
            $status = if ($resp.status) { $resp.status } elseif ($resp.approval_status) { $resp.approval_status } else { "pending" }
            if ($status -in @("approved", "active", "online")) {
                Write-Log "[OK] Node approved!" $Colors.Green
                return
            }
        } catch {}
        Start-Sleep -Seconds 10
        if ($i % 3 -eq 0) { Write-Log "    Still waiting... ($($i * 10)s)" $Colors.TextDim }
    }
    Write-Log "[~] Approval timeout — node will sync once approved on the hub" $Colors.Yellow
}

# ── Step 10: Verify ──────────────────────────────────────────────────────────
function Step-Verify {
    Write-Log "" $Colors.TextDim
    Write-Log "========================================" $Colors.Cyan
    Write-Log "  A.R.C.H.I.E. Node Setup Complete!" $Colors.Green
    Write-Log "========================================" $Colors.Cyan
    Write-Log "  Node ID:     $($script:NodeId)" $Colors.TextPri
    Write-Log "  Hub:         $($hubUrlBox.Text)" $Colors.TextPri
    Write-Log "  Install Dir: $InstallDir" $Colors.TextPri
    Write-Log "  Version:     $ClientVersion" $Colors.TextPri
    Write-Log "" $Colors.TextDim

    # Container status
    $ps = docker compose ps 2>&1
    foreach ($line in $ps) { Write-Log "  $line" $Colors.TextDim }

    # Clean resume file
    Remove-Item $ResumeFile -ErrorAction SilentlyContinue

    Update-UI {
        $installBtn.Content = "CLOSE"
        $installBtn.Background = [System.Windows.Media.BrushConverter]::new().ConvertFromString($Colors.Green)
    }
}

# ── Main Install Runner ──────────────────────────────────────────────────────
function Start-Install {
    param([int]$ResumeFrom = 0)

    $steps = @(
        @{ Num = 1;  Desc = "Checking prerequisites...";   Func = { Step-Prerequisites } },
        @{ Num = 2;  Desc = "Detecting hardware...";       Func = { Step-Hardware } },
        @{ Num = 3;  Desc = "Checking Docker...";          Func = { Step-Docker } },
        @{ Num = 4;  Desc = "Configuring firewall...";     Func = { Step-Firewall } },
        @{ Num = 5;  Desc = "Registering with hub...";     Func = { Step-Register } },
        @{ Num = 6;  Desc = "Setting up mesh VPN...";      Func = { Step-Tailscale } },
        @{ Num = 7;  Desc = "Writing configuration...";    Func = { Step-WriteConfig } },
        @{ Num = 8;  Desc = "Starting containers...";      Func = { Step-StartContainers } },
        @{ Num = 9;  Desc = "Waiting for approval...";     Func = { Step-WaitApproval } },
        @{ Num = 10; Desc = "Verifying deployment...";     Func = { Step-Verify } }
    )

    Update-UI {
        $installBtn.IsEnabled = $false
        $hubUrlBox.IsEnabled = $false
    }

    foreach ($step in $steps) {
        if ($script:CancelFlag) {
            Write-Log "[!] Installation cancelled." $Colors.Orange
            Update-UI { $installBtn.IsEnabled = $true; $hubUrlBox.IsEnabled = $true }
            return
        }
        if ($step.Num -lt $ResumeFrom) { continue }

        Set-Step -Num $step.Num -Desc $step.Desc
        try {
            & $step.Func
        } catch {
            Write-Log "[!!] Error: $_" $Colors.Red
            Write-Log "[!!] Fix the issue and re-run setup." $Colors.Red
            Update-UI {
                $installBtn.IsEnabled = $true
                $installBtn.Content = "RETRY"
                $hubUrlBox.IsEnabled = $true
            }
            return
        }
    }
}

# ── Button Handlers ──────────────────────────────────────────────────────────
$installBtn.Add_Click({
    if ($installBtn.Content -eq "CLOSE") {
        $window.Close()
        return
    }
    $script:CancelFlag = $false
    # Run install in background thread
    $runspace = [RunspaceFactory]::CreateRunspace()
    $runspace.ApartmentState = "STA"
    $runspace.ThreadOptions = "ReuseThread"
    $runspace.Open()
    $runspace.SessionStateProxy.SetVariable("window", $window)
    $runspace.SessionStateProxy.SetVariable("scriptScope", $script:ExecutionContext)

    $ps = [PowerShell]::Create()
    $ps.Runspace = $runspace
    $ps.AddScript({
        Start-Install
    }) | Out-Null
    $ps.BeginInvoke() | Out-Null
})

$cancelBtn.Add_Click({
    $script:CancelFlag = $true
    Write-Log "[!] Cancelling..." $Colors.Orange
})

# ── Check for resume state ───────────────────────────────────────────────────
if (Test-Path $ResumeFile) {
    $resume = Get-Content $ResumeFile -Raw | ConvertFrom-Json
    Write-Log "[~] Resuming from step $($resume.step) after reboot..." $Colors.Yellow
    if ($resume.hub_url) { $hubUrlBox.Text = $resume.hub_url }
    # Auto-start from resume point
    $window.Add_Loaded({
        Start-Sleep -Milliseconds 500
        Start-Install -ResumeFrom $resume.step
    })
}

# ── Show Window ──────────────────────────────────────────────────────────────
$window.ShowDialog() | Out-Null
