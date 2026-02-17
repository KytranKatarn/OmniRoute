#!/usr/bin/env python3
"""
A.R.C.H.I.E. Node Sync Service
================================
Long-lived service that runs on business nodes to keep them in sync with the Hub.

Responsibilities:
  - Sends periodic heartbeats with system metrics
  - Reports code version on startup
  - Polls for pending sync commands and processes them

Standard library only (no pip install needed).
Optional: `requests` library for HTTP if available; falls back to urllib.
"""

import json
import logging
import os
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
DEFAULT_CONFIG_FILE = "/etc/archie-node/config.json"


def load_config():
    """
    Load configuration from environment variables, optionally overridden
    by a JSON config file.

    Priority: env vars  <  config file values  (config file wins if present)

    Required fields: NODE_ID, HUB_URL, HUB_API_KEY
    """
    # Start with env-var defaults
    config = {
        "node_id": os.environ.get("NODE_ID", ""),
        "hub_url": os.environ.get("HUB_URL", ""),
        "hub_api_key": os.environ.get("HUB_API_KEY", ""),
        "ollama_host": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        "heartbeat_interval": int(os.environ.get("HEARTBEAT_INTERVAL", "30")),
        "sync_poll_interval": int(os.environ.get("SYNC_POLL_INTERVAL", "60")),
        "archie_version": os.environ.get("ARCHIE_VERSION", "unknown"),
    }

    # Check for a config file
    config_path = os.environ.get("CONFIG_FILE", DEFAULT_CONFIG_FILE)
    if os.path.isfile(config_path):
        logger.info("Loading config from %s", config_path)
        try:
            with open(config_path, "r") as fh:
                file_cfg = json.load(fh)
            # Map file keys to our internal keys (support both naming styles)
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
            for file_key, internal_key in key_map.items():
                if file_key in file_cfg and file_cfg[file_key]:
                    val = file_cfg[file_key]
                    # Convert interval values to int
                    if internal_key in ("heartbeat_interval", "sync_poll_interval"):
                        val = int(val)
                    config[internal_key] = val
        except Exception as exc:
            logger.warning("Failed to load config file %s: %s", config_path, exc)

    # Validate required fields
    missing = [k for k in ("node_id", "hub_url", "hub_api_key") if not config.get(k)]
    if missing:
        logger.error(
            "Missing required config fields: %s. "
            "Set via environment variables or config file (%s).",
            ", ".join(missing),
            config_path,
        )
        sys.exit(1)

    # Strip trailing slash from hub_url
    config["hub_url"] = config["hub_url"].rstrip("/")

    return config


# ---------------------------------------------------------------------------
# HTTP Helpers
# ---------------------------------------------------------------------------


def http_post(url, data, headers=None):
    """
    POST JSON data to *url*. Returns (status_code, response_json).
    Uses `requests` if available, otherwise falls back to urllib.
    """
    headers = headers or {}
    headers.setdefault("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8")

    if _HAS_REQUESTS:
        try:
            resp = _requests_lib.post(url, json=data, headers=headers, timeout=15)
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


# ---------------------------------------------------------------------------
# Sync Operations
# ---------------------------------------------------------------------------


def _auth_headers(config):
    """Return standard auth headers for Hub API calls."""
    return {
        "X-Node-API-Key": config["hub_api_key"],
        "Content-Type": "application/json",
    }


def send_heartbeat(config):
    """
    POST heartbeat with metrics to the Hub.
    Endpoint: /tools/bridge/api/nodes/{node_id}/heartbeat
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
        "client_version": config["archie_version"],
        "details": {
            "hostname": _get_hostname(),
            "uptime": _get_uptime(),
            "sync_service": True,
        },
    }

    url = f"{config['hub_url']}/tools/bridge/api/nodes/{config['node_id']}/heartbeat"
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
    Endpoint: /tools/bridge/api/mesh/version
    """
    payload = {
        "node_id": config["node_id"],
        "version": config["archie_version"],
    }
    url = f"{config['hub_url']}/tools/bridge/api/mesh/version"
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
    Endpoint: /tools/bridge/api/mesh/sync/{node_id}/pending
    """
    url = f"{config['hub_url']}/tools/bridge/api/mesh/sync/{config['node_id']}/pending"
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
        try:
            handle_sync(config, sync_type, payload)
        except Exception as exc:
            logger.error("Sync #%s handler failed: %s", sync_id, exc)
            ack_status = "failed"
            error_message = str(exc)

        # Acknowledge the sync
        ack_url = f"{config['hub_url']}/tools/bridge/api/mesh/sync/{sync_id}/ack"
        ack_payload = {
            "node_id": config["node_id"],
            "status": ack_status,
            "error_message": error_message,
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
    Currently stub implementations for known sync types.
    """
    handlers = {
        "code_update": _handle_code_update,
        "iaae_policy": _handle_iaae_policy,
        "model_recommend": _handle_model_recommend,
    }

    handler = handlers.get(sync_type)
    if handler:
        handler(config, payload)
    else:
        logger.warning("Unknown sync_type '%s' — skipping", sync_type)


def _handle_code_update(config, payload):
    """Stub: handle a code_update sync command from the Hub."""
    version = payload.get("version", "unknown")
    logger.info(
        "[code_update] Hub requests update to version %s — stub, no action taken",
        version,
    )


def _handle_iaae_policy(config, payload):
    """Stub: handle an iaae_policy sync command from the Hub."""
    policy_name = payload.get("policy_name", "unknown")
    logger.info(
        "[iaae_policy] Received policy '%s' — stub, no action taken", policy_name
    )


def _handle_model_recommend(config, payload):
    """Stub: handle a model_recommend sync command from the Hub."""
    model = payload.get("model", "unknown")
    logger.info(
        "[model_recommend] Hub recommends model '%s' — stub, no action taken", model
    )


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


def main():
    logger.info("=" * 60)
    logger.info("A.R.C.H.I.E. Node Sync Service starting...")
    logger.info("=" * 60)

    config = load_config()

    logger.info("Node ID:            %s", config["node_id"])
    logger.info("Hub URL:            %s", config["hub_url"])
    logger.info("Ollama Host:        %s", config["ollama_host"])
    logger.info("Heartbeat Interval: %ds", config["heartbeat_interval"])
    logger.info("Sync Poll Interval: %ds", config["sync_poll_interval"])
    logger.info("Version:            %s", config["archie_version"])
    logger.info("HTTP backend:       %s", "requests" if _HAS_REQUESTS else "urllib")

    # Report version on startup
    report_version(config)

    last_heartbeat = 0.0
    last_sync_poll = 0.0

    logger.info("Entering main loop...")

    while True:
        now = time.time()

        # Heartbeat check
        if now - last_heartbeat >= config["heartbeat_interval"]:
            try:
                send_heartbeat(config)
            except Exception as exc:
                logger.error("Heartbeat error: %s", exc)
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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutting down (KeyboardInterrupt).")
        sys.exit(0)
    except Exception as exc:
        logger.critical("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)
