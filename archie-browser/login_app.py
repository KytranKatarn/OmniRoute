"""archie_browser_login supervisor — the S.I.G.N.A.L. session-login surface (#3953).

Runs permanently (cheap idle: Xvfb + x11vnc + noVNC are started by the
entrypoint). Holds NO browser until /start, so the shared profile stays free
for the headless worker. On /start it spawns login_browser.py (headed
Chromium into the persistent profile); the owner completes the login through
noVNC; /stop (or the idle timeout) terminates Chromium, which flushes the
now-trusted profile to disk for the worker.

No docker socket, no credentials — this container only ever sees the
profile volume and the X display.
"""
import logging
import os
import signal
import subprocess
import threading
import time

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("login_app")

app = Flask(__name__)

PROFILES_DIR = os.getenv("BROWSER_PROFILES_DIR", "/profiles")
IDLE_TIMEOUT_S = int(os.getenv("LOGIN_IDLE_TIMEOUT", "900"))  # auto-stop after 15 min
API_PORT = int(os.getenv("LOGIN_API_PORT", "4281"))

_state_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_started_at: float = 0.0
_target: dict = {}


def _profile_dir(agent_id: int, platform: str) -> str:
    return os.path.join(PROFILES_DIR, f"{agent_id}-{platform}")


def _running() -> bool:
    return _proc is not None and _proc.poll() is None


def _stop_browser(reason: str) -> bool:
    global _proc
    with _state_lock:
        if not _running():
            _proc = None
            return False
        logger.info("stopping login browser (%s)", reason)
        _proc.send_signal(signal.SIGTERM)
        try:
            _proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            _proc.kill()
        _proc = None
        return True


def _idle_watchdog():
    while True:
        time.sleep(30)
        if _running() and (time.time() - _started_at) > IDLE_TIMEOUT_S:
            _stop_browser(f"idle timeout {IDLE_TIMEOUT_S}s")


@app.get("/status")
def status():
    agent_id = int(request.args.get("agent_id", 342))
    platform = request.args.get("platform", "linkedin")
    pdir = _profile_dir(agent_id, platform)
    established = os.path.isdir(pdir) and bool(os.listdir(pdir))
    return jsonify(
        {
            "login_browser_running": _running(),
            "target": _target if _running() else None,
            "profile_established": established,
            "profile_dir": pdir,
            "idle_timeout_s": IDLE_TIMEOUT_S,
            "seconds_running": int(time.time() - _started_at) if _running() else 0,
        }
    )


@app.post("/start")
def start():
    global _proc, _started_at, _target
    j = request.get_json(silent=True) or {}
    agent_id = int(j.get("agent_id", 342))
    platform = (j.get("platform") or "linkedin").strip().lower()
    start_url = j.get("url") or "https://www.linkedin.com/login"
    pdir = _profile_dir(agent_id, platform)

    with _state_lock:
        if _running():
            return jsonify({"started": False, "error": "login browser already running"}), 409
        env = dict(os.environ)
        env.setdefault("DISPLAY", ":99")
        _proc = subprocess.Popen(
            ["python3", os.path.join(os.path.dirname(__file__), "login_browser.py"), pdir, start_url],
            env=env,
        )
        _started_at = time.time()
        _target = {"agent_id": agent_id, "platform": platform}
    logger.info("login browser started for %s/%s -> %s", agent_id, platform, pdir)
    return jsonify({"started": True, "profile_dir": pdir, "idle_timeout_s": IDLE_TIMEOUT_S})


@app.post("/stop")
def stop():
    stopped = _stop_browser("api /stop")
    return jsonify({"stopped": stopped})


if __name__ == "__main__":
    threading.Thread(target=_idle_watchdog, daemon=True).start()
    app.run(host="0.0.0.0", port=API_PORT)
