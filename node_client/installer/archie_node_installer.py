"""
A.R.C.H.I.E. Node v4.0 — by Kytran Empowerment

A standalone tkinter installer that deploys a full Docker container stack:
1. Prerequisites check (admin, internet, existing install)
2. Hardware detection (CPU, RAM, GPU, disk)
3. Docker setup (install/start Docker Desktop, check native Ollama)
4. Register with hub
5. Download stack files (docker-compose, node_sync, node_api, etc.)
6. Build & start containers
7. Wait for hub approval
8. Verify deployment

No external dependencies — uses only Python stdlib.
Package with PyInstaller for a single .exe distribution.
"""

import ctypes
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont, messagebox
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# winreg is stdlib on Windows only
if platform.system() == "Windows":
    import winreg

# ── Constants ─────────────────────────────────────────────────────────────────
CLIENT_VERSION = "4.0.0"
INSTALL_DIR = r"C:\ARCHIE-Node"
RESUME_FILE = os.path.join(INSTALL_DIR, "resume_after_reboot.json")
ENV_FILE = os.path.join(INSTALL_DIR, ".env")
TOTAL_STEPS = 11

# ── LCARS Colour Palette ─────────────────────────────────────────────────────
BG_DARK = "#0a0a12"
BG_PANEL = "#12121f"
BG_INPUT = "#1e293b"
CYAN = "#00e5ff"
ORANGE = "#f97316"
GREEN = "#10b981"
RED = "#ef4444"
YELLOW = "#fbbf24"
TEXT_PRIMARY = "#e0e0e0"
TEXT_DIM = "#666680"
BORDER = "#1e3a5f"

# ── Font Helper ───────────────────────────────────────────────────────────────
FONT_MONO = "Consolas"

# ── Docker Compose Template (pull-only, zero build, zero bind mounts) ─────────
_COMPOSE_TEMPLATE = """\
services:
  ollama:
    image: ollama/ollama:latest
    container_name: archie_node_ollama
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    environment:
      - OLLAMA_KEEP_ALIVE=5m
      - OLLAMA_NUM_PARALLEL=4
      - NVIDIA_VISIBLE_DEVICES=all
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "${OLLAMA_PORT:-11434}:11434"
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - archie_net

  postgres:
    image: postgres:16-alpine
    container_name: archie_node_db
    restart: unless-stopped
    environment:
      POSTGRES_USER: archie_node
      POSTGRES_PASSWORD: ${DB_PASSWORD:-archie_node_default}
      POSTGRES_DB: archie_node
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U archie_node"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - archie_net

  sync:
    image: ghcr.io/kytrankatarn/archie-node:latest
    container_name: archie_node_sync
    restart: unless-stopped
    depends_on:
      ollama:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      NODE_ID: ${NODE_ID}
      HUB_URL: ${HUB_URL}
      HUB_API_KEY: ${HUB_API_KEY}
      OLLAMA_HOST: http://ollama:11434
      DATABASE_URL: postgresql://archie_node:${DB_PASSWORD:-archie_node_default}@postgres:5432/archie_node
      HEARTBEAT_INTERVAL: "30"
      SYNC_POLL_INTERVAL: "60"
      DEPLOYMENT_MODE: "starship"
      COMFYUI_PORT: "${COMFYUI_PORT:-8188}"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - comfyui_data:/comfyui/models
    command: ["python3", "-u", "node_sync.py"]
    healthcheck:
      test: ["CMD-SHELL", "pgrep -f node_sync.py || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - archie_net

  node_api:
    image: ghcr.io/kytrankatarn/archie-node:latest
    container_name: archie_node_api
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://archie_node:${DB_PASSWORD:-archie_node_default}@postgres:5432/archie_node
      OLLAMA_HOST: http://ollama:11434
      NODE_ID: ${NODE_ID}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: ["python3", "-u", "node_api.py"]
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:3001/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
    ports:
      - "${NODE_API_PORT:-3001}:3001"
    networks:
      - archie_net

  comfyui:
    image: comfyui/base:latest
    container_name: archie_node_comfyui
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    volumes:
      - comfyui_data:/comfyui/models
    ports:
      - "${COMFYUI_PORT:-8188}:8188"
    networks:
      - archie_net

volumes:
  ollama_data:
  pg_data:
  comfyui_data:

networks:
  archie_net:
    driver: bridge
"""

_HELPER_SCRIPTS = {
    "start.bat": "@echo off\necho Starting A.R.C.H.I.E. Node...\ndocker compose up -d\necho.\necho Node started! You can close this window.\npause\n",
    "stop.bat": "@echo off\necho Stopping A.R.C.H.I.E. Node...\ndocker compose down\necho.\necho Node stopped.\npause\n",
    "update.bat": "@echo off\necho Updating A.R.C.H.I.E. Node...\ndocker compose pull\ndocker compose up -d\necho.\necho Node updated!\npause\n",
}


class ArchieInstaller(tk.Tk):
    """LCARS-themed A.R.C.H.I.E. Node installer by Kytran Empowerment."""

    def __init__(self):
        super().__init__()

        self.title("A.R.C.H.I.E. Node — by Kytran Empowerment")
        self.geometry("700x500")
        self.resizable(False, False)
        self.configure(bg=BG_DARK)

        # State
        self.hub_url = ""
        self.node_id = None
        self.api_key = None
        self.headscale_authkey = None
        self.headscale_url = None
        self.mesh_ip = None
        self.current_step = 0
        self.hw_info = {}
        self._cancel_flag = False
        self._install_thread = None

        # Try to set icon if bundled
        icon_path = self._resource_path("archie_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Check for resume state on launch
        self.after(300, self._check_resume_on_start)

    # ── Resource helper (PyInstaller compat) ──────────────────────────────────
    @staticmethod
    def _resource_path(relative_path):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, relative_path)

    # ── UI Construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        # Top accent bar
        tk.Frame(self, bg=CYAN, height=3).pack(fill="x")

        # Header
        header = tk.Frame(self, bg=BG_DARK, pady=10)
        header.pack(fill="x", padx=20)

        title_font = tkfont.Font(family=FONT_MONO, size=16, weight="bold")
        tk.Label(
            header, text="A.R.C.H.I.E. Node v4.0",
            font=title_font, fg=CYAN, bg=BG_DARK, anchor="w",
        ).pack(fill="x")

        # Separator under title
        tk.Frame(header, bg=CYAN, height=2).pack(fill="x", pady=(4, 0))

        # ── Hub URL input ─────────────────────────────────────────────────
        url_frame = tk.Frame(self, bg=BG_DARK)
        url_frame.pack(fill="x", padx=20, pady=(8, 4))

        lbl_font = tkfont.Font(family=FONT_MONO, size=9)
        tk.Label(
            url_frame, text="Hub URL:", font=lbl_font,
            fg=TEXT_DIM, bg=BG_DARK, anchor="w",
        ).pack(side="left")

        self.hub_url_var = tk.StringVar(value="https://platform.kytranempowerment.com")
        entry_font = tkfont.Font(family=FONT_MONO, size=10)
        self.hub_entry = tk.Entry(
            url_frame, textvariable=self.hub_url_var, font=entry_font,
            bg=BG_INPUT, fg=TEXT_PRIMARY, insertbackground=CYAN,
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=CYAN,
        )
        self.hub_entry.pack(side="left", fill="x", expand=True, padx=(8, 0), ipady=4)

        # ── Hardware Panel ────────────────────────────────────────────────
        hw_outer = tk.LabelFrame(
            self, text=" Hardware ", font=tkfont.Font(family=FONT_MONO, size=9),
            fg=CYAN, bg=BG_PANEL, labelanchor="nw",
            highlightbackground=BORDER, highlightthickness=1,
            bd=0, padx=8, pady=6,
        )
        hw_outer.pack(fill="x", padx=20, pady=(8, 4))

        hw_grid = tk.Frame(hw_outer, bg=BG_PANEL)
        hw_grid.pack(fill="x")

        hw_lbl_font = tkfont.Font(family=FONT_MONO, size=9)
        hw_val_font = tkfont.Font(family=FONT_MONO, size=9)

        self.hw_labels = {}
        hw_items = [
            ("CPU", 0, 0), ("RAM", 0, 2),
            ("GPU", 1, 0), ("Disk", 1, 2),
        ]
        for name, row, col in hw_items:
            tk.Label(
                hw_grid, text=f"{name}:", font=hw_lbl_font,
                fg=TEXT_DIM, bg=BG_PANEL, anchor="w",
            ).grid(row=row, column=col, sticky="w", padx=(0, 4), pady=1)
            lbl = tk.Label(
                hw_grid, text="(detecting...)", font=hw_val_font,
                fg=TEXT_PRIMARY, bg=BG_PANEL, anchor="w",
            )
            lbl.grid(row=row, column=col + 1, sticky="w", padx=(0, 20), pady=1)
            self.hw_labels[name] = lbl

        hw_grid.columnconfigure(1, weight=1)
        hw_grid.columnconfigure(3, weight=1)

        # ── Progress Bar ──────────────────────────────────────────────────
        prog_frame = tk.Frame(self, bg=BG_DARK)
        prog_frame.pack(fill="x", padx=20, pady=(8, 2))

        self.progress_canvas = tk.Canvas(
            prog_frame, height=16, bg=BG_PANEL, highlightthickness=0, bd=0,
        )
        self.progress_canvas.pack(fill="x")

        self.step_label = tk.Label(
            self, text="Ready to install", font=tkfont.Font(family=FONT_MONO, size=9),
            fg=TEXT_DIM, bg=BG_DARK, anchor="w",
        )
        self.step_label.pack(fill="x", padx=20)

        # ── Log Panel ────────────────────────────────────────────────────
        log_outer = tk.LabelFrame(
            self, text=" Log ", font=tkfont.Font(family=FONT_MONO, size=9),
            fg=CYAN, bg=BG_PANEL, labelanchor="nw",
            highlightbackground=BORDER, highlightthickness=1,
            bd=0, padx=4, pady=4,
        )
        log_outer.pack(fill="both", expand=True, padx=20, pady=(4, 8))

        log_font = tkfont.Font(family=FONT_MONO, size=8)
        self.log_text = tk.Text(
            log_outer, bg=BG_PANEL, fg=TEXT_DIM, font=log_font,
            relief="flat", bd=0, wrap="word", state="disabled", cursor="arrow",
        )
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

        self.log_text.tag_configure("info", foreground=TEXT_DIM)
        self.log_text.tag_configure("ok", foreground=GREEN)
        self.log_text.tag_configure("warn", foreground=ORANGE)
        self.log_text.tag_configure("error", foreground=RED)
        self.log_text.tag_configure("cyan", foreground=CYAN)
        self.log_text.tag_configure("yellow", foreground=YELLOW)

        # ── Button Row ───────────────────────────────────────────────────
        btn_frame = tk.Frame(self, bg=BG_DARK)
        btn_frame.pack(fill="x", padx=20, pady=(0, 10))

        btn_font = tkfont.Font(family=FONT_MONO, size=11, weight="bold")

        self.install_btn = tk.Button(
            btn_frame, text="Install", font=btn_font,
            bg=CYAN, fg=BG_DARK, activebackground="#00b8d4",
            activeforeground=BG_DARK, relief="flat", bd=0,
            cursor="hand2", command=self._start_install, padx=24, pady=6,
        )
        self.install_btn.pack(side="right", padx=(8, 0))

        self.cancel_btn = tk.Button(
            btn_frame, text="Cancel", font=btn_font,
            bg=BG_INPUT, fg=TEXT_PRIMARY, activebackground=BORDER,
            activeforeground=TEXT_PRIMARY, relief="flat", bd=0,
            cursor="hand2", command=self._on_cancel, padx=24, pady=6,
        )
        self.cancel_btn.pack(side="right")

        # Bottom accent bar
        tk.Frame(self, bg=CYAN, height=3).pack(fill="x", side="bottom")

    # ── Logging ───────────────────────────────────────────────────────────────
    def _log(self, message, tag="info"):
        """Append message to log panel. Thread-safe via self.after()."""
        def _do():
            self.log_text.configure(state="normal")
            prefixes = {
                "ok": "[OK] ", "error": "[!!] ", "warn": "[!] ",
                "cyan": ">> ", "yellow": "[~] ",
            }
            prefix = prefixes.get(tag, "    ")
            self.log_text.insert("end", f"{prefix}{message}\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _do)

    def _update_progress(self, step, description):
        """Update progress bar and step label. Thread-safe."""
        self.current_step = step

        def _do():
            self.step_label.configure(text=f"Step {step}/{TOTAL_STEPS}  {description}")
            # Redraw progress bar
            c = self.progress_canvas
            c.delete("all")
            w = c.winfo_width() or 660
            h = 16
            # Background
            c.create_rectangle(0, 0, w, h, fill=BG_INPUT, outline="")
            # Filled portion
            fill_w = int(w * step / TOTAL_STEPS)
            if fill_w > 0:
                c.create_rectangle(0, 0, fill_w, h, fill=CYAN, outline="")
        self.after(0, _do)

    def _update_hw_label(self, key, value):
        """Update a hardware panel label. Thread-safe."""
        def _do():
            if key in self.hw_labels:
                self.hw_labels[key].configure(text=value)
        self.after(0, _do)

    def _set_install_btn(self, text, command, bg=CYAN):
        """Change install button state. Thread-safe."""
        def _do():
            self.install_btn.configure(text=text, command=command, bg=bg, state="normal")
        self.after(0, _do)

    def _disable_inputs(self):
        def _do():
            self.install_btn.configure(state="disabled", bg=BG_INPUT, fg=TEXT_DIM)
            self.hub_entry.configure(state="disabled")
        self.after(0, _do)

    def _enable_inputs(self):
        def _do():
            self.install_btn.configure(state="normal", bg=CYAN, fg=BG_DARK)
            self.hub_entry.configure(state="normal")
        self.after(0, _do)

    # ── Network helpers ───────────────────────────────────────────────────────
    def _http_get(self, url, timeout=30):
        """GET request, returns bytes."""
        req = Request(url, method="GET")
        resp = urlopen(req, timeout=timeout)
        return resp.read()

    def _http_post_json(self, url, data, timeout=30):
        """POST JSON, returns parsed dict."""
        body = json.dumps(data).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        resp = urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))

    def _download_file(self, url, dest_path, timeout=120):
        """Download file from URL to local path."""
        req = Request(url, method="GET")
        resp = urlopen(req, timeout=timeout)
        content = resp.read()
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(content)
        return len(content)

    # ── Resume handling ───────────────────────────────────────────────────────
    def _save_resume_state(self, step, data=None):
        """Save state so installer can resume after reboot."""
        os.makedirs(INSTALL_DIR, exist_ok=True)
        state = {"step": step, "hub_url": self.hub_url}
        if data:
            state.update(data)
        if self.node_id:
            state["node_id"] = self.node_id
        if self.api_key:
            state["api_key"] = self.api_key
        with open(RESUME_FILE, "w") as f:
            json.dump(state, f, indent=2)

        # Add RunOnce registry key (Windows only)
        if platform.system() == "Windows":
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
                    0, winreg.KEY_SET_VALUE,
                )
                if getattr(sys, "frozen", False):
                    exe_path = sys.executable
                else:
                    exe_path = f'pythonw "{os.path.abspath(__file__)}"'
                winreg.SetValueEx(key, "ARCHIE-Node-Resume", 0, winreg.REG_SZ, exe_path)
                winreg.CloseKey(key)
            except Exception:
                pass

    def _check_resume(self):
        """Check for saved resume state."""
        if os.path.exists(RESUME_FILE):
            try:
                with open(RESUME_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _clear_resume(self):
        """Remove resume file."""
        try:
            if os.path.exists(RESUME_FILE):
                os.remove(RESUME_FILE)
        except Exception:
            pass

    def _check_resume_on_start(self):
        """Called after UI loads to check for resume state."""
        resume = self._check_resume()
        if resume:
            step = resume.get("step", 0)
            hub = resume.get("hub_url", "")
            answer = messagebox.askyesno(
                "Resume Installation",
                f"A previous installation was interrupted at step {step}.\n"
                f"Hub: {hub}\n\nResume where you left off?",
            )
            if answer:
                self.hub_url = hub
                self.hub_url_var.set(hub)
                self.node_id = resume.get("node_id")
                self.api_key = resume.get("api_key")
                self._clear_resume()
                self._start_install(resume_from=step)
            else:
                self._clear_resume()

    # ── Install flow ──────────────────────────────────────────────────────────
    def _start_install(self, resume_from=0):
        """Begin installation in a background thread."""
        self._cancel_flag = False
        self._disable_inputs()
        self.hub_url = self.hub_url_var.get().strip().rstrip("/")
        if not self.hub_url:
            self._log("Please enter a Hub URL.", "error")
            self._enable_inputs()
            return
        self._install_thread = threading.Thread(
            target=self._run_install, args=(resume_from,), daemon=True,
        )
        self._install_thread.start()

    def _run_install(self, resume_from=0):
        """Execute all 8 install steps. Runs in background thread."""
        try:
            steps = [
                (1, "Checking prerequisites...", self._step_prerequisites),
                (2, "Configuring firewall...", self._step_firewall),
                (3, "Detecting hardware...", self._step_hardware),
                (4, "Setting up Docker...", self._step_docker),
                (5, "Registering with hub...", self._step_register),
                (6, "Setting up mesh VPN...", self._step_tailscale),
                (7, "Downloading stack files...", self._step_download),
                (8, "Building & starting containers...", self._step_build),
                (9, "Waiting for approval...", self._step_approval),
                (10, "Downloading AI models...", self._step_checkpoints),
                (11, "Verifying deployment...", self._step_verify),
            ]

            for step_num, desc, func in steps:
                if self._cancel_flag:
                    self._log("Installation cancelled.", "warn")
                    self._enable_inputs()
                    return
                if step_num < resume_from:
                    continue
                self._update_progress(step_num, desc)
                self._log(desc, "cyan")
                func()

        except _StepError as e:
            self._log(str(e), "error")
            self._enable_inputs()
        except Exception as e:
            self._log(f"Unexpected error: {e}", "error")
            self._enable_inputs()

    # ── Step 1: Prerequisites ─────────────────────────────────────────────────
    def _step_prerequisites(self):
        # Check admin
        if platform.system() == "Windows":
            try:
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
            except Exception:
                is_admin = False
            if not is_admin:
                self._log("Not running as Administrator.", "warn")
                self._log("Some features may require elevation.", "warn")
            else:
                self._log("Running as Administrator", "ok")
        else:
            if os.geteuid() == 0:
                self._log("Running as root", "ok")
            else:
                self._log("Not running as root — some steps may need sudo", "warn")

        # Check internet
        try:
            self._http_get(self.hub_url, timeout=10)
            self._log(f"Hub reachable: {self.hub_url}", "ok")
        except Exception as e:
            raise _StepError(f"Cannot reach hub at {self.hub_url}: {e}")

        # Check existing installation
        if os.path.exists(ENV_FILE):
            containers_running = False
            try:
                result = subprocess.run(
                    ["docker", "compose", "ps", "-q"],
                    cwd=INSTALL_DIR, capture_output=True, timeout=15,
                )
                containers_running = bool(result.stdout.strip())
            except Exception:
                pass

            if containers_running:
                self._log("Existing A.R.C.H.I.E. Node installation found (containers running).", "yellow")
                answer = self._ask_choice(
                    "Existing Installation",
                    "An A.R.C.H.I.E. Node is already installed and running.\n\n"
                    "Choose an option:",
                    ["Upgrade", "Fresh Install", "Cancel"],
                )
                if answer == "Cancel" or answer is None:
                    raise _StepError("Installation cancelled by user.")
                elif answer == "Fresh Install":
                    self._log("Stopping existing containers...", "cyan")
                    subprocess.run(
                        ["docker", "compose", "down", "--remove-orphans"],
                        cwd=INSTALL_DIR, capture_output=True, timeout=60,
                    )
                    self._log("Existing containers stopped.", "ok")
                else:
                    self._log("Upgrading existing installation...", "cyan")
            else:
                self._log("Existing config found (not running).", "yellow")
                answer = self._ask_choice(
                    "Existing Config Found",
                    "A previous A.R.C.H.I.E. Node config exists but containers are not running.\n\n"
                    "Choose an option:",
                    ["Resume", "Fresh Install", "Cancel"],
                )
                if answer == "Cancel" or answer is None:
                    raise _StepError("Installation cancelled by user.")
                elif answer == "Fresh Install":
                    self._log("Starting fresh installation...", "cyan")
                else:
                    self._log("Resuming previous installation...", "cyan")
                    # Load existing config
                    try:
                        with open(ENV_FILE) as f:
                            for line in f:
                                line = line.strip()
                                if line.startswith("NODE_ID="):
                                    self.node_id = line.split("=", 1)[1]
                                elif line.startswith("HUB_API_KEY="):
                                    self.api_key = line.split("=", 1)[1]
                    except Exception:
                        pass
        else:
            self._log("No existing installation found.", "ok")

    # ── Step 2: Firewall Configuration ───────────────────────────────────────
    def _step_firewall(self):
        """Open required ports in Windows Firewall for ARCHIE services."""
        if platform.system() != "Windows":
            self._log("Not Windows — skipping firewall config.", "ok")
            return

        rules = [
            ("ARCHIE BEACON", "3001", "TCP"),
            ("ARCHIE ComfyUI", "8188", "TCP"),
            ("ARCHIE Ollama", "11434", "TCP"),
            ("Allow ICMPv4-In", None, "ICMPv4"),
        ]

        for name, port, proto in rules:
            try:
                # Check if rule already exists
                check = subprocess.run(
                    ["powershell", "-Command",
                     f'Get-NetFirewallRule -DisplayName "{name}" -ErrorAction SilentlyContinue'],
                    capture_output=True, text=True, timeout=10,
                )
                if name in (check.stdout or ""):
                    self._log(f"Firewall rule '{name}' already exists.", "ok")
                    continue

                # Create the rule
                if proto == "ICMPv4":
                    cmd = (f'New-NetFirewallRule -DisplayName "{name}" '
                           f'-Protocol ICMPv4 -IcmpType 8 '
                           f'-Direction Inbound -Action Allow -Profile Any')
                else:
                    cmd = (f'New-NetFirewallRule -DisplayName "{name}" '
                           f'-Direction Inbound -LocalPort {port} '
                           f'-Protocol {proto} -Action Allow -Profile Any')

                result = subprocess.run(
                    ["powershell", "-Command", cmd],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0:
                    self._log(f"Firewall rule '{name}' added.", "ok")
                else:
                    self._log(f"Firewall rule '{name}' — needs admin elevation.", "warn")
            except Exception as e:
                self._log(f"Firewall rule '{name}' skipped: {e}", "warn")

    # ── Step 3: Hardware Detection ────────────────────────────────────────────
    def _step_hardware(self):
        hw = self.hw_info

        # CPU
        cpu_name = "Unknown"
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["wmic", "cpu", "get", "name"],
                    capture_output=True, text=True, timeout=10,
                )
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip() and l.strip() != "Name"]
                if lines:
                    cpu_name = lines[0]
            except Exception:
                cpu_name = platform.processor() or "Unknown"
        else:
            cpu_name = platform.processor() or "Unknown"
        hw["cpu_model"] = cpu_name
        hw["cpu_cores"] = os.cpu_count() or 1
        # Truncate long CPU names for display
        display_cpu = cpu_name[:30] + "..." if len(cpu_name) > 33 else cpu_name
        self._update_hw_label("CPU", f"{display_cpu} ({hw['cpu_cores']}c)")
        self._log(f"CPU: {cpu_name} ({hw['cpu_cores']} cores)", "ok")

        # RAM
        ram_gb = 0
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["wmic", "computersystem", "get", "totalphysicalmemory"],
                    capture_output=True, text=True, timeout=10,
                )
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip() and l.strip().isdigit()]
                if lines:
                    ram_gb = round(int(lines[0]) / (1024 ** 3), 1)
            except Exception:
                pass
        else:
            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal"):
                            ram_gb = round(int(line.split()[1]) / (1024 * 1024), 1)
                            break
            except Exception:
                pass
        hw["ram_gb"] = ram_gb
        self._update_hw_label("RAM", f"{ram_gb} GB")
        self._log(f"RAM: {ram_gb} GB", "ok")

        # GPU
        gpu_model = None
        gpu_vram_gb = None
        gpu_available = False
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["wmic", "path", "win32_videocontroller", "get", "name,adapterram"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.strip().split("\n")[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    # adapterram is first numeric field, name is the rest
                    parts = line.split()
                    if parts:
                        # Try to find NVIDIA
                        full_line = " ".join(parts)
                        if "NVIDIA" in full_line.upper():
                            gpu_available = True
                            # Parse adapter RAM (bytes) and name
                            # Format: "AdapterRAM  Name" — numbers first
                            ram_bytes = 0
                            name_parts = []
                            for p in parts:
                                if p.isdigit() and not name_parts:
                                    ram_bytes = int(p)
                                else:
                                    name_parts.append(p)
                            gpu_model = " ".join(name_parts) if name_parts else full_line
                            if ram_bytes > 0:
                                gpu_vram_gb = round(ram_bytes / (1024 ** 3), 1)
            except Exception:
                pass
        hw["gpu_available"] = gpu_available
        hw["gpu_model"] = gpu_model
        hw["gpu_vram_gb"] = gpu_vram_gb
        if gpu_available:
            vram_str = f" ({gpu_vram_gb}GB)" if gpu_vram_gb else ""
            self._update_hw_label("GPU", f"{gpu_model}{vram_str}")
            self._log(f"GPU: {gpu_model}{vram_str}", "ok")
        else:
            self._update_hw_label("GPU", "None detected")
            self._log("GPU: No NVIDIA GPU detected (CPU-only mode)", "yellow")

        # Disk
        try:
            usage = shutil.disk_usage("C:\\" if platform.system() == "Windows" else "/")
            disk_free_gb = round(usage.free / (1024 ** 3), 1)
            disk_total_gb = round(usage.total / (1024 ** 3), 1)
        except Exception:
            disk_free_gb = 0
            disk_total_gb = 0
        hw["disk_free_gb"] = disk_free_gb
        hw["disk_total_gb"] = disk_total_gb
        self._update_hw_label("Disk", f"{disk_free_gb} GB free / {disk_total_gb} GB")
        self._log(f"Disk: {disk_free_gb} GB free of {disk_total_gb} GB", "ok")

        # OS
        hw["os_info"] = f"{platform.system()} {platform.release()} {platform.machine()}"
        hw["hostname"] = socket.gethostname()

    # ── Step 3: Docker Setup ──────────────────────────────────────────────────
    def _step_docker(self):
        docker_ok = self._check_docker()

        if not docker_ok:
            self._log("Docker not found. Installing Docker Desktop...", "warn")
            self._install_docker()
            docker_ok = self._check_docker()
            if not docker_ok:
                # Docker installed but needs restart
                self._log("Docker installed. A system restart may be required.", "yellow")
                self._save_resume_state(3, {"needs_docker_start": True})
                answer = self._ask_choice(
                    "Restart Required",
                    "Docker Desktop has been installed but requires a system restart.\n\n"
                    "The installer will resume automatically after reboot.",
                    ["Restart Now", "I'll restart later"],
                )
                if answer == "Restart Now":
                    self._log("Restarting system...", "cyan")
                    subprocess.run(["shutdown", "/r", "/t", "5"], capture_output=True)
                raise _StepError("Please restart your computer and run the installer again.")

        # Docker found — check if running
        if not self._docker_running():
            self._log("Docker Desktop not running. Starting...", "yellow")
            self._start_docker_desktop()
            # Poll for up to 90s
            for i in range(18):
                if self._cancel_flag:
                    return
                time.sleep(5)
                if self._docker_running():
                    break
                self._log(f"Waiting for Docker... ({(i + 1) * 5}s)", "info")
            if not self._docker_running():
                raise _StepError("Docker Desktop did not start within 90 seconds. Please start it manually.")

        self._log("Docker Desktop is running.", "ok")

        # Check for native Ollama on port 11434
        self._check_native_ollama()

    def _check_docker(self):
        """Check if docker CLI exists."""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _docker_running(self):
        """Check if Docker daemon is responsive."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _install_docker(self):
        """Download and install Docker Desktop silently."""
        installer_url = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
        installer_path = os.path.join(INSTALL_DIR, "DockerDesktopInstaller.exe")

        self._log("Downloading Docker Desktop installer...", "cyan")
        os.makedirs(INSTALL_DIR, exist_ok=True)
        try:
            self._download_file(installer_url, installer_path, timeout=300)
            self._log("Docker Desktop downloaded.", "ok")
        except Exception as e:
            raise _StepError(f"Failed to download Docker Desktop: {e}")

        self._log("Installing Docker Desktop (this may take several minutes)...", "cyan")
        try:
            result = subprocess.run(
                [installer_path, "install", "--quiet", "--accept-license"],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                self._log(f"Docker installer output: {result.stderr[:200]}", "warn")
        except subprocess.TimeoutExpired:
            self._log("Docker install is taking a long time. It may still be running.", "warn")
        except Exception as e:
            raise _StepError(f"Docker install failed: {e}")

        # Refresh PATH
        if platform.system() == "Windows":
            docker_paths = [
                os.path.join(os.environ.get("PROGRAMFILES", ""), "Docker", "Docker", "resources", "bin"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Docker", "Docker", "resources", "bin"),
            ]
            for dp in docker_paths:
                if os.path.isdir(dp) and dp not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = dp + os.pathsep + os.environ.get("PATH", "")

        # Clean up installer
        try:
            os.remove(installer_path)
        except Exception:
            pass

    def _start_docker_desktop(self):
        """Attempt to start Docker Desktop."""
        if platform.system() != "Windows":
            return
        docker_desktop_paths = [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Docker", "Docker", "Docker Desktop.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Docker", "Docker", "Docker Desktop.exe"),
        ]
        for path in docker_desktop_paths:
            if os.path.isfile(path):
                try:
                    subprocess.Popen(
                        [path],
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._log(f"Started Docker Desktop: {path}", "ok")
                    return
                except Exception:
                    continue
        self._log("Could not find Docker Desktop executable to start.", "warn")

    def _check_native_ollama(self):
        """Check for native Ollama running on port 11434."""
        try:
            resp = urlopen("http://localhost:11434/api/tags", timeout=3)
            if resp.status == 200:
                self._log("Native Ollama detected on port 11434.", "warn")
                self._log("The Docker stack includes its own Ollama container.", "warn")
                self._log("Consider stopping native Ollama to avoid port conflicts.", "warn")
        except Exception:
            pass  # Not running, that's fine

    # ── Step 4: Register with Hub ─────────────────────────────────────────────
    def _step_register(self):
        if self.node_id and self.api_key:
            self._log(f"Already registered as node {self.node_id}. Skipping.", "ok")
            return

        hw = self.hw_info
        local_ip = self._get_local_ip()
        register_url = f"{self.hub_url}/tools/starbase/api/nodes/register"

        payload = {
            "node_name": hw.get("hostname", socket.gethostname()),
            "hostname": local_ip,
            "port": 11434,
            "gpu_available": hw.get("gpu_available", False),
            "gpu_model": hw.get("gpu_model"),
            "gpu_vram_gb": hw.get("gpu_vram_gb"),
            "cpu_cores": hw.get("cpu_cores", os.cpu_count() or 1),
            "cpu_model": hw.get("cpu_model", "Unknown"),
            "ram_gb": hw.get("ram_gb", 0),
            "disk_gb": hw.get("disk_free_gb", 0),
            "os_info": hw.get("os_info", platform.platform()),
            "client_version": CLIENT_VERSION,
            "tags": ["windows"],
        }

        try:
            result = self._http_post_json(register_url, payload)
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            raise _StepError(f"Registration failed (HTTP {e.code}): {body}")
        except URLError as e:
            raise _StepError(f"Cannot reach hub: {e.reason}")
        except Exception as e:
            raise _StepError(f"Registration error: {e}")

        if not result.get("success"):
            raise _StepError(f"Registration rejected: {result.get('error', 'Unknown')}")

        self.node_id = result.get("node_id", "unknown")
        self.api_key = result.get("api_key", "")
        self.headscale_authkey = result.get("headscale_authkey")
        self.headscale_url = result.get("headscale_url")

        self._log(f"Registered as node: {self.node_id}", "ok")
        if self.headscale_authkey:
            self._log("Mesh VPN auth key received", "ok")

        # Save .env file
        os.makedirs(INSTALL_DIR, exist_ok=True)
        env_content = (
            f"NODE_ID={self.node_id}\n"
            f"NODE_NAME={self.hw_info.get('hostname', socket.gethostname())}\n"
            f"HUB_URL={self.hub_url}\n"
            f"HUB_API_KEY={self.api_key}\n"
            f"DB_PASSWORD=archie_node_default\n"
            f"OLLAMA_PORT=11434\n"
            f"NODE_API_PORT=3001\n"
            f"COMFYUI_PORT=8188\n"
            f"HEADSCALE_URL={self.headscale_url or ''}\n"
            f"HEADSCALE_AUTHKEY={self.headscale_authkey or ''}\n"
        )
        with open(ENV_FILE, "w") as f:
            f.write(env_content)
        self._log(f"Config saved to {ENV_FILE}", "ok")

    def _get_local_ip(self):
        """Get local IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # ── Step 5: Tailscale Mesh VPN ───────────────────────────────────────────
    def _step_tailscale(self):
        if not self.headscale_authkey:
            self._log("No mesh auth key — skipping VPN setup (LAN only)", "warn")
            return

        # Check if Tailscale is already installed
        tailscale_exe = None
        for path in [
            r"C:\Program Files\Tailscale\tailscale.exe",
            r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        ]:
            if os.path.exists(path):
                tailscale_exe = path
                break

        if not tailscale_exe:
            try:
                result = subprocess.run(
                    ["where", "tailscale"], capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    tailscale_exe = result.stdout.strip().split("\n")[0]
            except Exception:
                pass

        if not tailscale_exe:
            self._log("Installing Tailscale...", "info")
            try:
                msi_url = "https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi"
                msi_path = os.path.join(os.environ.get("TEMP", INSTALL_DIR), "tailscale-setup.msi")
                self._download_file(msi_url, msi_path)
                self._log("Running Tailscale installer...", "info")
                subprocess.run(
                    ["msiexec", "/i", msi_path, "/qn"],
                    timeout=120, check=True,
                )
                time.sleep(5)
                # Find the installed exe
                for path in [
                    r"C:\Program Files\Tailscale\tailscale.exe",
                    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
                ]:
                    if os.path.exists(path):
                        tailscale_exe = path
                        break
                if tailscale_exe:
                    self._log("Tailscale installed", "ok")
                else:
                    self._log("Tailscale installed but exe not found in expected path", "warn")
                    return
            except Exception as e:
                self._log(f"Tailscale install failed: {e}", "warn")
                self._log("Install manually from https://tailscale.com/download/windows", "info")
                return
        else:
            self._log(f"Tailscale found: {tailscale_exe}", "ok")

        # Join the mesh
        self._log(f"Joining mesh at {self.headscale_url}...", "info")
        try:
            node_name = self.hw_info.get("hostname", socket.gethostname())
            subprocess.run(
                [
                    tailscale_exe, "up",
                    f"--login-server={self.headscale_url}",
                    f"--authkey={self.headscale_authkey}",
                    f"--hostname={node_name}",
                    "--ssh",
                ],
                timeout=30, capture_output=True, text=True,
            )
            time.sleep(5)

            # Get mesh IP
            result = subprocess.run(
                [tailscale_exe, "ip", "-4"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                self.mesh_ip = result.stdout.strip()
                self._log(f"Mesh VPN connected: {self.mesh_ip}", "ok")

                # Report mesh IP to hub
                try:
                    report_url = f"{self.hub_url}/tools/starbase/api/nodes/{self.node_id}/mesh-ip"
                    req = Request(
                        report_url,
                        data=json.dumps({"mesh_ip": self.mesh_ip}).encode(),
                        headers={
                            "Content-Type": "application/json",
                            "X-Node-API-Key": self.api_key,
                        },
                        method="POST",
                    )
                    urlopen(req, timeout=10)
                    self._log("Mesh IP reported to hub", "ok")
                except Exception as e:
                    self._log(f"Could not report mesh IP: {e}", "warn")

                # Update .env with mesh IP
                with open(ENV_FILE, "a") as f:
                    f.write(f"MESH_IP={self.mesh_ip}\n")
            else:
                self._log("Tailscale joined but no IP assigned yet", "warn")
        except Exception as e:
            self._log(f"Mesh join failed: {e}", "warn")
            self._log("VPN can be configured later", "info")

    # ── Step 6: Write Stack Files (no downloads — images pulled by Docker) ───
    def _step_download(self):
        """Write docker-compose.yml to disk. All code runs inside Docker images
        pulled from ghcr.io — no local Python files, no Dockerfile, no build step.
        This eliminates the hub-download approach that corrupted node .246."""
        os.makedirs(INSTALL_DIR, exist_ok=True)

        compose_path = os.path.join(INSTALL_DIR, "docker-compose.yml")
        compose_content = _COMPOSE_TEMPLATE
        with open(compose_path, "w") as f:
            f.write(compose_content)
        self._log(f"Wrote docker-compose.yml ({len(compose_content):,} bytes)", "ok")

        # Write helper scripts
        for name, content in _HELPER_SCRIPTS.items():
            path = os.path.join(INSTALL_DIR, name)
            with open(path, "w") as f:
                f.write(content)
            self._log(f"Wrote {name}", "ok")

        # Post-process docker-compose.yml based on hardware
        compose_path = os.path.join(INSTALL_DIR, "docker-compose.yml")
        if os.path.exists(compose_path):
            self._adjust_compose(compose_path)

    def _adjust_compose(self, compose_path):
        """Adjust docker-compose.yml based on detected hardware."""
        try:
            with open(compose_path, "r") as f:
                content = f.read()
        except Exception:
            return

        modified = False
        hw = self.hw_info

        # No GPU: strip GPU config
        if not hw.get("gpu_available", False):
            self._log("No GPU detected — removing GPU config from compose.", "yellow")
            # Remove deploy.resources.reservations.devices YAML block
            # and NVIDIA_VISIBLE_DEVICES env var
            if "NVIDIA_VISIBLE_DEVICES" in content:
                lines = content.split("\n")
                new_lines = [l for l in lines if "NVIDIA_VISIBLE_DEVICES" not in l]
                content = "\n".join(new_lines)
                modified = True
            if "driver: nvidia" in content:
                # Remove the deploy/resources/reservations/devices block
                # This is a simplified approach — strip lines between markers
                lines = content.split("\n")
                new_lines = []
                skip_depth = 0
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("deploy:"):
                        skip_depth = len(line) - len(line.lstrip())
                        # Skip this entire deploy block
                        continue
                    if skip_depth > 0:
                        current_depth = len(line) - len(line.lstrip()) if line.strip() else skip_depth + 1
                        if current_depth > skip_depth or not line.strip():
                            continue
                        else:
                            skip_depth = 0
                    new_lines.append(line)
                content = "\n".join(new_lines)
                modified = True

        # GPU detected but low disk: remove ComfyUI service
        if hw.get("gpu_available", False) and hw.get("disk_free_gb", 0) < 50:
            self._log("Low disk space — disabling ComfyUI service.", "warn")
            if "comfyui" in content.lower():
                lines = content.split("\n")
                new_lines = []
                in_comfyui = False
                comfyui_indent = 0
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("comfyui:") or stripped.startswith("archie_comfyui:"):
                        in_comfyui = True
                        comfyui_indent = len(line) - len(line.lstrip())
                        continue
                    if in_comfyui:
                        current_indent = len(line) - len(line.lstrip()) if line.strip() else comfyui_indent + 1
                        if current_indent > comfyui_indent or not line.strip():
                            continue
                        else:
                            in_comfyui = False
                    if not in_comfyui:
                        new_lines.append(line)
                content = "\n".join(new_lines)
                modified = True

        if modified:
            with open(compose_path, "w") as f:
                f.write(content)

    # ── Step 6: Build & Start ─────────────────────────────────────────────────
    def _step_build(self):
        self._log("Building containers (this may take several minutes)...", "cyan")
        try:
            result = subprocess.run(
                ["docker", "compose", "build", "--no-cache"],
                cwd=INSTALL_DIR, capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                self._log(f"Build warnings: {result.stderr[:300]}", "warn")
            else:
                self._log("Containers built successfully.", "ok")
        except subprocess.TimeoutExpired:
            self._log("Build is taking a long time but may still be running.", "warn")
        except Exception as e:
            raise _StepError(f"Docker build failed: {e}")

        self._log("Starting containers...", "cyan")
        try:
            result = subprocess.run(
                ["docker", "compose", "up", "-d"],
                cwd=INSTALL_DIR, capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                raise _StepError(f"Docker compose up failed: {result.stderr[:300]}")
        except subprocess.TimeoutExpired:
            raise _StepError("Docker compose up timed out after 120 seconds.")
        except _StepError:
            raise
        except Exception as e:
            raise _StepError(f"Failed to start containers: {e}")

        # Count containers
        try:
            ps_result = subprocess.run(
                ["docker", "compose", "ps", "-q"],
                cwd=INSTALL_DIR, capture_output=True, text=True, timeout=15,
            )
            count = len([l for l in ps_result.stdout.strip().split("\n") if l.strip()])
            self._log(f"Started {count} container(s).", "ok")
        except Exception:
            self._log("Containers started.", "ok")

    # ── Step 7: Wait for Approval ─────────────────────────────────────────────
    def _step_approval(self):
        if not self.node_id:
            self._log("No node ID — skipping approval check.", "warn")
            return

        status_url = f"{self.hub_url}/tools/starbase/api/nodes/{self.node_id}/status"
        dots = ""

        for i in range(60):  # Poll for up to 10 minutes
            if self._cancel_flag:
                return
            try:
                resp_bytes = self._http_get(status_url, timeout=10)
                data = json.loads(resp_bytes.decode("utf-8"))
                status = data.get("status", data.get("approval_status", "pending"))
                if status in ("approved", "active", "online"):
                    self._log("Node approved by hub!", "ok")
                    self._log("Models are being pushed to your node...", "cyan")
                    return
            except Exception:
                pass

            dots = "." * ((i % 3) + 1)
            self._log(f"Waiting for hub approval{dots}", "info")
            time.sleep(10)

        self._log("Timed out waiting for approval. The node will sync once approved.", "yellow")

    # ── Step 10: Download AI Checkpoints ─────────────────────────────────────
    def _step_checkpoints(self):
        """Download SDXL checkpoints for ComfyUI if GPU is available."""
        if not self.hw_info.get("gpu"):
            self._log("No GPU detected — skipping checkpoint downloads.", "ok")
            return

        # Check if ComfyUI container is running
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=archie_comfyui", "-q"],
                capture_output=True, text=True, timeout=10,
            )
            if not result.stdout.strip():
                self._log("ComfyUI container not running — skipping checkpoints.", "warn")
                return
        except Exception:
            self._log("Could not check ComfyUI container — skipping checkpoints.", "warn")
            return

        checkpoints_dir = "/comfyui/models/checkpoints"
        models = [
            (
                "RealVisXL_V4.0.safetensors",
                "https://huggingface.co/SG161222/RealVisXL_V4.0/resolve/main/RealVisXL_V4.0.safetensors",
            ),
            (
                "sd_xl_base_1.0.safetensors",
                "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
            ),
        ]

        for filename, url in models:
            dest = f"{checkpoints_dir}/{filename}"
            # Check if already exists via docker exec
            try:
                check = subprocess.run(
                    ["docker", "exec", "archie_comfyui", "test", "-f", dest],
                    capture_output=True, timeout=5,
                )
                if check.returncode == 0:
                    self._log(f"{filename} already downloaded.", "ok")
                    continue
            except Exception:
                pass

            self._log(f"Downloading {filename} (~6.5GB)...", "cyan")
            self._log("This may take a while depending on internet speed.", "info")
            try:
                result = subprocess.run(
                    [
                        "docker", "exec", "archie_comfyui",
                        "wget", "-q", "--show-progress",
                        "-O", dest, url,
                    ],
                    capture_output=True, text=True, timeout=7200,
                )
                if result.returncode == 0:
                    self._log(f"{filename} downloaded successfully.", "ok")
                else:
                    self._log(f"{filename} download failed — can be retried later via OTA.", "warn")
            except subprocess.TimeoutExpired:
                self._log(f"{filename} download timed out — will retry via OTA.", "warn")
            except Exception as e:
                self._log(f"{filename} download error: {e}", "warn")

    # ── Step 11: Verify ───────────────────────────────────────────────────────
    def _step_verify(self):
        # Check container status
        try:
            result = subprocess.run(
                ["docker", "compose", "ps"],
                cwd=INSTALL_DIR, capture_output=True, text=True, timeout=15,
            )
            if result.stdout.strip():
                for line in result.stdout.strip().split("\n")[1:]:
                    if line.strip():
                        self._log(f"  {line.strip()}", "info")
        except Exception:
            self._log("Could not check container status.", "warn")

        # Clean up resume file
        self._clear_resume()

        # Show summary
        self._log("", "info")
        self._log("=" * 48, "ok")
        self._log("  INSTALLATION COMPLETE", "ok")
        self._log("=" * 48, "ok")
        self._log("", "info")
        self._log(f"Node ID:      {self.node_id}", "cyan")
        self._log(f"Hub URL:      {self.hub_url}", "cyan")
        self._log(f"Install dir:  {INSTALL_DIR}", "cyan")
        self._log(f"Version:      {CLIENT_VERSION}", "cyan")
        if self.mesh_ip:
            self._log(f"Mesh VPN:     {self.mesh_ip}", "cyan")
        self._log("", "info")

        self._update_progress(TOTAL_STEPS, "Installation complete!")

        # Change Install button to Close
        self._set_install_btn("Close", self._on_close, bg=GREEN)

    # ── Dialog helper ─────────────────────────────────────────────────────────
    def _ask_choice(self, title, message, options):
        """Show a dialog with multiple choices. Returns the chosen option text or None.
        Must be called from background thread — uses threading.Event for sync."""
        result = [None]
        event = threading.Event()

        def _show():
            # Use simple messagebox for 2-option choices, custom dialog for 3+
            if len(options) == 2:
                answer = messagebox.askyesno(title, f"{message}\n\nYes = {options[0]}\nNo = {options[1]}")
                result[0] = options[0] if answer else options[1]
            elif len(options) == 3:
                # Yes/No/Cancel style
                answer = messagebox.askyesnocancel(title, f"{message}\n\nYes = {options[0]}\nNo = {options[1]}\nCancel = {options[2]}")
                if answer is True:
                    result[0] = options[0]
                elif answer is False:
                    result[0] = options[1]
                else:
                    result[0] = options[2]
            event.set()

        self.after(0, _show)
        event.wait(timeout=300)
        return result[0]

    # ── Cancel / Close ────────────────────────────────────────────────────────
    def _on_cancel(self):
        """Handle cancel button or window close."""
        if self._install_thread and self._install_thread.is_alive():
            self._cancel_flag = True
            self._log("Cancelling installation...", "warn")
            # Give thread a moment to notice
            self.after(2000, self.destroy)
        else:
            self.destroy()

    def _on_close(self):
        """Clean shutdown."""
        self.destroy()


class _StepError(Exception):
    """Raised by a step to abort the install flow with a message."""
    pass


def main():
    app = ArchieInstaller()
    # Centre on screen
    app.update_idletasks()
    w = app.winfo_width()
    h = app.winfo_height()
    x = (app.winfo_screenwidth() // 2) - (w // 2)
    y = (app.winfo_screenheight() // 2) - (h // 2)
    app.geometry(f"+{x}+{y}")
    app.mainloop()


if __name__ == "__main__":
    main()
