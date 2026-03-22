# A.R.C.H.I.E. Node — Professional Windows Installer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a professional Windows installer using Inno Setup that installs the A.R.C.H.I.E. Node app with proper shortcuts, service registration, and Add/Remove Programs entry.

**Architecture:** PyInstaller bundles the Python tkinter app into a standalone `.exe`. Inno Setup wraps that `.exe` into a proper Windows installer with wizard UI, shortcuts, service registration, and uninstaller. GitHub Actions builds both stages on `windows-latest`.

**Tech Stack:** Python 3.11, PyInstaller, Inno Setup 6, NSSM (service wrapper), ImageMagick (ICO conversion), GitHub Actions

**Spec:** `docs/superpowers/specs/2026-03-22-windows-installer-design.md`

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `node_client/installer/archie_node_installer.py` | Modify | Branding updates + install dir fix |
| `node_client/installer/build_installer.py` | Modify | Rename output + add `shutil` import |
| `node_client/installer/installer.iss` | Create | Inno Setup script (install wizard config) |
| `node_client/installer/logo-sm.png` | Copy | Logo source for ICO conversion |
| `node_client/installer/nssm.exe` | Download | Service wrapper for BEACON (bundled in installer) |
| `.github/workflows/build-installer.yml` | Modify | Full pipeline: ICO + PyInstaller + NSSM + Inno Setup |

---

### Task 1: Copy logo and update branding in installer

**Files:**
- Copy: `repos/website/kytranempowerment-site/logo-sm.png` → `node_client/installer/logo-sm.png`
- Modify: `node_client/installer/archie_node_installer.py` (lines 1-67, 115, 350, 481-503)

- [ ] **Step 1: Copy logo into installer directory**

```bash
cp /mnt/archie_brain/repos/website/kytranempowerment-site/logo-sm.png /mnt/archie_brain/node_client/installer/logo-sm.png
```

- [ ] **Step 2: Update branding strings in archie_node_installer.py**

Replace these strings:

| Line | Old | New |
|------|-----|-----|
| 2 | `A.R.C.H.I.E. Node Setup v3.0 — Windows LCARS GUI Installer` | `A.R.C.H.I.E. Node v4.0 — by Kytran Empowerment` |
| 39 | `INSTALL_DIR = r"C:\archie-node"` | `INSTALL_DIR = r"C:\ARCHIE-Node"` |
| 62 | `LCARS-themed ARCHIE Node installer with 8-step Docker deployment.` | `LCARS-themed A.R.C.H.I.E. Node installer by Kytran Empowerment.` |
| 67 | `self.title("A.R.C.H.I.E. Node Setup")` | `self.title("A.R.C.H.I.E. Node — by Kytran Empowerment")` |
| 115 | `text="A.R.C.H.I.E. Node Setup v3.0"` | `text="A.R.C.H.I.E. Node v4.0"` |
| 481 | `"Existing ARCHIE installation found` | `"Existing A.R.C.H.I.E. Node installation found` |
| 484 | `"An ARCHIE node is already installed` | `"An A.R.C.H.I.E. Node is already installed` |
| 503 | `"A previous ARCHIE node config exists` | `"A previous A.R.C.H.I.E. Node config exists` |

Do NOT change:
- Line 350: `ARCHIE-Node-Resume` registry key (internal, no user visibility)
- Line 842: `DB_PASSWORD=archie_node_default` (functional, not branding)

- [ ] **Step 3: Update .gitignore to exclude build artifacts but include logo**

Add to `node_client/installer/.gitignore`:
```
build/
dist/
*.spec
*.ico
!logo-sm.png
```

- [ ] **Step 4: Commit**

```bash
git add node_client/installer/logo-sm.png node_client/installer/archie_node_installer.py node_client/installer/.gitignore
git commit -m "feat(installer): rebrand to Kytran Empowerment + add logo asset"
```

---

### Task 2: Create Inno Setup script

**Files:**
- Create: `node_client/installer/installer.iss`

- [ ] **Step 1: Create the Inno Setup script**

Create `node_client/installer/installer.iss` with:

```iss
; A.R.C.H.I.E. Node — Inno Setup Installer Script
; Produces ARCHIE-Node-Setup.exe
; Uses NSSM to register BEACON as a Windows Service (tkinter GUI is not a native service binary)

[Setup]
AppId={{7E33E91B-A868-D446-BCDE-ARCHIENODE01}
AppName=A.R.C.H.I.E. Node
AppVersion=4.0.0
AppVerName=A.R.C.H.I.E. Node v4.0.0
AppPublisher=Kytran Empowerment
AppPublisherURL=https://kytranempowerment.com
AppSupportURL=https://kytranempowerment.com
DefaultDirName=C:\ARCHIE-Node
DisableDirPage=yes
DefaultGroupName=Kytran Empowerment
OutputDir=dist
OutputBaseFilename=ARCHIE-Node-Setup
SetupIconFile=archie_icon.ico
UninstallDisplayIcon={app}\archie_icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\ARCHIE-Node.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "nssm.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "archie_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\A.R.C.H.I.E. Node"; Filename: "{app}\ARCHIE-Node.exe"; IconFilename: "{app}\archie_icon.ico"
Name: "{group}\Uninstall A.R.C.H.I.E. Node"; Filename: "{uninstallexe}"
Name: "{commondesktop}\A.R.C.H.I.E. Node"; Filename: "{app}\ARCHIE-Node.exe"; IconFilename: "{app}\archie_icon.ico"

[Run]
; Register BEACON as a Windows Service using NSSM (wraps the GUI exe as a proper service)
Filename: "{app}\nssm.exe"; Parameters: "install ARCHIEBeacon ""{app}\ARCHIE-Node.exe"""; Flags: runhidden waituntilterminated; StatusMsg: "Registering BEACON service..."
Filename: "{app}\nssm.exe"; Parameters: "set ARCHIEBeacon DisplayName ""A.R.C.H.I.E. BEACON"""; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set ARCHIEBeacon Description ""A.R.C.H.I.E. Node fleet agent — connects to Starbase hub"""; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set ARCHIEBeacon Start SERVICE_AUTO_START"; Flags: runhidden waituntilterminated
; Offer to launch the app after install
Filename: "{app}\ARCHIE-Node.exe"; Description: "Launch A.R.C.H.I.E. Node"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop and remove the BEACON service using NSSM
Filename: "{app}\nssm.exe"; Parameters: "stop ARCHIEBeacon"; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "remove ARCHIEBeacon confirm"; Flags: runhidden waituntilterminated
; Stop Docker containers
Filename: "docker"; Parameters: "compose -f ""{app}\docker-compose.yml"" down"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*.json"
Type: filesandordirs; Name: "{app}\.env"
Type: filesandordirs; Name: "{app}\docker-compose.yml"

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Kytran Empowerment\ARCHIE Node"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\Kytran Empowerment\ARCHIE Node"; ValueType: string; ValueName: "Version"; ValueData: "4.0.0"; Flags: uninsdeletekey

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if FileExists('C:\ARCHIE-Node\ARCHIE-Node.exe') then
  begin
    if MsgBox('A.R.C.H.I.E. Node is already installed. Do you want to upgrade?',
              mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
```

- [ ] **Step 2: Commit**

```bash
git add node_client/installer/installer.iss
git commit -m "feat(installer): add Inno Setup script for Windows install wizard"
```

---

### Task 3: Update build script for Inno Setup

**Files:**
- Modify: `node_client/installer/build_installer.py`

- [ ] **Step 1: Make these exact changes to build_installer.py**

**Add `shutil` and `subprocess` imports** at the top (after `import sys`):
```python
import shutil
import subprocess
```

**Change PyInstaller output name** — line 43, change:
```python
"--name=ARCHIE-Node-Setup",
```
to:
```python
"--name=ARCHIE-Node",
```

**Update the exe check** — line 61, change:
```python
exe_path = os.path.join(dist_dir, "ARCHIE-Node-Setup.exe")
```
to:
```python
exe_path = os.path.join(dist_dir, "ARCHIE-Node.exe")
```

**Update print banners** — lines 77-78, change:
```python
print("  A.R.C.H.I.E. Node Installer — Builder")
```
to:
```python
print("  A.R.C.H.I.E. Node — by Kytran Empowerment — Builder")
```

**Do NOT add Inno Setup invocation to this script** — the GitHub Actions workflow handles ISCC separately (avoids double invocation).

- [ ] **Step 2: Commit**

```bash
git add node_client/installer/build_installer.py
git commit -m "feat(installer): add Inno Setup compilation to build script"
```

---

### Task 4: Update GitHub Actions workflow

**Files:**
- Modify: `.github/workflows/build-installer.yml`

- [ ] **Step 1: Rewrite the workflow**

The workflow needs these steps in order:

```yaml
name: Build A.R.C.H.I.E. Node Installer

on:
  workflow_dispatch:
  push:
    paths:
      - 'node_client/installer/**'

jobs:
  build-installer:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install PyInstaller
        run: pip install pyinstaller

      - name: Install ImageMagick
        run: choco install imagemagick -y

      - name: Convert PNG to ICO
        working-directory: node_client/installer
        run: magick logo-sm.png -define icon:auto-resize=256,48,32,16 archie_icon.ico

      - name: Install Inno Setup
        run: choco install innosetup -y

      - name: Download NSSM
        working-directory: node_client/installer
        run: |
          Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile nssm.zip
          Expand-Archive nssm.zip -DestinationPath nssm-temp
          Copy-Item nssm-temp/nssm-2.24/win64/nssm.exe .
          Remove-Item -Recurse nssm-temp, nssm.zip

      - name: Build app with PyInstaller
        working-directory: node_client/installer
        run: python build_installer.py

      - name: Build installer with Inno Setup
        working-directory: node_client/installer
        run: iscc installer.iss

      - name: Upload installer artifact
        uses: actions/upload-artifact@v4
        with:
          name: ARCHIE-Node-Setup
          path: node_client/installer/dist/ARCHIE-Node-Setup.exe
          retention-days: 90

      - name: Create Release (on tag)
        if: startsWith(github.ref, 'refs/tags/')
        uses: softprops/action-gh-release@v2
        with:
          files: node_client/installer/dist/ARCHIE-Node-Setup.exe
```

Key changes from current workflow:
- Added ImageMagick install + PNG→ICO conversion
- Added Inno Setup install (Chocolatey adds `iscc` to PATH)
- Added NSSM download for service wrapper
- PyInstaller output renamed to `ARCHIE-Node.exe` (app binary)
- Inno Setup runs separately (not inside build_installer.py — avoids double invocation)
- Final artifact is `ARCHIE-Node-Setup.exe` (the installer)
- Trigger on any `node_client/installer/**` change (not just 2 files)

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/build-installer.yml
git commit -m "feat(installer): GitHub Actions pipeline with ICO + PyInstaller + Inno Setup"
```

---

### Task 5: Test and verify

- [ ] **Step 1: Trigger the GitHub Actions workflow**

```bash
gh workflow run "Build A.R.C.H.I.E. Node Installer"
```

- [ ] **Step 2: Monitor the workflow run**

```bash
gh run list --workflow=build-installer.yml --limit=1
gh run watch <run-id>
```

Expected: All steps pass, `ARCHIE-Node-Setup.exe` uploaded as artifact.

- [ ] **Step 3: Download and verify the artifact**

```bash
gh run download <run-id> -n ARCHIE-Node-Setup
```

Verify:
- `ARCHIE-Node-Setup.exe` exists and is >5MB (PyInstaller bundle + Inno Setup overhead)
- Transfer to a Windows machine and run to confirm:
  - Install wizard appears with ram logo
  - "A.R.C.H.I.E. Node — by Kytran Empowerment" branding
  - Installs to `C:\ARCHIE-Node\`
  - Creates Start Menu + Desktop shortcuts
  - Shows in Add/Remove Programs
  - Uninstaller works

- [ ] **Step 4: Push changes and commit**

```bash
git push origin main
```

- [ ] **Step 5: Update Dev HQ**

Use MCP tools:
- `complete_task` #1179 with verification notes
- `log_decision` for Inno Setup choice
- `update_project_understanding` for Node Onboarding project

---

## Summary

| Task | Description | Effort |
|------|-------------|--------|
| 1 | Copy logo + rebrand strings | ~5 min |
| 2 | Create Inno Setup script | ~10 min |
| 3 | Update build script | ~5 min |
| 4 | Update GitHub Actions workflow | ~5 min |
| 5 | Test and verify | ~15 min |

**Total: ~40 minutes**
