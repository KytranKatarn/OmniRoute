# A.R.C.H.I.E. Node — Professional Windows Installer

**Date**: 2026-03-22
**Status**: Approved
**Related Tasks**: #1179, #1180, #1189

## Problem

The current installer is a raw PyInstaller `.exe` — a bundled Python script the user double-clicks. It doesn't install to a proper location, doesn't register as a Windows program, has no uninstaller, no Start Menu entry, no service registration, and no icon. This is not how professional Windows software works (Chrome, Adobe, Plex, etc. all use proper install wizards).

## Solution

Wrap the PyInstaller-bundled app inside an **Inno Setup** installer. Inno Setup is free, battle-tested, and produces a single `Setup.exe` that handles the full Windows installation lifecycle.

## User Experience

1. Download `ARCHIE-Node-Setup.exe` from GitHub Releases
2. Double-click — see branded welcome page with ram logo
3. "A.R.C.H.I.E. Node — by Kytran Empowerment" branding throughout
4. Install progress bar — files copied to `C:\ARCHIE-Node\`
5. BEACON registered as a Windows Service (auto-start on boot)
6. Desktop shortcut + Start Menu shortcut created (status dashboard)
7. Entry appears in Add/Remove Programs (ram icon, "Kytran Empowerment" publisher)
8. Finish page with "Launch ARCHIE Node" checkbox

## Architecture

### Build Pipeline (GitHub Actions)

```
logo-sm.png ──→ ImageMagick ──→ archie_icon.ico
                                      │
archie_node_installer.py ──→ PyInstaller ──→ ARCHIE-Node.exe
                                                   │
installer.iss + icon + exe ──→ Inno Setup ──→ ARCHIE-Node-Setup.exe
                                                   │
                                            Upload artifact / Release
```

### Install Layout (`C:\ARCHIE-Node\`)

```
C:\ARCHIE-Node\
├── ARCHIE-Node.exe          # Main app (PyInstaller bundle)
├── archie_icon.ico          # Icon for shortcuts
├── unins000.exe             # Inno Setup auto-generated uninstaller
├── unins000.dat             # Uninstaller data
├── .env                     # Generated during first run (hub registration)
├── docker-compose.yml       # Downloaded from hub during setup
└── resume_after_reboot.json # Reboot recovery state
```

### Windows Integration

| Feature | Implementation |
|---------|---------------|
| Install wizard | Inno Setup `installer.iss` |
| Install location | `C:\ARCHIE-Node\` (no spaces) |
| Start Menu | `Kytran Empowerment\A.R.C.H.I.E. Node` |
| Desktop shortcut | `A.R.C.H.I.E. Node.lnk` → `ARCHIE-Node.exe` |
| Add/Remove Programs | Name: "A.R.C.H.I.E. Node", Publisher: "Kytran Empowerment" |
| Windows Service | BEACON registered via `sc create` or NSSM in post-install |
| Auto-start | Service set to `Automatic` start type |
| Tray icon / status | Desktop shortcut launches status dashboard |
| Uninstall | Inno Setup uninstaller — stops service, removes files, cleans registry |
| Icon | Ram logo (`logo-sm.png` converted to multi-size `.ico`) |

### Branding Updates (in `archie_node_installer.py`)

| Current | New |
|---------|-----|
| `"A.R.C.H.I.E. Node Setup"` (window title) | `"A.R.C.H.I.E. Node — by Kytran Empowerment"` |
| `"LCARS-themed ARCHIE Node installer"` (docstring) | `"LCARS-themed A.R.C.H.I.E. Node installer by Kytran Empowerment"` |
| `ARCHIE-Node-Resume` (registry key) | `ARCHIE-Node-Resume` (keep — internal, no user visibility) |
| `C:\archie-node` (install dir) | `C:\ARCHIE-Node` (capitalization fix) |
| No publisher info | Add "Kytran Empowerment" to About/splash |

### Inno Setup Script (`installer.iss`)

Key configuration:
- `AppName=A.R.C.H.I.E. Node`
- `AppPublisher=Kytran Empowerment`
- `AppPublisherURL=https://kytranempowerment.com`
- `DefaultDirName=C:\ARCHIE-Node` (fixed, not user-choosable — Docker path sensitivity)
- `DefaultGroupName=Kytran Empowerment`
- `SetupIconFile=archie_icon.ico`
- `UninstallDisplayIcon={app}\archie_icon.ico`
- `OutputBaseFilename=ARCHIE-Node-Setup`
- `PrivilegesRequired=admin` (needed for Docker + service registration)
- `WizardStyle=modern`

Post-install `[Run]` section:
- Register BEACON as Windows Service
- Optionally launch the app

Pre-uninstall `[UninstallRun]` section:
- Stop and remove the BEACON service
- Stop Docker containers

### GitHub Actions Workflow Updates

```yaml
# Added steps:
- Install ImageMagick (convert PNG → ICO)
- Install Inno Setup (iscc compiler)
- Convert logo-sm.png → archie_icon.ico (16,32,48,256 sizes)
- Run PyInstaller → ARCHIE-Node.exe
- Run Inno Setup → ARCHIE-Node-Setup.exe
- Upload ARCHIE-Node-Setup.exe as artifact
- Create release on tag push
```

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `node_client/installer/installer.iss` | **Create** | Inno Setup script |
| `node_client/installer/logo-sm.png` | **Copy** | Logo source for icon conversion |
| `node_client/installer/archie_node_installer.py` | **Modify** | Branding updates |
| `node_client/installer/build_installer.py` | **Modify** | Add Inno Setup compilation step |
| `.github/workflows/build-installer.yml` | **Modify** | Add ImageMagick + Inno Setup steps |

## Out of Scope

- Custom installer UI theming (Inno Setup `modern` style is sufficient)
- Silent install mode (can add later with `/SILENT` flag — Inno Setup supports it natively)
- Auto-update mechanism (OTA handles this separately)
- macOS/Linux installers (shell scripts already work)
- License agreement page (skip for now, add if needed later)

## Success Criteria

1. `ARCHIE-Node-Setup.exe` produced by GitHub Actions on every push to installer files
2. Install wizard shows ram logo and Kytran Empowerment branding
3. App installs to `C:\ARCHIE-Node\` with proper shortcuts
4. BEACON runs as a Windows Service on boot
5. Shows in Add/Remove Programs with correct name, publisher, icon
6. Uninstaller cleanly removes everything (service, files, shortcuts, registry)
7. Tagged releases auto-publish the installer as a GitHub Release asset
