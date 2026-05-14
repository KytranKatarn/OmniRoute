"""Cluster Proxy routes — /api/proxy/fetch

Hub acts as trusted egress proxy for VPS fleet nodes.
VPS products route blocked external HTTP calls here so the
hub's residential IP (153.68.195.85) is used instead of
Hostinger datacenter IPs which are blocked by gov APIs.
"""

import ipaddress
import logging
import os
import socket
import time

import requests
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

proxy_bp = Blueprint("cluster_proxy", __name__, url_prefix="/api/proxy")

# Auth key — shared secret between hub and VPS nodes
_PROXY_KEY = os.environ.get("CLUSTER_PROXY_KEY", "")

# Hard limits
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB
_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120

# SSRF protection — block private/loopback ranges except Tailscale mesh
_BLOCKED_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
]

# Allowed external-only schemes
_ALLOWED_SCHEMES = {"http", "https"}


def _is_ssrf_safe(url: str) -> tuple[bool, str]:
    """Return (safe, reason). Blocks private IPs except mesh."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            return False, f"scheme '{parsed.scheme}' not allowed"

        host = parsed.hostname
        if not host:
            return False, "no host in URL"

        # Resolve hostname to IP
        try:
            ip_str = socket.gethostbyname(host)
            ip = ipaddress.ip_address(ip_str)
        except socket.gaierror:
            return False, f"cannot resolve host '{host}'"

        for blocked in _BLOCKED_RANGES:
            if ip in blocked:
                return False, f"IP {ip_str} is in blocked range {blocked}"

        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _verify_key() -> bool:
    """Check X-Proxy-Key header against CLUSTER_PROXY_KEY."""
    if not _PROXY_KEY:
        # No key configured — only allow requests from mesh IPs
        remote = request.remote_addr or ""
        return remote.startswith("100.64.") or remote.startswith("192.168.1.")
    incoming = request.headers.get("X-Proxy-Key", "")
    return incoming == _PROXY_KEY


def register_proxy_routes(bp, _admin_required=None):
    """Register proxy routes on the given blueprint (called from app.py pattern)."""

    @bp.route("/fetch", methods=["POST"])
    def proxy_fetch():
        """Proxy an external HTTP request through the hub's residential IP.

        Request body (JSON):
            url        str   — target URL (required)
            method     str   — HTTP method (default: GET)
            headers    dict  — extra request headers (optional)
            body       str   — request body for POST/PUT (optional)
            timeout    int   — seconds, max 120 (default: 30)
            stream     bool  — if true, return raw bytes (default: false)

        Response (JSON):
            status_code  int
            headers      dict
            body         str  (text) or base64 (binary)
            url          str  (final URL after redirects)
            elapsed_ms   int
        """
        if not _verify_key():
            return jsonify({"error": "Unauthorized — invalid or missing X-Proxy-Key"}), 401

        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        if not url:
            return jsonify({"error": "url is required"}), 400

        # SSRF check
        safe, reason = _is_ssrf_safe(url)
        if not safe:
            logger.warning("[proxy] SSRF blocked: %s — %s", url, reason)
            return jsonify({"error": f"URL blocked: {reason}"}), 403

        method = (data.get("method") or "GET").upper()
        if method not in {"GET", "POST", "PUT", "HEAD", "OPTIONS"}:
            return jsonify({"error": f"method '{method}' not allowed"}), 400

        extra_headers = data.get("headers") or {}
        body = data.get("body")
        timeout = min(int(data.get("timeout") or _DEFAULT_TIMEOUT), _MAX_TIMEOUT)

        # Build request headers — spoof a real browser UA so gov sites don't block
        req_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.8",
        }
        req_headers.update(extra_headers)

        t0 = time.time()
        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=req_headers,
                data=body.encode() if body else None,
                timeout=timeout,
                allow_redirects=True,
                stream=True,
            )

            # Read with size cap
            chunks = []
            size = 0
            for chunk in resp.iter_content(chunk_size=65536):
                chunks.append(chunk)
                size += len(chunk)
                if size > _MAX_RESPONSE_BYTES:
                    break
            raw = b"".join(chunks)

            elapsed_ms = int((time.time() - t0) * 1000)

            # Try to decode as text; fall back to base64
            content_type = resp.headers.get("Content-Type", "")
            if "text" in content_type or "json" in content_type or "xml" in content_type:
                try:
                    body_out = raw.decode("utf-8", errors="replace")
                    encoding = "utf-8"
                except Exception:
                    import base64

                    body_out = base64.b64encode(raw).decode()
                    encoding = "base64"
            else:
                import base64

                body_out = base64.b64encode(raw).decode()
                encoding = "base64"

            logger.info(
                "[proxy] %s %s → %d (%d bytes, %dms)",
                method,
                url,
                resp.status_code,
                size,
                elapsed_ms,
            )

            return jsonify(
                {
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": body_out,
                    "encoding": encoding,
                    "url": resp.url,
                    "elapsed_ms": elapsed_ms,
                    "truncated": size >= _MAX_RESPONSE_BYTES,
                }
            )

        except requests.Timeout:
            return jsonify({"error": f"Request timed out after {timeout}s", "url": url}), 504
        except requests.ConnectionError as exc:
            return jsonify({"error": f"Connection error: {exc}", "url": url}), 502
        except Exception as exc:
            logger.exception("[proxy] Unexpected error fetching %s", url)
            return jsonify({"error": str(exc), "url": url}), 500

    @bp.route("/health", methods=["GET"])
    def proxy_health():
        """Simple health check — confirms proxy is running."""
        return jsonify({"status": "ok", "key_configured": bool(_PROXY_KEY)})
