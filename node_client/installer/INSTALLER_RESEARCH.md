# Windows Installer Research Report
**Date**: 2026-03-23 | **Goal**: Fix or replace the failing Python+tkinter+PyInstaller installer

---

## Executive Summary: Recommended Architecture

**Drop the Python/tkinter GUI entirely.** Use a two-stage approach:

1. **Inno Setup** handles file deployment, Docker Desktop prerequisite, shortcuts, uninstall
2. **PowerShell + WPF** first-run script handles the dynamic parts (hardware detection, hub registration, container startup, progress GUI)

This eliminates every tkinter/PyInstaller failure mode while giving you a native Windows look and zero external dependencies.

---

## 1. Why PyInstaller + tkinter Fails on Windows

### Problems Found in Current Code (`archie_node_installer.py`, 1493 lines)

| Issue | Root Cause | Impact |
|-------|-----------|--------|
| **DPI blurriness** | tkinter lacks native high-DPI support. Windows 10/11 scales the window as a bitmap, producing blurry text on >100% scaling. | Users on laptops (125-150% scaling) see blurry UI |
| **Thread safety violations** | `_log()` uses `self.after(0, _do)` correctly, but `subprocess.run()` in threads can deadlock when capturing output while tkinter's mainloop is waiting | Hangs during hardware detection and Docker operations |
| **PyInstaller + tkinter bundling** | PyInstaller must find and bundle Tcl/Tk data directories. Python 3.12+ changed how `_tkinter` is built (dynamic vs built-in). Missing `TCL_LIBRARY`/`TK_LIBRARY` env vars cause `TclError` at startup | `.exe` crashes on machines without Python installed |
| **`--windowed` + subprocess** | `--windowed` flag hides the console, but `subprocess.run(capture_output=True)` on some Windows versions hangs because there's no console to inherit | Docker commands hang silently |
| **Single-file extraction** | `--onefile` extracts to a temp dir. Windows Defender flags it. Slow startup (5-10s). Anti-virus quarantine. | Users think installer is broken |

### DPI Fix (if you kept tkinter)
```python
# Must be called BEFORE creating Tk() window
import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
```
But this only fixes scaling, not the other issues.

---

## 2. WMIC Deprecation and Replacements

**WMIC is removed by default on Windows 11 24H2/25H2 (shipping now).** Your `install.ps1` already uses `Get-CimInstance` correctly, but the Python installer may be using `subprocess` calls to `wmic`.

### PowerShell Replacements

| Old (wmic) | New (PowerShell) |
|-----------|-----------------|
| `wmic cpu get name` | `(Get-CimInstance Win32_Processor).Name` |
| `wmic memorychip get capacity` | `(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory` |
| `wmic path win32_videocontroller get name,adapterram` | `Get-CimInstance Win32_VideoController` |
| `wmic diskdrive get size` | `Get-CimInstance Win32_LogicalDisk` |
| `wmic os get caption` | `(Get-CimInstance Win32_OperatingSystem).Caption` |

### CRITICAL: VRAM >4GB Detection Bug

`Win32_VideoController.AdapterRAM` is a **uint32** — it overflows at 4GB. An RTX 3070 (8GB) reports as 0 or 4GB.

**Fix — read from registry:**
```powershell
function Get-GpuVram {
    $gpus = Get-CimInstance Win32_VideoController | Where-Object { $_.AdapterRAM -gt 0 }
    foreach ($gpu in $gpus) {
        $vram = $gpu.AdapterRAM
        # Try registry for accurate VRAM (fixes >4GB overflow)
        $regPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        Get-ChildItem $regPath -ErrorAction SilentlyContinue | ForEach-Object {
            $driverDesc = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).'DriverDesc'
            if ($driverDesc -eq $gpu.Name) {
                $qwMem = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).'HardwareInformation.qwMemorySize'
                if ($qwMem -and $qwMem -gt $vram) { $vram = $qwMem }
            }
        }
        [PSCustomObject]@{
            Name = $gpu.Name
            VRAM_GB = [math]::Round($vram / 1GB, 1)
        }
    }
}
```

**Your current `install.ps1` line 126-135 has this bug** — it uses `$gpu.AdapterRAM` without the registry fallback. Any node with >4GB VRAM will report incorrectly to the hub.

---

## 3. Better Alternatives to tkinter for Windows Installer GUIs

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **PowerShell + WPF/XAML** | Zero dependencies (built into Windows), proper DPI scaling, native look, thread-safe dispatcher | Requires XAML knowledge, PS execution policy | **RECOMMENDED** |
| **CustomTkinter** | Drop-in tkinter replacement, modern look | Still has PyInstaller bundling issues, still not native | Not worth it |
| **PyQt6/PySide6** | Professional UI, proper threading | Adds 30-50MB to installer, complex PyInstaller bundling | Overkill |
| **Electron** | Web tech UI | 100MB+ overhead, absurd for an installer | No |
| **Inno Setup custom pages** | Built into the installer framework | Limited to wizard-style pages, no async operations | Good for simple input |
| **Pure Inno Setup + Pascal** | No external dependencies at all | Cannot do async HTTP or long-running progress | Partial solution only |

### PowerShell + WPF Example (progress window)
```powershell
Add-Type -AssemblyName PresentationFramework
[xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="A.R.C.H.I.E. Node Setup" Height="400" Width="600"
        WindowStartupLocation="CenterScreen" Background="#0a0a12">
    <StackPanel Margin="20">
        <TextBlock Text="A.R.C.H.I.E. Node" Foreground="#00e5ff" FontSize="24" FontFamily="Consolas"/>
        <ProgressBar Name="Progress" Height="20" Margin="0,20,0,10" Maximum="100"/>
        <TextBlock Name="Status" Foreground="#e0e0e0" FontFamily="Consolas"/>
        <TextBox Name="Log" Height="200" Margin="0,10,0,0" IsReadOnly="True"
                 Background="#12121f" Foreground="#666680" FontFamily="Consolas" FontSize="10"
                 VerticalScrollBarVisibility="Auto" TextWrapping="Wrap"/>
    </StackPanel>
</Window>
"@
$reader = (New-Object System.Xml.XmlNodeReader $xaml)
$window = [Windows.Markup.XamlReader]::Load($reader)
```

WPF handles DPI scaling automatically. Thread-safe updates via `$window.Dispatcher.Invoke()`.

---

## 4. Inno Setup [Code] Section Capabilities

### What Inno Setup Pascal CAN Do
- HTTP requests via COM: `CreateOleObject('WinHttp.WinHttpRequest.5.1')`
- Registry reads/writes
- File system operations
- Execute external programs and wait
- Custom wizard pages with input fields
- Check if Docker is installed (registry or PATH check)
- Display message boxes and progress

### What It CANNOT Do Well
- Async operations (no threading, no background tasks)
- Real-time progress updates during long downloads
- Complex JSON parsing (no native JSON support)
- GPU detection (would need to shell out to PowerShell)

### HTTP POST Example (works in Inno Setup)
```pascal
[Code]
function RegisterWithHub(hubUrl, payload: String): String;
var
  WinHttpReq: Variant;
begin
  Result := '';
  try
    WinHttpReq := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    WinHttpReq.Open('POST', hubUrl + '/tools/starbase/api/nodes/register', False);
    WinHttpReq.SetRequestHeader('Content-Type', 'application/json');
    WinHttpReq.Send(payload);
    if WinHttpReq.Status = 200 then
      Result := WinHttpReq.ResponseText
    else
      MsgBox('Registration failed: ' + IntToStr(WinHttpReq.Status), mbError, MB_OK);
  except
    MsgBox('Could not connect to hub.', mbError, MB_OK);
  end;
end;
```

### Verdict
Inno Setup can handle Docker-present checks and simple registration, but cannot drive the full post-install workflow (container pull, progress, health checks). Use it for installation only; delegate dynamic work to a PowerShell first-run script.

---

## 5. NSIS vs Inno Setup vs WiX

| Feature | Inno Setup | NSIS | WiX |
|---------|-----------|------|-----|
| **Output format** | .exe | .exe | .msi |
| **Scripting** | Pascal (readable) | NSIS script (arcane) | XML + C# |
| **Custom UI** | Wizard pages + Pascal | Full custom UI possible | Standard MSI UI |
| **HTTP calls** | Via COM objects | Via plugins | Via custom actions |
| **File size overhead** | ~1MB | 34KB | Varies |
| **Enterprise deployment** | No GPO support | No GPO support | Full GPO/SCCM |
| **Learning curve** | Low | Medium-High | High |
| **CI/CD** | Cross-compile on Linux via Wine | Linux via Wine | Windows only |
| **Best for** | Consumer/prosumer apps | Tiny installers, max control | Enterprise IT |

### Recommendation: **Stay with Inno Setup**

Your current `installer.iss` is clean and works. Inno Setup is the right tool for this use case (consumer-facing, .exe output, simple wizard, custom actions). WiX is overkill. NSIS scripting language is painful.

---

## 6. How Docker Desktop's Installer Works

Docker Desktop uses a **standard MSI/NSIS hybrid**:
- The downloadable `.exe` is an NSIS wrapper around an MSI
- Silent install: `"Docker Desktop Installer.exe" install --quiet --accept-license`
- Via winget: `winget install --exact --id Docker.DockerDesktop --accept-source-agreements --accept-package-agreements`
- **Requires reboot** after first install (enables WSL2/Hyper-V)
- Post-install, Docker Desktop auto-starts and shows its own onboarding UI

### Key Insight
Docker's own installer does NOT try to do everything in one step. It installs files, enables Windows features, and then requires a reboot. The actual Docker engine setup happens on first launch.

**Your installer should follow the same pattern.**

---

## 7. Best Practice: Installer vs First-Run Script

### The Two-Phase Pattern (Recommended)

**Phase 1: Inno Setup Installer (ARCHIE-Node-Setup.exe)**
- Check Windows version (10+, 64-bit)
- Check/install Docker Desktop (via winget or direct download)
- Install files to `C:\ARCHIE-Node\` (PowerShell scripts, icons, batch files)
- Create Start Menu shortcuts and desktop icon
- Write registry keys
- If Docker was just installed: schedule reboot, set resume flag
- Launch Phase 2 after install (or after reboot)

**Phase 2: PowerShell First-Run Script (with WPF GUI)**
- Detect hardware (CPU, RAM, GPU with registry VRAM fix)
- Verify Docker is running
- Prompt for Hub URL (or read from config)
- Register with hub via HTTP POST
- Write docker-compose.yml and .env
- Pull and start containers (with real-time progress)
- Wait for health checks
- Show success summary

### Why This Pattern Works
- Inno Setup handles the "installer" parts it's designed for (files, registry, shortcuts, prerequisites)
- PowerShell handles the "configuration" parts that need async operations and real progress feedback
- If something fails in Phase 2, user can re-run it without reinstalling
- No Python dependency. No PyInstaller. No tkinter. Zero external runtime.

---

## 8. PowerShell-Based Installer: Full Replacement?

### Could a single PowerShell script replace everything?

**Yes, with caveats:**

| Approach | Works? | Issue |
|----------|--------|-------|
| `irm https://... \| iex` one-liner | Yes | No .exe, requires user to open PowerShell as admin |
| `.ps1` file double-click | No | Execution policy blocks by default |
| Signed `.ps1` | Partial | Still requires right-click > Run with PowerShell |
| `.ps1` wrapped in `.bat` launcher | Yes | `powershell -ExecutionPolicy Bypass -File setup.ps1` |
| `.exe` via `ps2exe` | Yes | Anti-virus flags it even more than PyInstaller |

### Docker Installation via winget
```powershell
# Check if Docker Desktop is installed
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    # Install via winget (available on Windows 10 1809+ and all Windows 11)
    winget install --exact --id Docker.DockerDesktop --accept-source-agreements --accept-package-agreements --silent
    # NOTE: Requires reboot after first install to enable WSL2
}
```

**Known issue**: `winget install` of Docker Desktop is verbose even with `--silent`. Also, winget may not be present on older Windows 10 builds.

### Verdict
A pure PowerShell approach works for technical users (your `install.ps1` already does this well). For non-technical users who need a double-clickable `.exe`, you need Inno Setup as the entry point.

---

## Concrete Recommendation: Implementation Plan

### Architecture
```
ARCHIE-Node-Setup.exe  (Inno Setup — what user downloads and double-clicks)
  |
  +-- Installs files to C:\ARCHIE-Node\
  |     +-- setup.ps1          (Phase 2: WPF GUI setup script)
  |     +-- start.bat / stop.bat / update.bat
  |     +-- archie_icon.ico
  |
  +-- [Code] section checks:
  |     +-- Windows 10+ 64-bit?
  |     +-- Docker Desktop installed? If not, offer to install via winget
  |     +-- If Docker just installed, warn about reboot
  |
  +-- [Run] section launches:
        +-- powershell -ExecutionPolicy Bypass -File "C:\ARCHIE-Node\setup.ps1"
```

### What to Build

1. **Enhance `installer.iss`** — Add Docker Desktop detection and winget install in `[Code]` section
2. **Create `setup.ps1`** — PowerShell + WPF script that replaces `archie_node_installer.py` entirely
3. **Fix VRAM detection** — Registry-based `qwMemorySize` lookup in both `setup.ps1` and `install.ps1`
4. **Remove PyInstaller from the pipeline** — No more `build_installer.py`, no more `archie_node_installer.py`

### What to Delete
- `archie_node_installer.py` (1493 lines of fragile tkinter code)
- `build_installer.py` (PyInstaller wrapper — no longer needed)

### Files to Keep/Modify
- `installer.iss` — enhance with Docker detection + launch setup.ps1
- `install.ps1` — fix VRAM detection bug, keep as CLI alternative

---

## Sources

- [WMIC removal from Windows](https://support.microsoft.com/en-us/topic/windows-management-instrumentation-command-line-wmic-removal-from-windows-e9e83c7f-4992-477f-ba1d-96f694b8665d)
- [WMIC deprecation next steps (Microsoft)](https://techcommunity.microsoft.com/blog/windows-itpro-blog/wmi-command-line-wmic-utility-deprecation-next-steps/4039242)
- [Windows 11 25H2 WMIC removal + PowerShell alternatives](https://powershellisfun.com/2025/10/08/windows-11-25h2s-removal-of-wmic-and-the-powershell-alternative/)
- [Win32_VideoController class (Microsoft)](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-videocontroller)
- [VRAM >4GB detection workaround (NVIDIA Forums)](https://forums.developer.nvidia.com/t/how-to-query-adapter-ram-for-cards-with-more-than-4-gb-c/69955)
- [Get-CimInstance (Microsoft)](https://learn.microsoft.com/en-us/powershell/scripting/samples/getting-wmi-objects--get-ciminstance-?view=powershell-7.5)
- [Docker Desktop Windows install docs](https://docs.docker.com/desktop/setup/install/windows-install/)
- [Docker Desktop silent install parameters](https://forums.docker.com/t/unattended-installation-of-docker-desktop-which-parameters-can-be-used-besides-install-quiet/74081)
- [winget Docker.DockerDesktop](https://winget.run/pkg/Docker/DockerDesktop)
- [Inno Setup Pascal Scripting](https://jrsoftware.org/ishelp/topic_scriptintro.htm)
- [Inno Setup HTTP POST via WinHttp](https://copyprogramming.com/howto/http-post-request-in-inno-setup-script)
- [NSIS vs WiX comparison (2026)](https://copyprogramming.com/howto/nsis-vs-wix-vs-anyother-installation-packages-complete-guide)
- [PowerShell WPF GUI tutorial](https://4sysops.com/archives/create-a-gui-for-your-powershell-script-with-wpf/)
- [PyInstaller tkinter bundling issues](https://github.com/pyinstaller/pyinstaller/issues/9204)
- [Tkinter DPI awareness](https://www.pythontutorials.net/blog/attempting-to-resolve-blurred-tkinter-text-scaling-on-windows-10-high-dpi-displays-but-concerned-my-approach-is-not-pythonic-or-is-unsafe/)
- [Windows Installer best practices (Microsoft)](https://learn.microsoft.com/en-us/windows/win32/msi/windows-installer-best-practices)
