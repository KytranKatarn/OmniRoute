"""
A.R.C.H.I.E. Starship Node Installer — Windows GUI Application

A standalone tkinter installer that:
1. Checks for Ollama installation
2. Registers the node with the ARCHIE hub
3. Downloads node_sync.py
4. Creates a Windows startup shortcut
5. Launches the node sync service

No external dependencies — uses only Python stdlib.
Package with PyInstaller for a single .exe distribution.
"""

import json
import os
import platform
import socket
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import webbrowser
import shutil

# ── Colour palette (LCARS-inspired) ──────────────────────────────────────────
BG_DARK = "#0a0e17"
BG_PANEL = "#111827"
BG_INPUT = "#1e293b"
CYAN = "#00e5ff"
TEAL = "#14b8a6"
AMBER = "#fbbf24"
RED = "#ef4444"
GREEN = "#22c55e"
PURPLE = "#8b5cf6"
TEXT_PRIMARY = "#e2e8f0"
TEXT_DIM = "#94a3b8"
BORDER = "#1e3a5f"

APP_DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ARCHIE-Node")
CONFIG_PATH = os.path.join(APP_DATA_DIR, "config.json")
NODE_SYNC_PATH = os.path.join(APP_DATA_DIR, "node_sync.py")


class ArchieInstaller(tk.Tk):
    """Main installer window."""

    def __init__(self):
        super().__init__()

        self.title("A.R.C.H.I.E. Starship Node Setup")
        self.geometry("620x680")
        self.resizable(False, False)
        self.configure(bg=BG_DARK)

        # Try to set icon if bundled
        icon_path = self._resource_path("archie_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Resource helper (PyInstaller compat) ─────────────────────────────────
    @staticmethod
    def _resource_path(relative_path):
        """Get absolute path to resource, works for dev and for PyInstaller."""
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, relative_path)

    # ── UI Construction ──────────────────────────────────────────────────────
    def _build_ui(self):
        # Title bar
        title_frame = tk.Frame(self, bg=CYAN, height=4)
        title_frame.pack(fill="x")

        header = tk.Frame(self, bg=BG_DARK, pady=16)
        header.pack(fill="x")

        title_font = tkfont.Font(family="Segoe UI", size=18, weight="bold")
        tk.Label(
            header,
            text="A.R.C.H.I.E.",
            font=title_font,
            fg=CYAN,
            bg=BG_DARK,
        ).pack()

        subtitle_font = tkfont.Font(family="Segoe UI", size=11)
        tk.Label(
            header,
            text="Starship Node Setup",
            font=subtitle_font,
            fg=TEXT_DIM,
            bg=BG_DARK,
        ).pack()

        # Separator
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20)

        # Hub URL input section
        input_frame = tk.Frame(self, bg=BG_DARK, pady=16, padx=30)
        input_frame.pack(fill="x")

        label_font = tkfont.Font(family="Segoe UI", size=10)
        tk.Label(
            input_frame,
            text="Hub URL",
            font=label_font,
            fg=TEAL,
            bg=BG_DARK,
            anchor="w",
        ).pack(fill="x")

        self.hub_url_var = tk.StringVar(value="https://archie.kytranempowerment.com")
        entry_font = tkfont.Font(family="Consolas", size=11)
        self.hub_entry = tk.Entry(
            input_frame,
            textvariable=self.hub_url_var,
            font=entry_font,
            bg=BG_INPUT,
            fg=TEXT_PRIMARY,
            insertbackground=CYAN,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=CYAN,
        )
        self.hub_entry.pack(fill="x", pady=(4, 0), ipady=8)

        # Node name input
        tk.Label(
            input_frame,
            text="Node Name (optional — auto-generated if blank)",
            font=label_font,
            fg=TEAL,
            bg=BG_DARK,
            anchor="w",
        ).pack(fill="x", pady=(12, 0))

        self.node_name_var = tk.StringVar(value="")
        self.name_entry = tk.Entry(
            input_frame,
            textvariable=self.node_name_var,
            font=entry_font,
            bg=BG_INPUT,
            fg=TEXT_PRIMARY,
            insertbackground=CYAN,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=CYAN,
        )
        self.name_entry.pack(fill="x", pady=(4, 0), ipady=8)
        self.name_entry.insert(0, f"{socket.gethostname()}")

        # Connect button
        btn_frame = tk.Frame(self, bg=BG_DARK, pady=10)
        btn_frame.pack(fill="x", padx=30)

        btn_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.connect_btn = tk.Button(
            btn_frame,
            text="CONNECT",
            font=btn_font,
            bg=CYAN,
            fg=BG_DARK,
            activebackground=TEAL,
            activeforeground=BG_DARK,
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._start_setup,
            padx=30,
            pady=10,
        )
        self.connect_btn.pack(fill="x")

        # Separator
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(10, 0))

        # Status / log area
        log_header = tk.Frame(self, bg=BG_DARK, padx=30, pady=(8, 0))
        log_header.pack(fill="x")
        tk.Label(
            log_header,
            text="STATUS LOG",
            font=tkfont.Font(family="Segoe UI", size=9, weight="bold"),
            fg=TEXT_DIM,
            bg=BG_DARK,
            anchor="w",
        ).pack(fill="x")

        log_frame = tk.Frame(self, bg=BG_PANEL, padx=30, pady=8)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(4, 10))

        log_font = tkfont.Font(family="Consolas", size=9)
        self.log_text = tk.Text(
            log_frame,
            bg=BG_PANEL,
            fg=TEXT_DIM,
            font=log_font,
            relief="flat",
            bd=0,
            wrap="word",
            state="disabled",
            cursor="arrow",
        )
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

        # Configure text tags for colours
        self.log_text.tag_configure("info", foreground=TEXT_DIM)
        self.log_text.tag_configure("step", foreground=CYAN)
        self.log_text.tag_configure("success", foreground=GREEN)
        self.log_text.tag_configure("warning", foreground=AMBER)
        self.log_text.tag_configure("error", foreground=RED)
        self.log_text.tag_configure("highlight", foreground=PURPLE)

        # Bottom bar with close button (hidden until done)
        self.bottom_frame = tk.Frame(self, bg=BG_DARK, pady=10, padx=30)
        self.bottom_frame.pack(fill="x")

        self.close_btn = tk.Button(
            self.bottom_frame,
            text="CLOSE",
            font=tkfont.Font(family="Segoe UI", size=10, weight="bold"),
            bg=BG_INPUT,
            fg=TEXT_PRIMARY,
            activebackground=BORDER,
            activeforeground=TEXT_PRIMARY,
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._on_close,
            padx=20,
            pady=6,
        )
        # Don't pack yet — shown after setup completes

        # Bottom accent bar
        tk.Frame(self, bg=CYAN, height=3).pack(fill="x", side="bottom")

    # ── Logging helpers ──────────────────────────────────────────────────────
    def _log(self, message, tag="info"):
        """Append a message to the log area (thread-safe)."""
        def _do():
            self.log_text.configure(state="normal")
            prefix = {"step": ">> ", "success": "[OK] ", "error": "[!!] ", "warning": "[!] ", "highlight": "   "}.get(tag, "   ")
            self.log_text.insert("end", f"{prefix}{message}\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _do)

    # ── Ollama detection ─────────────────────────────────────────────────────
    def _find_ollama(self):
        """Check if Ollama is installed. Returns path or None."""
        # Check PATH first
        ollama_in_path = shutil.which("ollama")
        if ollama_in_path:
            return ollama_in_path

        # Common Windows install locations
        common_paths = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Ollama", "ollama.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Ollama", "ollama.exe"),
            os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "Programs", "Ollama", "ollama.exe"),
            r"C:\Program Files\Ollama\ollama.exe",
            r"C:\Ollama\ollama.exe",
        ]
        # Linux/macOS
        if platform.system() != "Windows":
            common_paths.extend(["/usr/local/bin/ollama", "/usr/bin/ollama", "/opt/ollama/ollama"])

        for p in common_paths:
            if p and os.path.isfile(p):
                return p

        return None

    def _check_ollama_running(self):
        """Check if Ollama server is responding."""
        try:
            req = Request("http://127.0.0.1:11434/api/tags", method="GET")
            resp = urlopen(req, timeout=5)
            return resp.status == 200
        except Exception:
            return False

    # ── Hardware detection ───────────────────────────────────────────────────
    def _detect_hardware(self):
        """Gather basic hardware info."""
        info = {
            "hostname": socket.gethostname(),
            "os_info": f"{platform.system()} {platform.release()} {platform.machine()}",
            "cpu_model": platform.processor() or "Unknown",
            "cpu_cores": os.cpu_count() or 1,
        }

        # Try to get RAM
        try:
            if platform.system() == "Windows":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                c_ulonglong = ctypes.c_ulonglong

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", c_ulonglong),
                        ("ullAvailPhys", c_ulonglong),
                        ("ullTotalPageFile", c_ulonglong),
                        ("ullAvailPageFile", c_ulonglong),
                        ("ullTotalVirtual", c_ulonglong),
                        ("ullAvailVirtual", c_ulonglong),
                        ("ullAvailExtendedVirtual", c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(stat)
                kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                info["ram_gb"] = round(stat.ullTotalPhys / (1024 ** 3), 1)
            else:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal"):
                            kb = int(line.split()[1])
                            info["ram_gb"] = round(kb / (1024 * 1024), 1)
                            break
        except Exception:
            info["ram_gb"] = 0

        # Try to detect GPU via Ollama (if running)
        info["gpu_available"] = False
        info["gpu_model"] = None
        info["gpu_vram_gb"] = None

        return info

    # ── Network helpers ──────────────────────────────────────────────────────
    def _post_json(self, url, data):
        """POST JSON and return parsed response."""
        body = json.dumps(data).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        resp = urlopen(req, timeout=30)
        return json.loads(resp.read().decode("utf-8"))

    def _download_file(self, url, dest_path):
        """Download a file from URL to local path."""
        req = Request(url, method="GET")
        resp = urlopen(req, timeout=60)
        content = resp.read()
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(content)
        return len(content)

    # ── Startup shortcut ─────────────────────────────────────────────────────
    def _create_startup_shortcut(self):
        """Create a .bat in Windows Startup folder to launch node_sync.py on boot."""
        if platform.system() != "Windows":
            self._log("Skipping startup shortcut (not Windows)", "info")
            return False

        try:
            startup_dir = os.path.join(
                os.environ.get("APPDATA", ""),
                "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
            )
            if not os.path.isdir(startup_dir):
                self._log(f"Startup folder not found: {startup_dir}", "warning")
                return False

            # Find python
            python_exe = sys.executable
            if not python_exe or "python" not in python_exe.lower():
                python_exe = shutil.which("python3") or shutil.which("python") or "python"

            bat_path = os.path.join(startup_dir, "ARCHIE-Node-Sync.bat")
            bat_content = (
                "@echo off\r\n"
                f'start /min "" "{python_exe}" "{NODE_SYNC_PATH}"\r\n'
            )
            with open(bat_path, "w") as f:
                f.write(bat_content)

            self._log(f"Startup shortcut created: {bat_path}", "success")
            return True
        except Exception as e:
            self._log(f"Could not create startup shortcut: {e}", "warning")
            return False

    # ── Main setup flow ──────────────────────────────────────────────────────
    def _start_setup(self):
        """Begin the setup process in a background thread."""
        self.connect_btn.configure(state="disabled", bg=BG_INPUT, fg=TEXT_DIM)
        self.hub_entry.configure(state="disabled")
        self.name_entry.configure(state="disabled")
        thread = threading.Thread(target=self._run_setup, daemon=True)
        thread.start()

    def _run_setup(self):
        """Execute all setup steps (runs in background thread)."""
        hub_url = self.hub_url_var.get().strip().rstrip("/")
        node_name = self.node_name_var.get().strip()

        if not hub_url:
            self._log("Please enter a Hub URL.", "error")
            self._re_enable_connect()
            return

        # ── Step 1: Check Ollama ─────────────────────────────────────────
        self._log("Checking prerequisites...", "step")

        ollama_path = self._find_ollama()
        if ollama_path:
            self._log(f"Ollama found: {ollama_path}", "success")
        else:
            self._log("Ollama is NOT installed.", "error")
            self._log("Ollama is required to run AI models on this node.", "warning")
            self._log("Download from: https://ollama.com/download", "warning")
            self._show_ollama_link()
            self._re_enable_connect()
            return

        # Check if Ollama is running
        if self._check_ollama_running():
            self._log("Ollama server is running.", "success")
        else:
            self._log("Ollama is installed but not running.", "warning")
            self._log("Starting Ollama...", "step")
            try:
                if platform.system() == "Windows":
                    subprocess.Popen(
                        [ollama_path, "serve"],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    subprocess.Popen(
                        [ollama_path, "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                # Wait a moment for it to start
                import time
                for i in range(10):
                    time.sleep(1)
                    if self._check_ollama_running():
                        break
                if self._check_ollama_running():
                    self._log("Ollama started successfully.", "success")
                else:
                    self._log("Ollama may still be starting. Continuing anyway...", "warning")
            except Exception as e:
                self._log(f"Could not start Ollama: {e}", "warning")
                self._log("You may need to start Ollama manually.", "warning")

        # ── Step 2: Detect hardware ──────────────────────────────────────
        self._log("Detecting hardware...", "step")
        hw = self._detect_hardware()
        self._log(f"OS: {hw['os_info']}", "highlight")
        self._log(f"CPU: {hw['cpu_model']} ({hw['cpu_cores']} cores)", "highlight")
        if hw.get("ram_gb"):
            self._log(f"RAM: {hw['ram_gb']} GB", "highlight")

        # Check Ollama for GPU info
        try:
            req = Request("http://127.0.0.1:11434/api/tags", method="GET")
            resp = urlopen(req, timeout=5)
            ollama_data = json.loads(resp.read().decode("utf-8"))
            hw["ollama_available"] = True
            model_count = len(ollama_data.get("models", []))
            self._log(f"Ollama models available: {model_count}", "highlight")
        except Exception:
            hw["ollama_available"] = True  # It's installed, just may not respond yet

        # ── Step 3: Register with hub ────────────────────────────────────
        self._log("Registering with hub...", "step")

        register_url = f"{hub_url}/tools/starbase/api/nodes/register"
        payload = {
            "node_name": node_name or hw["hostname"],
            "hostname": hw["hostname"],
            "os_info": hw["os_info"],
            "cpu_model": hw["cpu_model"],
            "cpu_cores": hw["cpu_cores"],
            "ram_gb": hw.get("ram_gb"),
            "gpu_available": hw.get("gpu_available", False),
            "gpu_model": hw.get("gpu_model"),
            "gpu_vram_gb": hw.get("gpu_vram_gb"),
            "ollama_available": hw.get("ollama_available", False),
            "client_version": "1.0.0-installer",
        }

        try:
            result = self._post_json(register_url, payload)
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            self._log(f"Registration failed (HTTP {e.code}): {body[:200]}", "error")
            self._re_enable_connect()
            return
        except URLError as e:
            self._log(f"Cannot reach hub: {e.reason}", "error")
            self._log("Check the URL and your network connection.", "warning")
            self._re_enable_connect()
            return
        except Exception as e:
            self._log(f"Registration error: {e}", "error")
            self._re_enable_connect()
            return

        if not result.get("success"):
            self._log(f"Registration rejected: {result.get('error', 'Unknown error')}", "error")
            self._re_enable_connect()
            return

        node_id = result.get("node_id", "unknown")
        api_key = result.get("api_key", "")
        node_display = result.get("node_name", node_name)
        approval = result.get("approval_status", "pending")

        self._log(f"Registered as: {node_display}", "success")
        self._log(f"Node ID: {node_id}", "highlight")
        self._log(f"Approval status: {approval}", "highlight")

        # ── Step 4: Save config ──────────────────────────────────────────
        self._log("Saving configuration...", "step")

        config = {
            "node_id": node_id,
            "node_name": node_display,
            "hub_url": hub_url,
            "api_key": api_key,
            "starbase_url": f"{hub_url}",
            "deployment_mode": "starship",
            "heartbeat_interval": 30,
            "ollama_host": "http://127.0.0.1:11434",
        }

        try:
            os.makedirs(APP_DATA_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
            self._log(f"Config saved: {CONFIG_PATH}", "success")
        except Exception as e:
            self._log(f"Failed to save config: {e}", "error")
            self._re_enable_connect()
            return

        # ── Step 5: Download node_sync.py ────────────────────────────────
        self._log("Downloading node client...", "step")

        sync_url = f"{hub_url}/tools/starbase/api/nodes/node_sync.py"
        try:
            size = self._download_file(sync_url, NODE_SYNC_PATH)
            self._log(f"Downloaded node_sync.py ({size:,} bytes)", "success")
        except HTTPError as e:
            self._log(f"Download failed (HTTP {e.code})", "error")
            self._log("The node client file may not be available on the hub.", "warning")
            self._re_enable_connect()
            return
        except Exception as e:
            self._log(f"Download error: {e}", "error")
            self._re_enable_connect()
            return

        # ── Step 6: Create startup shortcut ──────────────────────────────
        self._log("Setting up auto-start...", "step")
        self._create_startup_shortcut()

        # ── Step 7: Launch node sync ─────────────────────────────────────
        self._log("Launching node sync service...", "step")

        try:
            python_exe = sys.executable
            if not python_exe or "python" not in python_exe.lower():
                python_exe = shutil.which("python3") or shutil.which("python") or "python"

            if platform.system() == "Windows":
                subprocess.Popen(
                    [python_exe, NODE_SYNC_PATH],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=APP_DATA_DIR,
                )
            else:
                subprocess.Popen(
                    [python_exe, NODE_SYNC_PATH],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=APP_DATA_DIR,
                )
            self._log("Node sync service launched.", "success")
        except Exception as e:
            self._log(f"Could not launch sync service: {e}", "warning")
            self._log("You can start it manually by running:", "warning")
            self._log(f"  python \"{NODE_SYNC_PATH}\"", "highlight")

        # ── Done ─────────────────────────────────────────────────────────
        self._log("", "info")
        self._log("=" * 50, "success")
        self._log("SUCCESS! Your node is now connected.", "success")
        self._log("=" * 50, "success")
        self._log("", "info")
        self._log(f"Node name:   {node_display}", "highlight")
        self._log(f"Node ID:     {node_id}", "highlight")
        self._log(f"Hub:         {hub_url}", "highlight")
        self._log(f"Config:      {CONFIG_PATH}", "highlight")
        self._log("", "info")
        if approval == "pending":
            self._log("Your node is pending approval by the hub admin.", "warning")
            self._log("Once approved, it will begin receiving AI workloads.", "warning")
        else:
            self._log("Your node is active and ready for AI workloads.", "success")

        # Show close button
        self.after(0, lambda: self.close_btn.pack(fill="x"))

    # ── UI helpers ───────────────────────────────────────────────────────────
    def _re_enable_connect(self):
        """Re-enable the connect button after a failure."""
        def _do():
            self.connect_btn.configure(state="normal", bg=CYAN, fg=BG_DARK)
            self.hub_entry.configure(state="normal")
            self.name_entry.configure(state="normal")
        self.after(0, _do)

    def _show_ollama_link(self):
        """Show a clickable link to download Ollama."""
        def _do():
            link_frame = tk.Frame(self.log_text, bg=BG_PANEL)
            link = tk.Label(
                link_frame,
                text="Click here to download Ollama",
                fg=CYAN,
                bg=BG_PANEL,
                cursor="hand2",
                font=tkfont.Font(family="Segoe UI", size=10, underline=True),
            )
            link.pack(padx=4, pady=4)
            link.bind("<Button-1>", lambda e: webbrowser.open("https://ollama.com/download"))

            self.log_text.configure(state="normal")
            self.log_text.window_create("end", window=link_frame)
            self.log_text.insert("end", "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _do)

    def _on_close(self):
        """Clean shutdown."""
        self.destroy()


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
