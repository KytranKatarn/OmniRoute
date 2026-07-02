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
import hmac
import ipaddress
import logging
import os
import re
import signal
import subprocess
import threading
import time
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("login_app")

app = Flask(__name__)

PROFILES_DIR = os.getenv("BROWSER_PROFILES_DIR", "/profiles")
IDLE_TIMEOUT_S = int(os.getenv("LOGIN_IDLE_TIMEOUT", "900"))  # auto-stop after 15 min
API_PORT = int(os.getenv("LOGIN_API_PORT", "4281"))

# Bearer token gating every route. Reuses the platform-wide INTERNAL_API_KEY
# (already shared with archie_platform via env_file). Fail-closed: if unset,
# the API refuses all requests — a privileged action (spawning a headed
# browser that navigates inside the owner's trusted profile) must never be
# reachable unauthenticated, even on the internal Docker network.
_API_TOKEN = os.getenv("INTERNAL_API_KEY") or ""

# Strict allowlists — platform flows into a filesystem path and start_url is
# navigated by the headed browser inside the trusted profile, so both are
# attacker-relevant (path traversal / SSRF-shaped open-redirect). Extend
# deliberately as new device-trust sites are added (#3982).
_ALLOWED_PLATFORMS = {"linkedin", "x", "claude", "deepseek"}
_ALLOWED_LOGIN_HOSTS = {
    "linkedin": {"www.linkedin.com", "linkedin.com"},
    # #3982 multi-site: mirrors the S.C.O.U.T. cookie-import allowlist —
    # same one-time-human-login + persistent-device-trust model per site.
    "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"},
    "claude": {"claude.ai", "www.claude.ai"},
    "deepseek": {"chat.deepseek.com", "www.deepseek.com"},
}
_DEFAULT_LOGIN_URL = {
    "linkedin": "https://www.linkedin.com/login",
    "x": "https://x.com/i/flow/login",
    "claude": "https://claude.ai/login",
    "deepseek": "https://chat.deepseek.com/sign_in",
}

# #4006 dynamic platforms: hub registry (browser_platforms) supplies
# login_url + allowed_hosts per request; we re-validate everything locally
# (key shape, https, public-FQDN) — the sidecar never trusts the hub payload.
# Baked platforms above keep their hardcoded allowlists and IGNORE caller
# overrides, preserving the original trust boundary.
_PLATFORM_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
_PROFILE_DIR_RE = re.compile(r"^(\d+)-([a-z0-9_-]{2,32})$")
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".lan")

_state_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_started_at: float = 0.0
_target: dict = {}


@app.before_request
def _require_token():
    """Fail-closed bearer-token auth on every route."""
    if not _API_TOKEN:
        logger.error("INTERNAL_API_KEY unset — refusing all requests")
        abort(503)
    expected = f"Bearer {_API_TOKEN}"
    provided = request.headers.get("Authorization", "")
    if not hmac.compare_digest(provided, expected):
        abort(401)


def _valid_agent_id(raw) -> int:
    """Coerce + validate a positive int agent_id, else 400."""
    try:
        aid = int(raw)
    except (TypeError, ValueError):
        abort(400, "invalid agent_id")
    if aid <= 0:
        abort(400, "invalid agent_id")
    return aid


def _valid_platform(raw) -> str:
    p = (raw or "linkedin").strip().lower()
    if p in _ALLOWED_PLATFORMS:
        return p
    # #4006: dynamic platform keys — shape-validated here (they flow into a
    # filesystem path); /start additionally requires + validates a
    # caller-supplied login_url/allowed_hosts before navigating anywhere.
    if not _PLATFORM_RE.match(p):
        abort(400, "unsupported platform")
    return p


def _valid_public_host(host: str) -> bool:
    """Public FQDN only — reject IP literals, single-label (Docker service)
    names, and internal suffixes. No DNS-resolve check: hub split-horizon DNS
    maps our own public subdomains to private IPs."""
    h = (host or "").strip().lower().rstrip(".")
    if not h or len(h) > 253:
        return False
    try:
        ipaddress.ip_address(h)
        return False  # IP literal
    except ValueError:
        pass
    if "." not in h or h.endswith(_BLOCKED_HOST_SUFFIXES):
        return False
    return bool(_HOST_RE.match(h))


def _profile_dir(agent_id: int, platform: str) -> str:
    """Build the profile dir and assert it stays inside PROFILES_DIR.

    agent_id is int-validated and platform is allowlisted by the callers, but
    we still resolve + assert containment as defence in depth against path
    traversal (e.g. a future caller forgetting to validate).
    """
    pdir = os.path.join(PROFILES_DIR, f"{agent_id}-{platform}")
    real = os.path.realpath(pdir)
    base = os.path.realpath(PROFILES_DIR)
    if real != base and not real.startswith(base + os.sep):
        abort(400, "invalid profile path")
    return pdir


def _validate_start_url(platform: str, raw_url) -> str:
    """Return a safe login URL for platform; reject off-allowlist hosts."""
    if not raw_url:
        return _DEFAULT_LOGIN_URL[platform]
    try:
        u = urlparse(raw_url)
    except Exception:
        abort(400, "invalid url")
    if u.scheme != "https" or u.hostname not in _ALLOWED_LOGIN_HOSTS.get(platform, set()):
        abort(400, "url host not allowed for platform")
    return raw_url


def _validate_dynamic_login(login_url, allowed_hosts) -> str:
    """#4006 — validate a registry-supplied login target for a non-baked
    platform: https only, host within the supplied list, every host a public
    FQDN. Re-done locally regardless of what the hub already checked."""
    hosts = {str(h).strip().lower() for h in (allowed_hosts or []) if str(h).strip()}
    if not login_url or not hosts:
        abort(400, "login_url and allowed_hosts required for this platform")
    bad = sorted(h for h in hosts if not _valid_public_host(h))
    if bad:
        abort(400, f"allowed_hosts rejected (public FQDNs only): {', '.join(bad[:5])}")
    try:
        u = urlparse(login_url)
    except Exception:
        abort(400, "invalid url")
    if u.scheme != "https" or (u.hostname or "").lower() not in hosts:
        abort(400, "login_url host not in allowed_hosts")
    return login_url


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
    agent_id = _valid_agent_id(request.args.get("agent_id", 342))
    platform = _valid_platform(request.args.get("platform", "linkedin"))
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
    agent_id = _valid_agent_id(j.get("agent_id", 342))
    platform = _valid_platform(j.get("platform"))
    if platform in _ALLOWED_PLATFORMS:
        # Baked platforms keep their hardcoded allowlists — caller-supplied
        # hosts are deliberately ignored (original trust boundary).
        start_url = _validate_start_url(platform, j.get("url"))
    else:
        start_url = _validate_dynamic_login(j.get("login_url") or j.get("url"), j.get("allowed_hosts"))
    pdir = _profile_dir(agent_id, platform)

    with _state_lock:
        if _running():
            return jsonify({"started": False, "error": "login browser already running"}), 409
        env = dict(os.environ)
        env.setdefault("DISPLAY", ":99")
        # #4006 capture-to-vault: tells login_browser.py which vault row the
        # exported storage_state belongs to.
        env["LOGIN_AGENT_ID"] = str(agent_id)
        env["LOGIN_PLATFORM"] = platform
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


@app.get("/profiles")
def profiles():
    """#4006 — enumerate REAL persistent profiles on disk so the S.C.O.U.T.
    vault stops relying on the hardcoded WARM_PROFILES registry."""
    out = []
    base = os.path.realpath(PROFILES_DIR)
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        entries = []
    for name in entries:
        m = _PROFILE_DIR_RE.match(name)
        if not m:
            continue
        full = os.path.join(base, name)
        if not os.path.isdir(full):
            continue
        try:
            established = bool(os.listdir(full))
        except OSError:
            established = False
        out.append({"agent_id": int(m.group(1)), "platform": m.group(2), "established": established})
    return jsonify({"profiles": out})


@app.post("/group-image-retry")
def group_image_retry():
    """#4649 slice 1 — weekly headed retry of the WTF group cover/logo replace
    (server-side 422 on replace, KB #277261; fresh-set works, so retry until
    LinkedIn's flow accepts it). Runs the headed task IN-PROCESS under Xvfb :99
    while HOLDING the state lock, so /start can't open the same profile
    mid-task (and vice versa: a live login session 409s this)."""
    j = request.get_json(silent=True) or {}
    group_id = re.sub(r"\D", "", str(j.get("group_id") or os.getenv("LINKEDIN_WTF_GROUP_ID", "37040054")))
    if not group_id:
        abort(400, "group_id required")

    def _safe_image(raw, default):
        path = str(raw or default)
        real = os.path.realpath(path)
        if not real.startswith(os.path.realpath(PROFILES_DIR) + os.sep) or not os.path.isfile(real):
            abort(400, f"image path must be an existing file under {PROFILES_DIR}")
        return real

    banner = _safe_image(j.get("banner_path"), "/profiles/wtf_group_banner.png")
    logo = _safe_image(j.get("logo_path"), "/profiles/wtf_logo_512.png")

    if _running():
        return jsonify({"error": "login browser session active — retry later"}), 409
    if not _state_lock.acquire(blocking=False):
        return jsonify({"error": "another headed task is running"}), 409
    try:
        from headed_tasks import group_image_retry as run_retry

        result = run_retry(group_id, banner, logo)
        logger.info("group-image-retry: %s", result)
        return jsonify(result)
    except Exception as exc:
        logger.exception("group-image-retry failed")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    finally:
        _state_lock.release()


if __name__ == "__main__":
    threading.Thread(target=_idle_watchdog, daemon=True).start()
    app.run(host="0.0.0.0", port=API_PORT)
