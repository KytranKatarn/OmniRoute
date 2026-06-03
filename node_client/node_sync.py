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
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

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
CLIENT_VERSION = "3.0.0"

# Container name for ComfyUI on starship nodes
NODE_COMFYUI_CONTAINER = "archie_starship_comfyui"


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


# Resolved Ollama base URL — set once load_config() validates/detects a working
# endpoint, so helpers without `config` (get_ollama_status, _get_agent_welfare)
# use the same working host instead of a hardcoded 'ollama' that is unresolvable
# on Windows Docker Desktop (#3466).
_RESOLVED_OLLAMA_HOST = None


def _ollama_responds(host):
    """True if Ollama answers /api/tags at *host*."""
    if not host:
        return False
    try:
        status, _ = http_get(f"{host.rstrip('/')}/api/tags")
        return status == 200
    except Exception:
        return False


def _auto_detect_ollama():
    """Return the first Ollama endpoint that responds, or None.

    Ordered for cross-platform reach: an explicit OLLAMA_HOST that actually
    works, then host network, then Docker Desktop's host.docker.internal
    (Windows/Mac), then the node ollama container names. host.docker.internal
    is what makes Windows Starships work — the 'ollama' service name does NOT
    resolve there, which silently broke model_pull (#3466)."""
    env = os.environ.get("OLLAMA_HOST")
    candidates = [
        env,
        "http://host.docker.internal:11434",
        "http://localhost:11434",
        "http://archie_node_ollama:11434",
        "http://ollama:11434",
    ]
    seen = set()
    for host in candidates:
        if not host or host in seen:
            continue
        seen.add(host)
        if _ollama_responds(host):
            logger.info("Auto-detected Ollama at %s", host)
            return host
    return None


def _ollama_base():
    """Resolved Ollama base URL for helpers that don't carry `config`."""
    if _RESOLVED_OLLAMA_HOST:
        return _RESOLVED_OLLAMA_HOST
    return _auto_detect_ollama() or os.environ.get("OLLAMA_HOST") or "http://localhost:11434"


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
        "dr_hub_url": os.environ.get("DR_HUB_URL", ""),
        "hub_api_key": os.environ.get("HUB_API_KEY", ""),
        "ollama_host": os.environ.get("OLLAMA_HOST", ""),
        "heartbeat_interval": int(os.environ.get("HEARTBEAT_INTERVAL", "30")),
        "sync_poll_interval": int(os.environ.get("SYNC_POLL_INTERVAL", "60")),
        "archie_version": os.environ.get("ARCHIE_VERSION", CLIENT_VERSION),
    }

    # Load config.json as secondary source — env vars win for hub_url
    # (hub_url in config.json can be corrupted by OTA pushes with external URLs)
    if os.path.isfile(config_path):
        logger.info("Loading config from %s", config_path)
        try:
            with open(config_path, "r") as fh:
                file_cfg = json.load(fh)
            key_map = {
                "node_id": "node_id",
                "hub_url": "hub_url",
                "server_url": "hub_url",
                "dr_hub_url": "dr_hub_url",
                "hub_api_key": "hub_api_key",
                "api_key": "hub_api_key",
                "ollama_host": "ollama_host",
                "heartbeat_interval": "heartbeat_interval",
                "sync_poll_interval": "sync_poll_interval",
                "sync_interval": "sync_poll_interval",
                "archie_version": "archie_version",
                "client_version": "archie_version",
            }
            # Env vars that are SET always take priority over config.json
            env_protected = set()
            if os.environ.get("HUB_URL"):
                env_protected.add("hub_url")
            if os.environ.get("NODE_ID"):
                env_protected.add("node_id")
            if os.environ.get("HUB_API_KEY"):
                env_protected.add("hub_api_key")

            for file_key, internal_key in key_map.items():
                if file_key in file_cfg and file_cfg[file_key]:
                    if internal_key in env_protected:
                        continue  # env var wins
                    val = file_cfg[file_key]
                    if internal_key in ("heartbeat_interval", "sync_poll_interval"):
                        val = int(val)
                    config[internal_key] = val
        except Exception as exc:
            logger.warning("Failed to load config file %s: %s", config_path, exc)
    else:
        logger.info("No config.json found at %s — using env vars", config_path)

    # Resolve + VALIDATE the Ollama host. A configured value (env / config.json)
    # can be an unresolvable Docker service name on Windows Docker Desktop (e.g.
    # 'http://ollama:11434'), which silently breaks model_pull (#3466). If the
    # configured host does not answer /api/tags, auto-detect a working endpoint
    # and override. Re-runs every startup, so it self-heals if the host changes.
    global _RESOLVED_OLLAMA_HOST
    configured = config.get("ollama_host")
    if not _ollama_responds(configured):
        detected = _auto_detect_ollama()
        if detected:
            if configured and detected != configured:
                logger.warning(
                    "Configured Ollama host %s is unreachable — using detected %s (#3466)",
                    configured,
                    detected,
                )
            config["ollama_host"] = detected
        elif not configured:
            config["ollama_host"] = "http://localhost:11434"
            logger.warning("Could not auto-detect Ollama; defaulting to %s", config["ollama_host"])
        # else: keep the configured host — detection failed but a value was set;
        # the pull will error loudly and the hub reaper retries.
    _RESOLVED_OLLAMA_HOST = config.get("ollama_host")

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

    # --- DR auto-failover state. The node self-heals its heartbeat/sync target
    # to the boston-2 standby if the primary hub dies (no external repoint
    # needed — that is impossible when the hub itself is down). dr_hub_url comes
    # from env DR_HUB_URL / config.json, defaulting to the boston-2 DR mesh. ---
    config["primary_hub_url"] = config["hub_url"]
    config["dr_hub_url"] = (config.get("dr_hub_url") or "http://100.64.0.10:3000").rstrip("/")
    config["_active"] = "primary"
    config["_dr_primary_ok"] = 0

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


def get_ram_gb():
    """Return total RAM in GB from /proc/meminfo, or None on failure."""
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024 / 1024, 1)
    except Exception:
        pass
    return None


def get_gpu_info():
    """Return (gpu_model, gpu_vram_gb) from nvidia-smi, or (None, None) if unavailable."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().split("\n")[0]
            parts = line.split(",")
            if len(parts) >= 2:
                model = parts[0].strip()
                vram_mb = float(parts[1].strip())
                return model, round(vram_mb / 1024, 1)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None, None


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
    ollama_host = _ollama_base()
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
        ollama_host = _ollama_base()
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


def _get_cpu_model():
    """Best-effort CPU model string (Linux /proc/cpuinfo, else platform.processor())."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    try:
        import platform as _pf

        return _pf.processor() or None
    except Exception:
        return None


def send_heartbeat(config):
    """
    POST heartbeat with metrics to the Hub.
    Endpoint: /tools/department-hq/api/nodes/{node_id}/heartbeat
    """
    cpu = get_cpu_usage()
    mem = get_memory_usage()
    gpu = get_gpu_usage()
    ram_gb = get_ram_gb()
    gpu_model, gpu_vram_gb = get_gpu_info()
    models = get_ollama_models(config["ollama_host"])

    payload = {
        "status": "online",
        "current_load": cpu,
        "cpu_usage": cpu,
        "memory_usage": mem,
        "gpu_usage": gpu if gpu is not None else 0,
        "ram_gb": ram_gb,
        "cpu_cores": os.cpu_count() or 0,
        "cpu_model": _get_cpu_model(),
        "gpu_available": gpu_model is not None,
        "gpu_model": gpu_model,
        "gpu_vram_gb": gpu_vram_gb,
        "hostname": _get_mesh_ip() or _get_hostname(),
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

    url = f"{config['hub_url']}/tools/department-hq/api/nodes/{config['node_id']}/heartbeat"
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
    Endpoint: /tools/department-hq/api/mesh/version
    """
    payload = {
        "node_id": config["node_id"],
        "version": config["archie_version"],
    }
    url = f"{config['hub_url']}/tools/department-hq/api/mesh/version"
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
    Endpoint: /tools/department-hq/api/mesh/sync/{node_id}/pending
    """
    url = f"{config['hub_url']}/tools/department-hq/api/mesh/sync/{config['node_id']}/pending"
    status, resp = http_get(url, _auth_headers(config))

    if status != 200:
        logger.warning("Sync poll failed (HTTP %d): %s", status, resp)
        return

    syncs = resp.get("syncs", [])
    if not syncs:
        return

    logger.info("Received %d pending sync(s)", len(syncs))

    # Filter out stale syncs (>24h old) — auto-expire them
    now = datetime.now(timezone.utc)
    fresh_syncs = []
    for sync_item in syncs:
        sent_at_str = sync_item.get("sent_at")
        if sent_at_str:
            try:
                sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                age = now - sent_at
                if age > timedelta(hours=24):
                    sync_id = sync_item.get("id")
                    logger.warning(
                        "Sync #%s is stale (%.1fh old) — auto-expiring",
                        sync_id, age.total_seconds() / 3600,
                    )
                    # ACK as expired
                    ack_url = f"{config['hub_url']}/tools/department-hq/api/mesh/sync/{sync_id}/ack"
                    ack_payload = {
                        "node_id": config["node_id"],
                        "status": "expired",
                        "error_message": f"Stale sync expired after {age.total_seconds() / 3600:.1f}h",
                        "result": {"status": "expired"},
                    }
                    http_post(ack_url, ack_payload, _auth_headers(config))
                    continue
            except (ValueError, TypeError):
                pass  # If we can't parse sent_at, process normally
        fresh_syncs.append(sync_item)
    syncs = fresh_syncs

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
            logger.exception("Sync #%s handler failed", sync_id)
            ack_status = "failed"
            error_message = str(exc)

        # Acknowledge the sync (include handler output for job results)
        ack_url = f"{config['hub_url']}/tools/department-hq/api/mesh/sync/{sync_id}/ack"
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
        "checkpoint_pull": _handle_checkpoint_pull,
        "container_upgrade": _handle_container_upgrade,
        "shell_exec": _handle_shell_exec,
        "ssh_toggle": _handle_ssh_toggle,
        "comfyui_setup": _handle_comfyui_setup,
        "firewall_rule": _handle_firewall_rule,
        "tailscale_status": _handle_tailscale_status,
        "docker_cleanup": _handle_docker_cleanup,
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
    action = payload.get("action", "restart")

    if action == "pull_and_restart":
        logger.info("[container_restart] Pulling latest images...")
        try:
            pull_result = subprocess.run(
                ["docker", "pull", "ghcr.io/kytrankatarn/archie-node:latest"],
                capture_output=True, text=True, timeout=300,
            )
            logger.info("[container_restart] Pull exit=%d: %s", pull_result.returncode, pull_result.stdout[:200])
        except Exception as e:
            logger.error("[container_restart] Pull failed: %s", e)
            return json.dumps({"error": f"Pull failed: {e}"})

        # Restart sync and api containers with new image
        for container in ["archie_node_sync", "archie_node_api"]:
            try:
                subprocess.run(
                    ["docker", "restart", container],
                    capture_output=True, text=True, timeout=60,
                )
                logger.info("[container_restart] Restarted %s", container)
            except Exception as e:
                logger.warning("[container_restart] Failed to restart %s: %s", container, e)

        return json.dumps({"action": "pull_and_restart", "status": "completed"})

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

    # Always prefer HUB_URL env var for downloads — immune to OTA config corruption
    hub_url = os.environ.get("HUB_URL", "") or config["hub_url"]
    headers = _auth_headers(config)
    updated = []
    errors = []

    # --- Download updated Python files ---
    for fname in files:
        url = f"{hub_url}/tools/department-hq/api/nodes/ota/{fname}"
        logger.info("[code_update] Downloading %s", fname)
        status, resp = http_get(url, headers)
        if status == 200:
            # http_get returns parsed JSON or {"raw": text}
            content = resp.get("raw", "")
            if not content:
                errors.append(f"{fname}: empty response")
            elif content.lstrip().startswith("<!DOCTYPE") or content.lstrip().startswith("<html"):
                errors.append(f"{fname}: got HTML instead of code — hub may require auth")
                logger.error("[code_update] REJECTED %s — received HTML (login page?), not code", fname)
            else:
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
            errors.append(f"{fname}: HTTP {status}")
            logger.warning("[code_update] Failed to download %s (HTTP %d)", fname, status)

    # --- Download and apply migrations ---
    for mig_name in migrations:
        url = f"{hub_url}/tools/department-hq/api/nodes/migrations/{mig_name}"
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
    # NOTE: hub_url is PROTECTED — it can only be set via .env or manual config.
    # OTA config_update must NOT override it, as the hub may push an external URL
    # (e.g. via reverse proxy) that returns HTML login pages instead of files.
    key_map = {
        "node_id": "node_id",
        "hub_api_key": "hub_api_key",
        "api_key": "hub_api_key",
        "ollama_host": "ollama_host",
        "heartbeat_interval": "heartbeat_interval",
        "sync_poll_interval": "sync_poll_interval",
        "archie_version": "archie_version",
    }
    if "hub_url" in payload or "server_url" in payload:
        logger.info("[config_update] Ignoring hub_url from OTA — protected field")
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


def _handle_checkpoint_pull(config, payload):
    """
    Download a ComfyUI checkpoint to the node.

    Expected payload:
        url (str): Direct download URL for the checkpoint file
        filename (str): Target filename (e.g. "RealVisXL_V4.0.safetensors")
        checkpoints_dir (str): Override path (default /comfyui/models/checkpoints)
    """
    url = payload.get("url")
    filename = payload.get("filename")
    if not url or not filename:
        return {"status": "error", "error": "url and filename required"}

    checkpoints_dir = payload.get("checkpoints_dir", "/comfyui/models/checkpoints")
    dest = os.path.join(checkpoints_dir, filename)

    # Skip if already downloaded
    if os.path.exists(dest) and os.path.getsize(dest) > 10_000_000:
        size_gb = os.path.getsize(dest) / 1e9
        logger.info("[checkpoint_pull] %s already exists (%.1fGB) — skipping", filename, size_gb)
        return {
            "status": "completed",
            "filename": filename,
            "size_bytes": os.path.getsize(dest),
            "skipped": True,
        }

    logger.info("[checkpoint_pull] Downloading %s from %s", filename, url[:80])
    start = time.time()

    # Download to /tmp then move to shared comfyui_data volume at /comfyui/models
    tmp_file = f"/tmp/{filename}.downloading"

    try:
        # Step 1: Download to /tmp in sync container
        downloaded = 0
        total = 0
        chunk_size = 8 * 1024 * 1024  # 8MB chunks

        if _HAS_REQUESTS:
            resp = _requests_lib.get(
                url,
                stream=True,
                timeout=7200,
                headers={"User-Agent": "ARCHIE-Node/3.0"},
            )
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            with open(tmp_file, "wb") as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and downloaded % (64 * 1024 * 1024) < chunk_size:
                            pct = (downloaded / total) * 100
                            logger.info(
                                "[checkpoint_pull] %s: %.0f%% (%.0fMB/%.0fMB)",
                                filename, pct, downloaded / 1e6, total / 1e6,
                            )
        else:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "ARCHIE-Node/3.0"})
            with urllib.request.urlopen(req, timeout=7200) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                with open(tmp_file, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and downloaded % (64 * 1024 * 1024) < chunk_size:
                            pct = (downloaded / total) * 100
                            logger.info(
                                "[checkpoint_pull] %s: %.0f%% (%.0fMB/%.0fMB)",
                                filename, pct, downloaded / 1e6, total / 1e6,
                            )

        dl_size = os.path.getsize(tmp_file)
        dl_elapsed = time.time() - start
        logger.info(
            "[checkpoint_pull] Downloaded %s: %.1fGB in %.0fs",
            filename, dl_size / 1e9, dl_elapsed,
        )

        # Step 2: Move to shared volume (comfyui_data mounted at /comfyui/models)
        # Use shutil.move — os.rename fails across different filesystems
        import shutil
        dest = os.path.join(checkpoints_dir, filename)
        os.makedirs(checkpoints_dir, exist_ok=True)
        shutil.move(tmp_file, dest)
        logger.info("[checkpoint_pull] Moved to %s", dest)

        # Restart ComfyUI so it detects the new checkpoint
        restart_ok, restart_msg = _restart_container(NODE_COMFYUI_CONTAINER)
        if restart_ok:
            logger.info("[checkpoint_pull] ComfyUI restarted to detect %s", filename)
        else:
            logger.warning("[checkpoint_pull] ComfyUI restart failed: %s", restart_msg)

        elapsed = time.time() - start
        speed_mbps = (dl_size / 1e6) / elapsed if elapsed > 0 else 0
        logger.info(
            "[checkpoint_pull] %s complete: %.1fGB in %.0fs (%.1f MB/s)",
            filename, dl_size / 1e9, elapsed, speed_mbps,
        )
        return {
            "status": "completed",
            "filename": filename,
            "size_bytes": dl_size,
            "elapsed_seconds": round(elapsed, 1),
            "speed_mbps": round(speed_mbps, 1),
            "comfyui_restarted": restart_ok,
        }
    except Exception as e:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        logger.error("[checkpoint_pull] Failed to download %s: %s", filename, e)
        return {"status": "error", "filename": filename, "error": str(e)}


def _handle_container_upgrade(config, payload):
    """
    Self-replacement: clone this container with new volume mounts, start the
    clone, then exit. The old container dies, the new one takes over.

    Expected payload:
        add_binds (list): Additional volume binds to add, e.g. ["comfyui_data:/comfyui/models"]
        container_name (str): Container to upgrade (default: archie_starship_sync)
    """
    container_name = payload.get("container_name", "archie_starship_sync")
    add_binds = payload.get("add_binds", [])

    if not add_binds:
        return {"status": "error", "error": "add_binds required (list of 'volume:path' strings)"}

    logger.info("[container_upgrade] Upgrading %s with new binds: %s", container_name, add_binds)

    try:
        # Step 1: Inspect current container
        code, raw = _docker_api("GET", f"/containers/{container_name}/json")
        if code != 200:
            return {"status": "error", "error": f"Cannot inspect {container_name}: HTTP {code}"}

        config_data = json.loads(raw)
        image = config_data["Config"]["Image"]
        env_list = config_data["Config"]["Env"]
        cmd = config_data["Config"]["Cmd"]
        host_cfg = config_data.get("HostConfig", {})
        binds = list(host_cfg.get("Binds", []))
        network_mode = host_cfg.get("NetworkMode", "bridge")
        restart_policy = host_cfg.get("RestartPolicy", {"Name": "unless-stopped"})

        # Step 2: Add new binds (skip duplicates)
        for bind in add_binds:
            mount_target = bind.split(":")[-1] if ":" in bind else bind
            if not any(mount_target in b for b in binds):
                binds.append(bind)
                logger.info("[container_upgrade] Adding bind: %s", bind)
            else:
                logger.info("[container_upgrade] Bind already exists for %s — skipping", mount_target)

        # Step 3: Create the replacement container (with temp name)
        temp_name = container_name + "_upgrade"

        # Remove temp container if it exists from a previous failed attempt
        _docker_api("POST", f"/containers/{temp_name}/stop?t=5")
        _docker_api("DELETE", f"/containers/{temp_name}?force=true")

        create_body = {
            "Image": image,
            "Cmd": cmd,
            "Env": env_list,
            "HostConfig": {
                "Binds": binds,
                "NetworkMode": network_mode,
                "RestartPolicy": restart_policy,
            },
        }

        code, raw = _docker_api("POST", f"/containers/create?name={temp_name}", body=create_body)
        if code not in (200, 201):
            return {"status": "error", "error": f"Create failed: HTTP {code} {raw[:200]}"}

        new_id = json.loads(raw).get("Id", "unknown")
        logger.info("[container_upgrade] Created replacement %s (id=%s)", temp_name, new_id[:12])

        # Step 4: Start the replacement
        code, _ = _docker_api("POST", f"/containers/{new_id}/start")
        if code not in (200, 204):
            return {"status": "error", "error": f"Start failed: HTTP {code}"}

        logger.info("[container_upgrade] Replacement started. Renaming...")

        # Step 5: Stop+remove the OLD container (this one!) and rename the new one
        # We do this in a thread so we can return the ack first
        import threading

        def _swap():
            time.sleep(3)  # Give time for the ack to be sent
            _docker_api("POST", f"/containers/{container_name}/stop?t=5")
            _docker_api("DELETE", f"/containers/{container_name}?force=true")
            _docker_api("POST", f"/containers/{temp_name}/rename?name={container_name}")
            logger.info("[container_upgrade] Swap complete: %s is now the active container", container_name)

        threading.Thread(target=_swap, daemon=True).start()

        return {
            "status": "completed",
            "new_id": new_id[:12],
            "binds": binds,
            "message": f"Replacement created and started. Self-swap in 3 seconds.",
        }

    except Exception as e:
        logger.error("[container_upgrade] Failed: %s", e)
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


def _handle_docker_cleanup(config, payload):
    """Clean up Docker debris — dangling images, unused volumes, build cache."""
    action = payload.get("action", "report")
    logger.info("[docker_cleanup] Action: %s", action)

    commands = {
        "prune_all": ["docker", "system", "prune", "-af", "--volumes"],
        "prune_images": ["docker", "image", "prune", "-af"],
        "prune_volumes": ["docker", "volume", "prune", "-f"],
    }

    result = {"action": action}

    # Get docker disk usage
    try:
        du_out = subprocess.run(
            ["docker", "system", "df"],
            capture_output=True, text=True, timeout=30,
        )
        result["docker_usage"] = du_out.stdout.strip()
    except Exception as e:
        result["docker_usage"] = str(e)

    if action == "report":
        logger.info("[docker_cleanup] Report only — no cleanup performed")
        return json.dumps(result)

    cmd = commands.get(action)
    if not cmd:
        logger.warning("[docker_cleanup] Unknown action: %s", action)
        return json.dumps({"error": f"Unknown action: {action}"})

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        result["output"] = proc.stdout.strip()
        result["exit_code"] = proc.returncode
        logger.info("[docker_cleanup] %s completed (exit %d)", action, proc.returncode)
    except subprocess.TimeoutExpired:
        result["error"] = "Cleanup timed out after 300s"
        logger.error("[docker_cleanup] Timed out")
    except Exception as e:
        result["error"] = str(e)
        logger.error("[docker_cleanup] Failed: %s", e)

    return json.dumps(result)


def _handle_firewall_rule(config, payload):
    """
    Forward a firewall rule request to BEACON (node_api) on localhost.
    BEACON runs on the host and can modify the OS firewall.

    Expected payload:
        port (int): Port to open (must be in allowlist: 11434, 8188, 3001)
        protocol (str): tcp or udp (default tcp)
        name (str): Rule name (optional)
    """
    port = payload.get("port")
    if not port:
        return {"status": "failed", "error": "port is required"}

    beacon_url = "http://localhost:3001/api/firewall-rule"
    beacon_payload = {
        "port": int(port),
        "protocol": payload.get("protocol", "tcp"),
        "name": payload.get("name", f"ARCHIE-{port}"),
    }

    try:
        status_code, resp = http_post(beacon_url, beacon_payload, {})
        if 200 <= status_code < 300:
            return {
                "status": "completed",
                "beacon_response": resp,
            }
        else:
            return {
                "status": "failed",
                "error": f"BEACON returned HTTP {status_code}",
                "beacon_response": resp,
            }
    except Exception as e:
        return {"status": "failed", "error": f"BEACON unreachable: {e}"}


def _handle_ssh_toggle(config, payload):
    """
    SSH toggle is not supported on containerized/Windows nodes.
    Kept as a registered handler to avoid 'unknown sync_type' errors.
    Use Tailscale or BEACON (port 3001) for remote access instead.
    """
    logger.info("[ssh_toggle] Not supported on this platform — use Tailscale or BEACON")
    return {
        "status": "not_supported",
        "error": "SSH toggle not available on this platform. Use Tailscale or BEACON for remote access.",
        "platform": platform.system(),
    }


def _handle_tailscale_status(config, payload):
    """
    Check if the Tailscale container is running on this node.
    Uses Docker Engine API via Unix socket.
    """
    container_name = "archie_starship_tailscale"
    logger.info("[tailscale_status] Checking container %s", container_name)

    try:
        code, body = _docker_api("GET", f"/containers/{container_name}/json")
        if code == 200:
            info = json.loads(body)
            state = info.get("State", {})
            return {
                "status": "completed",
                "container_running": state.get("Running", False),
                "container_status": state.get("Status", "unknown"),
                "started_at": state.get("StartedAt", ""),
            }
        elif code == 404:
            return {
                "status": "completed",
                "container_running": False,
                "container_status": "not_found",
                "error": "Tailscale container does not exist",
            }
        else:
            return {
                "status": "completed",
                "container_running": False,
                "error": f"Docker API returned HTTP {code}",
            }
    except Exception as e:
        return {
            "status": "failed",
            "error": f"Docker API error: {e}",
        }


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

    container_name = NODE_COMFYUI_CONTAINER
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


def _get_mesh_ip():
    """Return the node's Tailscale/Headscale mesh IP, or None.

    Reads MESH_IP env var (set in .env by deploy-node.ps1 after
    `tailscale ip --4` detection). Used to self-report the canonical
    inter-cluster address as `hostname` in heartbeats/registrations,
    so the hub's remote_nodes.hostname column gets a usable value
    instead of socket.gethostname() (which is the Docker container ID
    inside the sync container).

    Hub-side container-ID guards (PR #769/#770) catch the bad value
    if MESH_IP isn't set — this function is defense-in-depth.
    """
    value = os.environ.get("MESH_IP", "").strip()
    if value and value.startswith("100."):
        # Sanity check: Tailscale CGNAT range is 100.64.0.0/10
        octets = value.split(".")
        if len(octets) == 4:
            try:
                if 64 <= int(octets[1]) <= 127:
                    return value
            except ValueError:
                pass
    return None


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
    url = f"{config['hub_url']}/tools/department-hq/api/nodes/register"
    payload = {
        "node_id": config["node_id"],
        "node_name": _get_hostname(),
        "hostname": _get_mesh_ip() or _get_hostname(),
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


# ---------------------------------------------------------------------------
# Shutdown event — shared across threads for graceful termination
# ---------------------------------------------------------------------------
_shutdown_event = threading.Event()


def _heartbeat_thread(config):
    """Dedicated heartbeat thread — runs independently of sync processing.

    This ensures the hub always knows the node is alive, even during
    long-running sync operations (model downloads can take 30+ minutes).
    """
    heartbeat_failures = 0
    base_interval = config["heartbeat_interval"]
    current_interval = base_interval

    logger.info("[heartbeat-thread] Started (interval: %ds)", base_interval)

    while not _shutdown_event.is_set():
        try:
            success = send_heartbeat(config)
            if success:
                if heartbeat_failures > 0:
                    logger.info(
                        "[heartbeat-thread] Recovered after %d failures",
                        heartbeat_failures,
                    )
                heartbeat_failures = 0
                current_interval = base_interval
                # DR failback: while running on the DR hub, probe the primary;
                # once it has recovered for a few checks, switch back to it.
                if config.get("_active") == "dr":
                    if _probe_hub(config.get("primary_hub_url"), config):
                        config["_dr_primary_ok"] = config.get("_dr_primary_ok", 0) + 1
                        if config["_dr_primary_ok"] >= 3:
                            config["hub_url"] = config["primary_hub_url"]
                            config["_active"] = "primary"
                            config["_dr_primary_ok"] = 0
                            logger.info(
                                "[DR] Primary hub recovered — FAILED BACK to %s",
                                config["hub_url"],
                            )
                    else:
                        config["_dr_primary_ok"] = 0
            else:
                heartbeat_failures += 1
                _handle_heartbeat_failure(
                    config, heartbeat_failures, base_interval
                )
                if 3 <= heartbeat_failures < 10:
                    current_interval = base_interval * 2
                elif heartbeat_failures >= 10:
                    logger.info(
                        "[heartbeat-thread] Failure cycle reset after %d",
                        heartbeat_failures,
                    )
                    heartbeat_failures = 0
                    current_interval = base_interval
        except Exception as exc:
            logger.error("[heartbeat-thread] Error: %s", exc)
            heartbeat_failures += 1

        # Wait for next heartbeat or shutdown signal
        _shutdown_event.wait(timeout=current_interval)

    logger.info("[heartbeat-thread] Stopped.")


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

    # --- Graceful shutdown handler ---
    def _signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else signum
        logger.info("Received %s — initiating graceful shutdown...", sig_name)
        _shutdown_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # --- Start heartbeat in dedicated thread ---
    hb_thread = threading.Thread(
        target=_heartbeat_thread, args=(config,), daemon=True, name="heartbeat"
    )
    hb_thread.start()

    logger.info("Entering main loop (sync polling)...")

    while not _shutdown_event.is_set():
        try:
            poll_syncs(config)
        except Exception as exc:
            logger.error("Sync poll error: %s", exc)

        # Wait for next poll or shutdown signal
        _shutdown_event.wait(timeout=config["sync_poll_interval"])

    # --- Graceful shutdown ---
    logger.info("Shutdown: waiting for heartbeat thread to finish...")
    hb_thread.join(timeout=10)

    # Send final "shutting_down" status heartbeat
    try:
        logger.info("Sending final shutdown heartbeat...")
        send_heartbeat(config)
    except Exception:
        pass

    logger.info("Node client stopped cleanly.")


def _probe_hub(url, config):
    """Lightweight reachability check for a hub URL (GET /login -> 200).
    Never raises and can't hang (http_get has a 15s timeout)."""
    if not url:
        return False
    try:
        status, _ = http_get(f"{url}/login")
        return status == 200
    except Exception:
        return False


def _maybe_dr_failover(config):
    """If the primary hub is unreachable and a reachable DR hub is configured,
    switch the active hub to DR so the node keeps working on the standby.
    Returns True if it switched. No-op if the DR hub isn't answering yet."""
    dr = config.get("dr_hub_url")
    if not dr or config.get("_active") == "dr" or config.get("hub_url") == dr:
        return False
    if _probe_hub(dr, config):
        config["hub_url"] = dr
        config["_active"] = "dr"
        config["_dr_primary_ok"] = 0
        logger.warning("[DR] Primary hub down — FAILED OVER to DR hub %s", dr)
        return True
    return False


def _handle_heartbeat_failure(config, failure_count, base_interval):
    """Handle heartbeat failure with escalating recovery actions."""
    if failure_count == 3:
        logger.warning(
            "Heartbeat failed %d consecutive times — doubling interval to %ds",
            failure_count,
            base_interval * 2,
        )
    elif failure_count == 5:
        # Primary hub looks dead — try DR failover first, then (re)register
        # against whichever hub is now active.
        if _maybe_dr_failover(config):
            logger.warning("[DR] Heartbeat now targeting DR hub %s", config["hub_url"])
        else:
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
        _shutdown_event.set()
        logger.info("Shutting down (KeyboardInterrupt).")
        sys.exit(0)
    except Exception as exc:
        logger.critical("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)
