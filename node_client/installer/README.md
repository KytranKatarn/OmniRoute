# A.R.C.H.I.E. Starship Node Installer

Windows GUI installer that sets up a Starship node with one double-click.

## What it does

1. Checks for Ollama (starts it if not running)
2. Detects hardware (CPU, RAM, GPU)
3. Registers with the ARCHIE hub
4. Downloads `node_sync.py` from the hub
5. Saves config to `%APPDATA%\ARCHIE-Node\config.json`
6. Creates a Windows startup shortcut
7. Launches the node sync service

## Building the .exe

### Prerequisites

- **Windows machine** (10 or 11) with Python 3.8+ installed
- Internet connection (to install PyInstaller)

### Build steps

```cmd
cd node_client\installer
python build_installer.py
```

This will:
1. Install PyInstaller if not present
2. Package everything into a single `ARCHIE-Node-Setup.exe`
3. Output to `dist/ARCHIE-Node-Setup.exe`

### Optional: custom icon

Place `archie_icon.ico` in this folder before building. The build script
will detect and include it automatically.

### Output

```
dist/ARCHIE-Node-Setup.exe    (~8-12 MB standalone executable)
```

## Distribution

Copy `ARCHIE-Node-Setup.exe` to the hub server at:
```
node_client/installer/dist/ARCHIE-Node-Setup.exe
```

The Starship UI will automatically serve this .exe when a user clicks
"Download" for Windows setup. If the .exe is not present, it falls back
to generating a .bat script.

## Development / testing

Run the installer directly with Python (no build needed):

```cmd
python archie_node_installer.py
```

## Architecture

- `archie_node_installer.py` — tkinter GUI app (stdlib only, zero pip deps)
- `build_installer.py` — build script (installs PyInstaller + runs it)
- `dist/` — output directory for the built .exe
- `build/` — PyInstaller work directory (gitignored)

## Hub endpoints used

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `POST /tools/starbase/api/nodes/register` | None (returns api_key) | Register new node |
| `GET /tools/starbase/api/nodes/node_sync.py` | None | Download sync client |
