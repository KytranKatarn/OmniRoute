#!/usr/bin/env python3
"""
A.R.C.H.I.E. Unified Node Client
===================================
Single long-lived service that runs on any node (Windows/Linux) to keep it
in sync with the Starbase hub.

Responsibilities:
  - Sends periodic heartbeats with system metrics + self-healing on failure
  - Reports code version on startup
  - Polls for pending sync commands and processes them (OTA, model pull, etc.)
  - Loads config from config.json (primary) with env-var fallback
  - Auto-detects Ollama host if not configured
  - Writes/updates config.json after registration or OTA config updates

Standard library only (no pip install needed).
Optional: `requests` library for HTTP if available; falls back to urllib.
"""

import json
import logging
import os
import platform
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Optional requests import — fall back to urllib
# ---------------------------------------------------------------------------
try:
    import requests as _requests_lib  # type: ignore

    _HAS_REQUESTS = True
except ImportError:
    _requests_lib = None
    _HAS_REQUESTS = False
    import urllib.request
    import urllib.error

# ---------------------------------------------------------------------------
# Optional psycopg2 import — needed for local DB operations
# ---------------------------------------------------------------------------
try:
    import psycopg2
    import psycopg2.extras

    _HAS_PSYCOPG2 = True
except ImportError:
    psycopg2 = None
    _HAS_PSYCOPG2 = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("archie_node_sync")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CLIENT_VERSION = "2.2.0"


def _get_config_paths():
    """Return ordered list of config.json paths to check (platform-aware)."""
    paths = []
    if platform.system() == "Windows":
        paths.append(r"C:\ProgramData\ARCHIE-Node\config.json")
    else:
        paths.append("/etc/archie-node/config.json")
    paths.append(os.path.join(os.getcwd(), "config.json"))
    return paths


def _find_config_path():
    """Find the first existing config.json, or return the preferred write path."""
    env_path = os.environ.get("CONFIG_FILE")
    if env_path and os.path.isfile(env_path):
        return env_path
    for p in _get_config_paths():
        if os.path.isfile(p):
            return p
    if env_path:
        return env_path
    return _get_config_paths()[0]


def _auto_detect_ollama():
    """Try common Ollama endpoints and return the first that responds, or None."""
    candidates = [
        "http://localhost:11434",
        "http://host.docker.internal:11434",
    ]
    for host in candidates:
        try:
            url = f"{host}/api/tags"
            status, _ = http_get(url)
            if status == 200:
                logger.info("Auto-detected Ollama at %s", host)
                return host
        except Exception:
            pass
    return None


def write_config(config, path=None):
    """Write current config to the appropriate config.json path."""
    if path is None:
        path = config.get("_config_path") or _get_config_paths()[0]

    serializable = {
        "node_id": config.get("node_id", ""),
        "hub_url": config.get("hub_url", ""),
        "hub_api_key": config.get("hub_api_key", ""),
        "ollama_host": config.get("ollama_host", "http://localhost:11434"),
        "heartbeat_interval": config.get("heartbeat_interval", 30),
        "sync_poll_interval": config.get("sync_poll_interval", 60),
        "archie_version": config.get("archie_version", CLIENT_VERSION),
        "client_version": CLIENT_VERSION,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, mode=0o755, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(serializable, fh, indent=2)
        if platform.system() != "Windows":
            os.chmod(path, 0o600)
        logger.info("Config written to %s", path)
    except Exception as exc:
        logger.warning("Failed to write config to %s: %s", path, exc)


def load_config():
    """
    Load configuration from config.json (PRIMARY) with env-var fallback.

    Search order for config.json:
      1. $CONFIG_FILE env var (if set)
      2. Windows: C:\\ProgramData\\ARCHIE-Node\\config.json
         Linux:   /etc/archie-node/config.json
      3. ./config.json (current directory)
    Then fall back to environment variables for any missing fields.

    Required fields: NODE_ID, HUB_URL, HUB_API_KEY
    """
    config_path = _find_config_path()

    # Start with env-var defaults (secondary source)
    config = {
        "node_id": os.environ.get("NODE_ID", ""),
        "hub_url": os.environ.get("HUB_URL", ""),
        "hub_api_key": os.environ.get("HUB_API_KEY", ""),
        "ollama_host": os.environ.get("OLLAMA_HOST", ""),
        "heartbeat_interval": int(os.environ.get("HEARTBEAT_INTERVAL", "30")),
        "sync_poll_interval": int(os.environ.get("SYNC_POLL_INTERVAL", "60")),
        "archie_version": os.environ.get("ARCHIE_VERSION", CLIENT_VERSION),
    }

    # Load config.json as PRIMARY source (overrides env vars)
    if os.path.isfile(config_path):
        logger.info("Loading config from %s", config_path)
        try:
            with open(config_path, "r") as fh:
                file_cfg = json.load(fh)
            key_map = {
                "node_id": "node_id",
                "hub_url": "hub_url",
                "server_url": "hub_url",
                "hub_api_key": "hub_api_key",
                "api_key": "hub_api_key",
                "ollama_host": "ollama_host",
                "heartbeat_interval": "heartbeat_interval",
                "sync_poll_interval": "sync_poll_interval",
                "sync_interval": "sync_poll_interval",
                "archie_version": "archie_version",
                "client_version": "archie_version",
            }
            for file_key, internal_key in key_map.items():
                if file_key in file_cfg and file_cfg[file_key]:
                    val = file_cfg[file_key]
                    if internal_key in ("heartbeat_interval", "sync_poll_interval"):
                        val = int(val)
                    config[internal_key] = val
        except Exception as exc:
            logger.warning("Failed to load config file %s: %s", config_path, exc)
    else:
        logger.info("No config.json found at %s — using env vars", config_path)

    # Auto-detect Ollama host if not configured
    if not config.get("ollama_host"):
        detected = _auto_detect_ollama()
        if detected:
            config["ollama_host"] = detected
        else:
            config["ollama_host"] = "http://localhost:11434"
            logger.warning(
                "Could not auto-detect Ollama; defaulting to %s",
                config["ollama_host"],
            )

    # Store config path for later writes
    config["_config_path"] = config_path

    # Validate required fields
    missing = [k for k in ("node_id", "hub_url", "hub_api_key") if not config.get(k)]
    if missing:
        logger.error(
            "Missing required config fields: %s. "
            "Set via config.json (%s) or environment variables.",
            ", ".join(missing),
            config_path,
        )
        sys.exit(1)

    # Strip trailing slash from hub_url
    config["hub_url"] = config["hub_url"].rstrip("/")

    return config


# ---------------------------------------------------------------------------
# Fleet coordination — completed job tracking
# ---------------------------------------------------------------------------
_completed_jobs = []


# ---------------------------------------------------------------------------
# Local Database Helpers
# ---------------------------------------------------------------------------


def _get_node_db():
    """Get a connection to the local node database (if available)."""
    if not _HAS_PSYCOPG2:
        logger.warning("psycopg2 not installed — local DB operations disabled")
        return None
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        return conn
    except Exception as e:
        logger.error("Failed to connect to local DB: %s", e)
        return None


# ---------------------------------------------------------------------------
# HTTP Helpers
# ---------------------------------------------------------------------------


def http_post(url, data, headers=None, timeout=15):
    """
    POST JSON data to *url*. Returns (status_code, response_json).
    Uses `requests` if available, otherwise falls back to urllib.
    """
    headers = headers or {}
    headers.setdefault("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8")

    if _HAS_REQUESTS:
        try:
            resp = _requests_lib.post(url, json=data, headers=headers, timeout=timeout)
            try:
                resp_json = resp.json()
            except Exception:
                resp_json = {"raw": resp.text}
            return resp.status_code, resp_json
        except Exception as exc:
            logger.debug("requests POST failed: %s", exc)
            return 0, {"error": str(exc)}
    else:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read().decode("utf-8")
                try:
                    resp_json = json.loads(resp_body)
                except Exception:
                    resp_json = {"raw": resp_body}
                return resp.status, resp_json
        except urllib.error.HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8")
                resp_json = json.loads(err_body)
            except Exception:
                resp_json = {"error": str(exc)}
            return exc.code, resp_json
        except Exception as exc:
            logger.debug("urllib POST failed: %s", exc)
            return 0, {"error": str(exc)}


def http_get(url, headers=None):
    """
    GET from *url*. Returns (status_code, response_json).
    Uses `requests` if available, otherwise falls back to urllib.
    """
    headers = headers or {}

    if _HAS_REQUESTS:
        try:
            resp = _requests_lib.get(url, headers=headers, timeout=15)
            try:
                resp_json = resp.json()
            except Exception:
                resp_json = {"raw": resp.text}
            return resp.status_code, resp_json
        except Exception as exc:
            logger.debug("requests GET failed: %s", exc)
            return 0, {"error": str(exc)}
    else:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_body = resp.read().decode("utf-8")
                try:
                    resp_json = json.loads(resp_body)
                except Exception:
                    resp_json = {"raw": resp_body}
                return resp.status, resp_json
        except urllib.error.HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8")
                resp_json = json.loads(err_body)
            except Exception:
                resp_json = {"error": str(exc)}
            return exc.code, resp_json
        except Exception as exc:
            logger.debug("urllib GET failed: %s", exc)
            return 0, {"error": str(exc)}


# ---------------------------------------------------------------------------
# Metrics Collection
# ---------------------------------------------------------------------------


def get_cpu_usage():
    """
    Return CPU usage as a float percentage (0-100).
    Linux: read /proc/loadavg 1-min average divided by cpu_count.
    Falls back to 0.0 on non-Linux or errors.
    """
    try:
        with open("/proc/loadavg", "r") as fh:
            load_1m = float(fh.read().split()[0])
        cpu_count = os.cpu_count() or 1
        usage = (load_1m / cpu_count) * 100.0
        return round(min(usage, 100.0), 1)
    except Exception:
        return 0.0


def get_memory_usage():
    """
    Return memory usage as a float percentage (0-100).
    Linux: parse /proc/meminfo for MemTotal and MemAvailable.
    Falls back to 0.0 on non-Linux or errors.
    """
    try:
        mem = {}
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    mem[key] = int(parts[1])  # value in kB
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        if total <= 0:
            return 0.0
        used_pct = ((total - available) / total) * 100.0
        return round(used_pct, 1)
    except Exception:
        return 0.0


def get_gpu_usage():
    """
    Return GPU utilization as a float percentage, or None if no NVIDIA GPU.
    Calls: nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Take the first GPU line
            val = result.stdout.strip().split("\n")[0].strip()
            return round(float(val), 1)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


def get_ollama_models(ollama_host):
    """
    Query the Ollama API for loaded models.
    Returns a list of dicts: [{"name": "llama3:latest", "size_gb": 4.1}, ...]
    Returns empty list on failure.
    """
    url = f"{ollama_host.rstrip('/')}/api/tags"
    status, data = http_get(url)
    if status != 200 or not isinstance(data, dict):
        return []

    models = []
    for m in data.get("models", []):
        name = m.get("name", "unknown")
        size_bytes = m.get("size", 0)
        size_gb = round(size_bytes / (1024**3), 2) if size_bytes else 0.0
        models.append({"name": name, "size_gb": size_gb})
    return models


def get_ollama_status():
    """Query local Ollama for loaded and available models."""
    ollama_host = os.getenv("OLLAMA_HOST", "http://ollama:11434")
    result = {"loaded_models": [], "available_models": []}
    try:
        tags_status, tags = http_get(f"{ollama_host}/api/tags")
        if tags_status == 200 and isinstance(tags, dict) and "models" in tags:
            result["available_models"] = [
                {"name": m["name"], "size_gb": round(m["size"] / (1024**3), 2)}
                for m in tags["models"]
            ]
        ps_status, ps = http_get(f"{ollama_host}/api/ps")
        if ps_status == 200 and isinstance(ps, dict) and "models" in ps:
            result["loaded_models"] = [m["name"] for m in ps["models"]]
    except Exception as e:
        logger.warning(f"Ollama status check failed: {e}")
    return result


# ---------------------------------------------------------------------------
# Sync Operations
# ---------------------------------------------------------------------------


def _auth_headers(config):
    """Return standard auth headers for Hub API calls."""
    return {
        "X-Node-API-Key": config["hub_api_key"],
        "Content-Type": "application/json",
    }


def _get_idle_agents():
    """Query local DB for agents not currently running a job."""
    conn = _get_node_db()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT nac.agent_name, nac.model, nac.station_codes, nac.capabilities
            FROM node_agent_configs nac
            WHERE NOT EXISTS (
                SELECT 1 FROM node_jobs nj
                WHERE nj.agent_name = nac.agent_name AND nj.status = 'running'
            )
            """
        )
        agents = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return agents
    except Exception as e:
        logger.warning("Failed to query idle agents: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return []


def _get_agent_welfare():
    """Get local agent welfare state for heartbeat reporting.

    Returns dict: {agent_name: {stress, energy, shift_state, task_count, model_loaded}}
    """
    conn = _get_node_db()
    if not conn:
        return {}
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT nac.agent_name, nac.model,
                   COUNT(nj.id) FILTER (WHERE nj.status = 'running') AS task_count
            FROM node_agent_configs nac
            LEFT JOIN node_jobs nj ON nj.agent_name = nac.agent_name
            GROUP BY nac.agent_name, nac.model
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Check which models are loaded in Ollama
        ollama_host = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
        loaded_models = set()
        try:
            ps_status, ps_data = http_get(f"{ollama_host}/api/ps")
            if ps_status == 200 and isinstance(ps_data, dict):
                loaded_models = {
                    m["name"].split(":")[0] for m in ps_data.get("models", [])
                }
        except Exception:
            pass

        welfare = {}
        for row in rows:
            model_base = (row["model"] or "").split(":")[0]
            welfare[row["agent_name"]] = {
                "stress": 0.0,  # Node agents don't have emotional state yet
                "energy": 1.0,
                "shift_state": "active",
                "task_count": row["task_count"] or 0,
                "model_loaded": model_base in loaded_models,
            }
        return welfare
    except Exception as e:
        logger.warning("Failed to get agent welfare: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return {}


def send_heartbeat(config):
    """
    POST heartbeat with metrics to the Hub.
    Endpoint: /tools/starbase/api/nodes/{node_id}/heartbeat
    """
    cpu = get_cpu_usage()
    mem = get_memory_usage()
    gpu = get_gpu_usage()
    models = get_ollama_models(config["ollama_host"])

    payload = {
        "status": "online",
        "current_load": cpu,
        "cpu_usage": cpu,
        "memory_usage": mem,
        "gpu_usage": gpu if gpu is not None else 0,
        "ollama_online": len(models) > 0 or _check_ollama_alive(config["ollama_host"]),
        "ollama_models": [
            {"name": m["name"], "size": int(m["size_gb"] * (1024**3))} for m in models
        ],
        "client_version": CLIENT_VERSION,
        "archie_version": config["archie_version"],
        "deployment_mode": os.getenv("DEPLOYMENT_MODE", "starship"),
        "ollama": get_ollama_status(),
        "details": {
            "hostname": _get_hostname(),
            "uptime": _get_uptime(),
            "sync_service": True,
        },
    }

    # Check if ComfyUI is available
    comfyui_port = os.environ.get("COMFYUI_PORT", "8188")
    comfyui_available = False
    try:
        comfyui_status, _ = http_get(f"http://comfyui:{comfyui_port}/system_stats")
        if comfyui_status == 200:
            comfyui_available = True
    except Exception:
        pass

    payload["comfyui_available"] = comfyui_available
    if comfyui_available:
        payload["comfyui_port"] = int(comfyui_port)

    # Report SSH status
    ssh_enabled = False
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "sshd"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        ssh_enabled = result.stdout.strip() == "active"
    except Exception:
        pass
    payload["ssh_enabled"] = ssh_enabled

    # Advertise idle agents for mesh sharing
    idle_agents = _get_idle_agents()
    if idle_agents:
        payload["idle_agents"] = idle_agents

    # Fleet coordination: report completed jobs since last heartbeat
    global _completed_jobs
    if _completed_jobs:
        payload["completed_jobs"] = _completed_jobs
        _completed_jobs = []  # Clear after sending

    # Fleet coordination: report agent welfare state
    agent_welfare = _get_agent_welfare()
    if agent_welfare:
        payload["agent_welfare"] = agent_welfare

    url = f"{config['hub_url']}/tools/starbase/api/nodes/{config['node_id']}/heartbeat"
    status, resp = http_post(url, payload, _auth_headers(config))

    if 200 <= status < 300:
        gpu_str = f"{gpu}%" if gpu is not None else "N/A"
        logger.info(
            "Heartbeat sent — CPU: %.1f%% | RAM: %.1f%% | GPU: %s | Models: %d",
            cpu,
            mem,
            gpu_str,
            len(models),
        )
        return True
    else:
        logger.warning("Heartbeat failed (HTTP %d): %s", status, resp)
        return False


def report_version(config):
    """
    POST code version to the Hub on startup.
    Endpoint: /tools/starbase/api/mesh/version
    """
    payload = {
        "node_id": config["node_id"],
        "version": config["archie_version"],
    }
    url = f"{config['hub_url']}/tools/starbase/api/mesh/version"
    status, resp = http_post(url, payload, _auth_headers(config))

    if 200 <= status < 300:
        logger.info("Version reported to Hub: %s", config["archie_version"])
        return True
    else:
        logger.warning("Version report failed (HTTP %d): %s", status, resp)
        return False


def poll_syncs(config):
    """
    GET pending sync commands from the Hub and process each one.
    Endpoint: /tools/starbase/api/mesh/sync/{node_id}/pending
    """
    url = f"{config['hub_url']}/tools/starbase/api/mesh/sync/{config['node_id']}/pending"
    status, resp = http_get(url, _auth_headers(config))

    if status != 200:
        logger.warning("Sync poll failed (HTTP %d): %s", status, resp)
        return

    syncs = resp.get("syncs", [])
    if not syncs:
        return

    logger.info("Received %d pending sync(s)", len(syncs))

    for sync_item in syncs:
        sync_id = sync_item.get("id")
        sync_type = sync_item.get("sync_type", "unknown")
        payload = sync_item.get("payload", {})

        logger.info("Processing sync #%s type=%s", sync_id, sync_type)

        ack_status = "acknowledged"
        error_message = None
        handler_result = {}
        try:
            handler_result = handle_sync(config, sync_type, payload) or {}
            ack_status = handler_result.get("status", "acknowledged")
            error_message = handler_result.get("error")
        except Exception as exc:
            logger.error("Sync #%s handler failed: %s", sync_id, exc)
            ack_status = "failed"
            error_message = str(exc)

        # Acknowledge the sync (include handler output for job results)
        ack_url = f"{config['hub_url']}/tools/starbase/api/mesh/sync/{sync_id}/ack"
        ack_payload = {
            "node_id": config["node_id"],
            "status": ack_status,
            "error_message": error_message,
            "result": handler_result,
        }
        ack_code, ack_resp = http_post(ack_url, ack_payload, _auth_headers(config))
        if 200 <= ack_code < 300:
            logger.info("Sync #%s acknowledged (%s)", sync_id, ack_status)
        else:
            logger.warning(
                "Sync #%s ack failed (HTTP %d): %s", sync_id, ack_code, ack_resp
            )


def handle_sync(config, sync_type, payload):
    """
    Dispatch a sync command to the appropriate handler.
    Returns a dict with at least {status: str} for the ACK payload.
    """
    handlers = {
        "code_update": _handle_code_update,
        "config_update": _handle_config_update,
        "container_restart": _handle_container_restart,
        "iaae_policy": _handle_iaae_policy,
        "model_recommend": _handle_model_recommend,
        "agent_config": _handle_agent_config,
        "job_request": _handle_job_request,
        "model_pull": _handle_model_pull,
        "shell_exec": _handle_shell_exec,
        "ssh_toggle": _handle_ssh_toggle,
        "comfyui_setup": _handle_comfyui_setup,
    }

    handler = handlers.get(sync_type)
    if handler:
        return handler(config, payload)
    else:
        logger.warning("Unknown sync_type '%s' — skipping", sync_type)
        return {"status": "skipped", "error": f"Unknown sync_type: {sync_type}"}


def _restart_container(name):
    """
    Restart a Docker container by name using the Docker Engine API via socket.
    Returns (success: bool, message: str).
    """
    import http.client

    try:
        # Use Unix socket to talk to Docker daemon
        sock_path = "/var/run/docker.sock"
        if not os.path.exists(sock_path):
            return False, "Docker socket not found at /var/run/docker.sock"

        conn = http.client.HTTPConnection("localhost")
        # Override the connection to use the Unix socket
        import socket

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(sock_path)
        conn.sock = sock

        conn.request("POST", f"/containers/{name}/restart?t=5")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        conn.close()

        if resp.status == 204:
            return True, f"Container {name} restarted"
        else:
            return False, f"HTTP {resp.status}: {body[:200]}"
    except Exception as e:
        return False, str(e)


def _handle_container_restart(config, payload):
    """
    Restart one or more Docker containers by name.

    Expected payload:
        containers (list[str]): Container names to restart.
            e.g. ["archie_starship_api", "archie_starship_sync"]
    """
    containers = payload.get("containers", [])
    if not containers:
        return {"status": "skipped", "error": "No containers specified"}

    results = {}
    for name in containers:
        ok, msg = _restart_container(name)
        results[name] = {"success": ok, "message": msg}
        logger.info("[container_restart] %s: %s", name, msg)

    all_ok = all(r["success"] for r in results.values())
    return {
        "status": "completed" if all_ok else "completed_with_errors",
        "results": results,
    }


def _handle_code_update(config, payload):
    """
    Handle a code_update sync command from the Hub.

    Downloads updated Python files and migrations from the hub,
    applies any new migrations to local Postgres, then exits
    so Docker auto-restarts the container with the new code.

    Expected payload:
        version (str): Target version string
        files (list[str]): File names to update, e.g. ["node_sync.py", "node_api.py"]
        migrations (list[str]): Migration filenames to download + apply
    """
    version = payload.get("version", "unknown")
    files = payload.get("files", ["node_sync.py", "node_api.py"])
    migrations = payload.get("migrations", [])

    logger.info("[code_update] Updating to version %s", version)

    hub_url = config["hub_url"]
    headers = _auth_headers(config)
    updated = []
    errors = []

    # --- Download updated Python files ---
    for fname in files:
        url = f"{hub_url}/tools/starbase/api/nodes/{fname}"
        logger.info("[code_update] Downloading %s", fname)
        status, resp = http_get(url, headers)
        if status == 200:
            # http_get returns parsed JSON or {"raw": text}
            content = resp.get("raw", "")
            if content:
                try:
                    fpath = os.path.join("/app", fname)
                    with open(fpath, "w") as fh:
                        fh.write(content)
                    updated.append(fname)
                    logger.info("[code_update] Updated %s", fname)
                except Exception as e:
                    errors.append(f"{fname}: write failed: {e}")
                    logger.error("[code_update] Failed to write %s: %s", fname, e)
            else:
                errors.append(f"{fname}: empty response")
        else:
            errors.append(f"{fname}: HTTP {status}")
            logger.warning("[code_update] Failed to download %s (HTTP %d)", fname, status)

    # --- Download and apply migrations ---
    for mig_name in migrations:
        url = f"{hub_url}/tools/starbase/api/nodes/migrations/{mig_name}"
        logger.info("[code_update] Downloading migration %s", mig_name)
        status, resp = http_get(url, headers)
        if status == 200:
            sql_content = resp.get("raw", "")
            if sql_content:
                mig_path = os.path.join("/app/migrations", mig_name)
                try:
                    with open(mig_path, "w") as fh:
                        fh.write(sql_content)
                    logger.info("[code_update] Saved migration %s", mig_name)
                except Exception as e:
                    errors.append(f"migration {mig_name}: write failed: {e}")
                    continue

                # Apply migration to local Postgres
                conn = _get_node_db()
                if conn:
                    try:
                        conn.autocommit = True
                        cur = conn.cursor()
                        cur.execute(sql_content)
                        cur.close()
                        conn.close()
                        updated.append(f"migration:{mig_name}")
                        logger.info("[code_update] Applied migration %s", mig_name)
                    except Exception as e:
                        errors.append(f"migration {mig_name}: apply failed: {e}")
                        logger.error(
                            "[code_update] Failed to apply %s: %s", mig_name, e
                        )
                        try:
                            conn.close()
                        except Exception:
                            pass
                else:
                    errors.append(f"migration {mig_name}: no DB connection")
        else:
            errors.append(f"migration {mig_name}: HTTP {status}")

    result = {
        "status": "completed" if not errors else "completed_with_errors",
        "version": version,
        "updated": updated,
        "errors": errors,
    }
    logger.info("[code_update] Result: %s", result)

    # If we updated code files, restart affected containers
    code_files_updated = [f for f in updated if not f.startswith("migration:")]
    if code_files_updated:
        logger.info(
            "[code_update] Code files updated (%s) — restarting containers...",
            ", ".join(code_files_updated),
        )

        # Restart node_api first (it doesn't affect us)
        if "node_api.py" in code_files_updated:
            ok, msg = _restart_container("archie_starship_api")
            logger.info("[code_update] node_api restart: %s", msg)
            result["api_restart"] = msg

        # If sync code changed, exit so Docker restarts us with new code
        if "node_sync.py" in code_files_updated:

            def _delayed_exit():
                time.sleep(3)
                logger.info("[code_update] Exiting for restart.")
                os._exit(0)

            import threading

            threading.Thread(target=_delayed_exit, daemon=True).start()

    return result


def _handle_config_update(config, payload):
    """
    Handle config_update sync — merge new config values and write to config.json.

    Expected payload: dict of config fields to update, e.g.
        {"hub_url": "http://...", "heartbeat_interval": 30}
    """
    if not payload:
        return {"status": "failed", "error": "Empty config payload"}

    logger.info(
        "[config_update] Updating config with keys: %s", list(payload.keys())
    )

    # Reload into the running config dict (in-memory update)
    key_map = {
        "node_id": "node_id",
        "hub_url": "hub_url",
        "server_url": "hub_url",
        "hub_api_key": "hub_api_key",
        "api_key": "hub_api_key",
        "ollama_host": "ollama_host",
        "heartbeat_interval": "heartbeat_interval",
        "sync_poll_interval": "sync_poll_interval",
        "archie_version": "archie_version",
    }
    updated_keys = []
    for file_key, internal_key in key_map.items():
        if file_key in payload:
            val = payload[file_key]
            if internal_key in ("heartbeat_interval", "sync_poll_interval"):
                val = int(val)
            old_val = config.get(internal_key)
            config[internal_key] = val
            updated_keys.append(internal_key)
            if old_val != val:
                logger.info("[config_update] %s: %s -> %s", internal_key, old_val, val)

    # Strip trailing slash from hub_url if updated
    if "hub_url" in config:
        config["hub_url"] = config["hub_url"].rstrip("/")

    # Write updated config to disk using the unified write_config function
    write_config(config)

    logger.info("[config_update] Updated keys: %s", updated_keys)

    return {
        "status": "acknowledged",
        "updated_keys": updated_keys,
    }


def _handle_iaae_policy(config, payload):
    """Stub: handle an iaae_policy sync command from the Hub."""
    policy_name = payload.get("policy_name", "unknown")
    logger.info(
        "[iaae_policy] Received policy '%s' — stub, no action taken", policy_name
    )
    return {"status": "acknowledged"}


def _handle_model_recommend(config, payload):
    """Stub: handle a model_recommend sync command from the Hub."""
    model = payload.get("model", "unknown")
    logger.info(
        "[model_recommend] Hub recommends model '%s' — stub, no action taken", model
    )
    return {"status": "acknowledged"}


def _handle_agent_config(config, payload):
    """Handle agent_config sync — save crew manifest to local Postgres."""
    agents = payload.get("agents", [])
    if not agents:
        logger.warning("[agent_config] Empty agents list — skipping")
        return {"status": "failed", "error": "Empty agents list"}

    conn = _get_node_db()
    if not conn:
        logger.error("[agent_config] No local DB — cannot save agent configs")
        return {"status": "failed", "error": "Local database unavailable"}

    try:
        cur = conn.cursor()
        saved = 0
        for agent in agents:
            cur.execute(
                """
                INSERT INTO node_agent_configs
                    (agent_name, display_name, model, system_prompt,
                     station_codes, capabilities, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (agent_name) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    model = EXCLUDED.model,
                    system_prompt = EXCLUDED.system_prompt,
                    station_codes = EXCLUDED.station_codes,
                    capabilities = EXCLUDED.capabilities,
                    updated_at = NOW()
                """,
                (
                    agent["name"],
                    agent.get("display_name", agent["name"]),
                    agent.get("model", "mistral:latest"),
                    agent.get("system_prompt", ""),
                    list(agent.get("station_codes", [])),
                    [json.dumps(c) if isinstance(c, dict) else str(c) for c in agent.get("capabilities", [])],
                ),
            )
            saved += 1
        conn.commit()
        cur.close()
        conn.close()
        logger.info("[agent_config] Saved %d agent configs to local DB", saved)
        return {"status": "acknowledged", "agents_saved": saved}
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error("[agent_config] Failed to save: %s", e)
        return {"status": "failed", "error": str(e)}


def _handle_job_request(config, payload):
    """Handle job_request sync — save job to local DB and execute via Ollama."""
    job_id = payload.get("job_id")
    agent_name = payload.get("agent_name")
    prompt = payload.get("prompt", "")
    timeout = payload.get("timeout_seconds", 300)

    if not agent_name or not prompt:
        return {"status": "failed", "error": "Missing agent_name or prompt"}

    conn = _get_node_db()
    if not conn:
        return {"status": "failed", "error": "Local database unavailable"}

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Save job to local DB
        cur.execute(
            """
            INSERT INTO node_jobs
                (hub_job_id, agent_name, job_type, description, prompt,
                 timeout_seconds, status, started_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'running', NOW())
            RETURNING id
            """,
            (
                job_id,
                agent_name,
                payload.get("job_type", "inference"),
                payload.get("description", ""),
                prompt,
                timeout,
            ),
        )
        local_job_id = cur.fetchone()["id"]
        conn.commit()

        # Look up agent config for model + system_prompt
        cur.execute(
            "SELECT model, system_prompt FROM node_agent_configs WHERE agent_name = %s",
            (agent_name,),
        )
        agent_cfg = cur.fetchone()
        if not agent_cfg:
            cur.execute(
                "UPDATE node_jobs SET status = 'failed', "
                "error_message = 'Agent not configured', "
                "completed_at = NOW() WHERE id = %s",
                (local_job_id,),
            )
            conn.commit()
            cur.close()
            conn.close()
            return {
                "status": "failed",
                "error": f"Agent '{agent_name}' not configured on this node",
            }

        model = agent_cfg["model"]
        system_prompt = agent_cfg["system_prompt"] or ""

        # Call Ollama
        ollama_host = config.get("ollama_host", "http://ollama:11434")
        ollama_payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system_prompt:
            ollama_payload["system"] = system_prompt

        logger.info(
            "[job_request] Executing job %s on agent '%s' (model: %s)",
            job_id,
            agent_name,
            model,
        )

        try:
            start = time.time()
            status_code, resp = http_post(
                f"{ollama_host}/api/generate",
                ollama_payload,
                timeout=timeout,
            )
            elapsed = time.time() - start

            if status_code == 200 and isinstance(resp, dict):
                output = resp.get("response", "")
                cur.execute(
                    "UPDATE node_jobs SET status = 'completed', "
                    "output = %s, completed_at = NOW() WHERE id = %s",
                    (output, local_job_id),
                )
                conn.commit()
                duration_ms = int(elapsed * 1000)
                logger.info(
                    "[job_request] Job %s completed in %.1fs (%d chars)",
                    job_id,
                    elapsed,
                    len(output),
                )

                # Track for heartbeat reporting
                _completed_jobs.append(
                    {
                        "agent_name": agent_name,
                        "capability": payload.get("capability", "unknown"),
                        "success": True,
                        "duration_ms": duration_ms,
                        "station_code": payload.get("station_code", "UNKNOWN"),
                    }
                )

                result = {
                    "status": "completed",
                    "output": output,
                    "elapsed_seconds": round(elapsed, 1),
                }
            else:
                error = f"Ollama returned HTTP {status_code}"
                cur.execute(
                    "UPDATE node_jobs SET status = 'failed', "
                    "error_message = %s, completed_at = NOW() WHERE id = %s",
                    (error, local_job_id),
                )
                conn.commit()
                result = {"status": "failed", "error": error}

        except Exception as ollama_err:
            error = f"Ollama call failed: {ollama_err}"
            cur.execute(
                "UPDATE node_jobs SET status = 'failed', "
                "error_message = %s, completed_at = NOW() WHERE id = %s",
                (error, local_job_id),
            )
            conn.commit()

            # Track failed job for heartbeat reporting
            _completed_jobs.append(
                {
                    "agent_name": agent_name,
                    "capability": payload.get("capability", "unknown"),
                    "success": False,
                    "duration_ms": int((time.time() - start) * 1000),
                    "station_code": payload.get("station_code", "UNKNOWN"),
                }
            )

            result = {"status": "failed", "error": error}

        cur.close()
        conn.close()
        return result

    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error("[job_request] Failed: %s", e)
        return {"status": "failed", "error": str(e)}


def _handle_model_pull(config, payload):
    """Pull an Ollama model on the node."""
    model_name = payload.get("model_name")
    if not model_name:
        return {"status": "error", "error": "No model_name in payload"}

    ollama_host = config.get("ollama_host", "http://ollama:11434")
    logger.info("[model_pull] Pulling model '%s' from %s", model_name, ollama_host)

    pull_data = {"name": model_name, "stream": False}
    timeout = 1800  # 30 minutes — model pulls can be very slow

    try:
        if _HAS_REQUESTS:
            resp = _requests_lib.post(
                f"{ollama_host}/api/pull", json=pull_data, timeout=timeout
            )
            try:
                resp_json = resp.json()
            except Exception:
                resp_json = {"raw": resp.text}
        else:
            body = json.dumps(pull_data).encode("utf-8")
            req = urllib.request.Request(
                f"{ollama_host}/api/pull",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp_json = json.loads(r.read().decode("utf-8"))

        logger.info("[model_pull] Pull response for '%s': %s", model_name, resp_json)
        return {"status": "completed", "model": model_name, "response": str(resp_json)}
    except Exception as e:
        logger.error("[model_pull] Failed to pull '%s': %s", model_name, e)
        return {"status": "error", "error": str(e)}


def _handle_shell_exec(config, payload):
    """
    Execute a shell command on the node with timeout.
    Only accepts commands from authenticated hub sync channel.

    Expected payload:
        command (str): Shell command to execute
        timeout (int): Timeout in seconds (default 30, max 300)
    """
    command = payload.get("command")
    if not command:
        return {"status": "failed", "error": "No command specified"}

    timeout = min(int(payload.get("timeout", 30)), 300)

    # Safety: block obviously dangerous commands
    blocked = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd"]
    for pattern in blocked:
        if pattern in command:
            logger.warning("[shell_exec] Blocked dangerous command: %s", command)
            return {"status": "failed", "error": "Command blocked by safety filter"}

    logger.info("[shell_exec] Executing: %s (timeout=%ds)", command, timeout)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        logger.info(
            "[shell_exec] Exit code %d, output: %s",
            result.returncode,
            output[:500],
        )
        return {
            "status": "completed" if result.returncode == 0 else "completed_with_errors",
            "exit_code": result.returncode,
            "output": output[:2000],
        }
    except subprocess.TimeoutExpired:
        logger.error("[shell_exec] Command timed out after %ds", timeout)
        return {"status": "failed", "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        logger.error("[shell_exec] Failed: %s", e)
        return {"status": "failed", "error": str(e)}


def _handle_ssh_toggle(config, payload):
    """
    Enable or disable SSH access on the node.

    Expected payload:
        enabled (bool): True to enable, False to disable
        hub_public_key (str): SSH public key to add when enabling (optional)
        timeout_minutes (int): Auto-disable after N minutes (default 60)
    """
    enabled = payload.get("enabled", False)
    hub_key = payload.get("hub_public_key", "")
    timeout_min = int(payload.get("timeout_minutes", 60))

    logger.info("[ssh_toggle] Setting SSH %s", "enabled" if enabled else "disabled")

    try:
        if enabled:
            # Start SSH service
            subprocess.run(
                ["systemctl", "start", "sshd"],
                capture_output=True,
                text=True,
                timeout=15,
            )

            # Add hub public key if provided
            if hub_key:
                ssh_dir = os.path.expanduser("~/.ssh")
                os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
                auth_keys = os.path.join(ssh_dir, "authorized_keys")
                existing = ""
                if os.path.isfile(auth_keys):
                    with open(auth_keys, "r") as f:
                        existing = f.read()
                if hub_key.strip() not in existing:
                    with open(auth_keys, "a") as f:
                        f.write(f"\n{hub_key.strip()}\n")
                    os.chmod(auth_keys, 0o600)

            # Schedule auto-disable
            if timeout_min > 0:
                import threading

                def _auto_disable():
                    time.sleep(timeout_min * 60)
                    logger.info("[ssh_toggle] Auto-disabling SSH after %dm", timeout_min)
                    subprocess.run(
                        ["systemctl", "stop", "sshd"],
                        capture_output=True,
                        timeout=15,
                    )

                threading.Thread(target=_auto_disable, daemon=True).start()
                logger.info(
                    "[ssh_toggle] SSH enabled, auto-disable in %dm", timeout_min
                )

            return {
                "status": "completed",
                "ssh_enabled": True,
                "auto_disable_minutes": timeout_min,
            }
        else:
            subprocess.run(
                ["systemctl", "stop", "sshd"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return {"status": "completed", "ssh_enabled": False}

    except Exception as e:
        logger.error("[ssh_toggle] Failed: %s", e)
        return {"status": "failed", "error": str(e)}


def _docker_api(method, path, body=None, timeout=30, stream=False):
    """
    Call the Docker Engine API via Unix socket.
    Returns (status_code, response_body_str).
    If stream=True, reads the full streaming response (for image pulls).
    """
    import http.client
    import socket as _socket

    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return 0, "Docker socket not found"

    conn = http.client.HTTPConnection("localhost", timeout=timeout)
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(sock_path)
    conn.sock = sock

    headers = {"Content-Type": "application/json"} if body else {}
    encoded = json.dumps(body).encode("utf-8") if body else None
    conn.request(method, path, body=encoded, headers=headers)
    resp = conn.getresponse()

    if stream:
        # Read full streaming response (image pulls send chunked JSON lines)
        chunks = []
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
        resp_body = b"".join(chunks).decode("utf-8", errors="replace")
    else:
        resp_body = resp.read().decode("utf-8", errors="replace")

    status = resp.status
    conn.close()
    return status, resp_body


def _handle_comfyui_setup(config, payload):
    """
    Set up ComfyUI on the node via Docker Engine API (Unix socket).

    Expected payload:
        action (str): 'start', 'stop', or 'status' (default 'start')
        port (int): ComfyUI port (default 8188)
        gpu (bool): Enable GPU (default True)
    """
    action = payload.get("action", "start")
    port = int(payload.get("port", 8188))
    use_gpu = payload.get("gpu", True)

    container_name = "archie_starship_comfyui"
    image = payload.get("image", "yanwk/comfyui-boot:latest")
    logger.info("[comfyui_setup] Action: %s, image: %s", action, image)

    if action == "status":
        try:
            code, body = _docker_api("GET", f"/containers/{container_name}/json")
            if code == 200:
                info = json.loads(body)
                running = info.get("State", {}).get("Running", False)
                return {"status": "completed", "comfyui_running": running, "port": port}
            return {"status": "completed", "comfyui_running": False, "port": port}
        except Exception:
            return {"status": "completed", "comfyui_running": False, "port": port}

    elif action == "stop":
        try:
            code, body = _docker_api("POST", f"/containers/{container_name}/stop?t=10")
            stopped = code in (204, 304)
            return {
                "status": "completed" if stopped else "failed",
                "comfyui_running": not stopped,
                "detail": f"HTTP {code}",
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    elif action == "start":
        # Step 1: Pull image via Docker API
        logger.info("[comfyui_setup] Pulling image %s ...", image)
        try:
            import urllib.parse
            # Split image:tag for Docker API
            if ":" in image:
                img_name, img_tag = image.rsplit(":", 1)
            else:
                img_name, img_tag = image, "latest"
            encoded_name = urllib.parse.quote(img_name, safe="")
            code, body = _docker_api(
                "POST", f"/images/create?fromImage={encoded_name}&tag={img_tag}",
                timeout=600, stream=True,
            )
            if code not in (200, 201):
                logger.warning("[comfyui_setup] Pull returned HTTP %d: %s", code, body[:300])
        except Exception as e:
            logger.warning("[comfyui_setup] Pull failed (continuing): %s", e)

        # Step 2: Remove existing container
        _docker_api("POST", f"/containers/{container_name}/stop?t=5")
        _docker_api("DELETE", f"/containers/{container_name}?force=true")

        # Step 3: Detect the Docker network used by our sync container
        network_name = "bridge"  # fallback
        try:
            code, body = _docker_api("GET", "/containers/archie_starship_sync/json")
            if code == 200:
                info = json.loads(body)
                networks = info.get("NetworkSettings", {}).get("Networks", {})
                if networks:
                    network_name = list(networks.keys())[0]
                    logger.info("[comfyui_setup] Detected network: %s", network_name)
        except Exception as e:
            logger.warning("[comfyui_setup] Network detection failed, using bridge: %s", e)

        # Create container via API
        create_body = {
            "Image": image,
            "ExposedPorts": {"8188/tcp": {}},
            "HostConfig": {
                "PortBindings": {
                    "8188/tcp": [{"HostPort": str(port)}]
                },
                "RestartPolicy": {"Name": "unless-stopped"},
                "NetworkMode": network_name,
            },
            "NetworkingConfig": {
                "EndpointsConfig": {
                    network_name: {
                        "Aliases": ["comfyui"],
                    }
                }
            },
        }
        if use_gpu:
            create_body["HostConfig"]["DeviceRequests"] = [
                {
                    "Driver": "",
                    "Count": -1,
                    "Capabilities": [["gpu"]],
                }
            ]

        logger.info("[comfyui_setup] Creating container %s", container_name)
        code, body = _docker_api(
            "POST",
            f"/containers/create?name={container_name}",
            body=create_body,
            timeout=30,
        )
        if code not in (201, 200):
            error = body[:500]
            logger.error("[comfyui_setup] Create failed (HTTP %d): %s", code, error)
            return {"status": "failed", "error": error}

        # Step 4: Start the container
        code, body = _docker_api("POST", f"/containers/{container_name}/start")
        if code in (204, 304):
            logger.info("[comfyui_setup] ComfyUI started on port %d", port)
            return {
                "status": "completed",
                "comfyui_running": True,
                "port": port,
                "container": container_name,
            }
        else:
            error = body[:500]
            logger.error("[comfyui_setup] Start failed (HTTP %d): %s", code, error)
            return {"status": "failed", "error": error}

    elif action == "download_model":
        # Download a checkpoint model into the ComfyUI container
        model_url = payload.get("url")
        model_name = payload.get("model_name")
        model_dir = payload.get("model_dir", "checkpoints")
        if not model_url or not model_name:
            return {"status": "failed", "error": "url and model_name required"}

        logger.info(
            "[comfyui_setup] Downloading model %s → %s", model_name, model_dir
        )

        # Use Python inside the ComfyUI container (guaranteed available)
        python_script = (
            "import urllib.request, os; "
            f"os.makedirs('/app/models/{model_dir}', exist_ok=True); "
            f"urllib.request.urlretrieve('{model_url}', "
            f"'/app/models/{model_dir}/{model_name}'); "
            f"sz = os.path.getsize('/app/models/{model_dir}/{model_name}'); "
            f"print(f'Downloaded {{sz}} bytes')"
        )
        exec_body = {
            "AttachStdout": True,
            "AttachStderr": True,
            "Cmd": ["python3", "-c", python_script],
        }
        code, body = _docker_api(
            "POST",
            f"/containers/{container_name}/exec",
            body=exec_body,
            timeout=30,
        )
        if code != 201:
            return {"status": "failed", "error": f"Exec create failed: {body[:300]}"}

        exec_id = json.loads(body).get("Id")
        if not exec_id:
            return {"status": "failed", "error": "No exec ID returned"}

        # Start the exec (blocks until download completes)
        logger.info(
            "[comfyui_setup] Download started for %s (may take 10-15min for large models)",
            model_name,
        )
        code, body = _docker_api(
            "POST",
            f"/exec/{exec_id}/start",
            body={"Detach": False},
            timeout=1800,  # 30 min for large models
            stream=True,
        )

        # Check exec result
        code, body = _docker_api("GET", f"/exec/{exec_id}/json")
        if code == 200:
            info = json.loads(body)
            exit_code = info.get("ExitCode", -1)
            if exit_code == 0:
                logger.info(
                    "[comfyui_setup] Model %s downloaded successfully", model_name
                )
                return {
                    "status": "completed",
                    "model_name": model_name,
                    "model_dir": model_dir,
                }
            else:
                return {
                    "status": "failed",
                    "error": f"Download exited with code {exit_code}",
                }

        return {"status": "failed", "error": f"Exec inspect failed: {body[:300]}"}

    return {"status": "failed", "error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _get_hostname():
    """Return the system hostname."""
    try:
        import socket

        return socket.gethostname()
    except Exception:
        return "unknown"


def _get_uptime():
    """Return system uptime in seconds (Linux), or 0."""
    try:
        with open("/proc/uptime", "r") as fh:
            return int(float(fh.read().split()[0]))
    except Exception:
        return 0


def _check_ollama_alive(ollama_host):
    """Quick check if Ollama is reachable (GET /api/tags returns 200)."""
    try:
        url = f"{ollama_host.rstrip('/')}/api/tags"
        status, _ = http_get(url)
        return status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------


def _attempt_re_registration(config):
    """
    Attempt to re-register with the hub using our existing node_id.
    Returns True on success.
    """
    url = f"{config['hub_url']}/tools/starbase/api/nodes/register"
    payload = {
        "node_id": config["node_id"],
        "node_name": _get_hostname(),
        "hostname": _get_hostname(),
        "port": 11434,
        "client_version": CLIENT_VERSION,
        "re_register": True,
    }
    logger.info("Attempting re-registration with hub at %s", url)
    status, resp = http_post(url, payload, _auth_headers(config))
    if 200 <= status < 300:
        logger.info("Re-registration successful: %s", resp)
        # Update config with any new values from hub
        if isinstance(resp, dict):
            if resp.get("api_key"):
                config["hub_api_key"] = resp["api_key"]
            if resp.get("node_id"):
                config["node_id"] = resp["node_id"]
            write_config(config)
        return True
    else:
        logger.warning("Re-registration failed (HTTP %d): %s", status, resp)
        return False


def main():
    logger.info("=" * 60)
    logger.info("A.R.C.H.I.E. Unified Node Client v%s starting...", CLIENT_VERSION)
    logger.info("=" * 60)

    config = load_config()

    logger.info("Node ID:            %s", config["node_id"])
    logger.info("Hub URL:            %s", config["hub_url"])
    logger.info("Ollama Host:        %s", config["ollama_host"])
    logger.info("Heartbeat Interval: %ds", config["heartbeat_interval"])
    logger.info("Sync Poll Interval: %ds", config["sync_poll_interval"])
    logger.info("Version:            %s", config["archie_version"])
    logger.info("Client Version:     %s", CLIENT_VERSION)
    logger.info("Platform:           %s", platform.system())
    logger.info("Config Path:        %s", config.get("_config_path", "N/A"))
    logger.info("HTTP backend:       %s", "requests" if _HAS_REQUESTS else "urllib")

    # Report version on startup
    report_version(config)

    last_heartbeat = 0.0
    last_sync_poll = 0.0

    # Self-healing state
    heartbeat_failures = 0
    base_heartbeat_interval = config["heartbeat_interval"]
    current_heartbeat_interval = base_heartbeat_interval

    logger.info("Entering main loop...")

    while True:
        now = time.time()

        # Heartbeat check (with self-healing)
        if now - last_heartbeat >= current_heartbeat_interval:
            try:
                success = send_heartbeat(config)
                if success:
                    # Reset failure tracking on success
                    if heartbeat_failures > 0:
                        logger.info(
                            "Heartbeat recovered after %d failures", heartbeat_failures
                        )
                    heartbeat_failures = 0
                    current_heartbeat_interval = base_heartbeat_interval
                else:
                    heartbeat_failures += 1
                    _handle_heartbeat_failure(
                        config, heartbeat_failures,
                        base_heartbeat_interval,
                    )
                    # Update current interval based on failure count
                    if 3 <= heartbeat_failures < 10:
                        current_heartbeat_interval = base_heartbeat_interval * 2
                    elif heartbeat_failures >= 10:
                        # Reset cycle — back to normal
                        logger.info(
                            "Heartbeat failure cycle reset after %d failures",
                            heartbeat_failures,
                        )
                        heartbeat_failures = 0
                        current_heartbeat_interval = base_heartbeat_interval
            except Exception as exc:
                logger.error("Heartbeat error: %s", exc)
                heartbeat_failures += 1
            last_heartbeat = now

        # Sync poll check
        if now - last_sync_poll >= config["sync_poll_interval"]:
            try:
                poll_syncs(config)
            except Exception as exc:
                logger.error("Sync poll error: %s", exc)
            last_sync_poll = now

        # Sleep between checks
        time.sleep(5)


def _handle_heartbeat_failure(config, failure_count, base_interval):
    """Handle heartbeat failure with escalating recovery actions."""
    if failure_count == 3:
        logger.warning(
            "Heartbeat failed %d consecutive times — doubling interval to %ds",
            failure_count,
            base_interval * 2,
        )
    elif failure_count == 5:
        logger.warning(
            "Heartbeat failed %d consecutive times — attempting re-registration",
            failure_count,
        )
        _attempt_re_registration(config)
    elif failure_count == 10:
        logger.warning(
            "Heartbeat failed %d consecutive times — resetting cycle",
            failure_count,
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutting down (KeyboardInterrupt).")
        sys.exit(0)
    except Exception as exc:
        logger.critical("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)
