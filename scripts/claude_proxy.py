#!/usr/bin/env python3
"""
Claude CLI HTTP Proxy for A.R.C.H.I.E.

Simple HTTP server that wraps `claude -p` CLI calls, allowing Docker
containers to use Claude Max subscription without API keys.

Listens on port 7682, accepts POST requests with JSON body:
    {"message": "...", "system_prompt": "..."}

Returns:
    {"response": "...", "success": true}

AUTHENTICATION
--------------
A POST here runs `claude -p --dangerously-skip-permissions` as the host user, so it is
remote code execution by design. Every POST must carry the shared secret in the
``X-Claude-Proxy-Token`` header, matched against the ``CLAUDE_PROXY_TOKEN`` environment
variable with :func:`hmac.compare_digest`.

It FAILS CLOSED: if ``CLAUDE_PROXY_TOKEN`` is unset or empty, every POST is refused with
503. An unset secret must never mean "allow" — that is precisely the state this proxy ran
in before, reachable unauthenticated from the whole LAN.

GET is deliberately left open: it returns only ``{"status": "ok"}`` and every caller uses
it as a liveness probe (see the health_check()/connect() paths in the two claude_bridge
modules), so gating it would break health reporting without protecting anything.
"""

import hmac
import json
import os
import subprocess
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [claude-proxy] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 7682
SUBPROCESS_TIMEOUT = 120

AUTH_HEADER = "X-Claude-Proxy-Token"
TOKEN_ENV_VAR = "CLAUDE_PROXY_TOKEN"

# A refused request still gets its body drained so the client reads the 401/503 instead of
# a connection reset — but only up to this cap, so an unauthenticated caller can never make
# the proxy buffer an arbitrary Content-Length.
MAX_DRAIN_BYTES = 1 << 20


def expected_token() -> str:
    """The configured shared secret, or "" when it is not configured."""
    return os.environ.get(TOKEN_ENV_VAR, "").strip()


class ClaudeProxyHandler(BaseHTTPRequestHandler):
    def _auth_refusal(self):
        """(status, error) when this request must be refused, else None.

        Never logs the presented or expected token.
        """
        expected = expected_token()
        if not expected:
            logger.error(
                "Refusing POST: %s is not configured (fail-closed). "
                "Set it in the environment and restart claude-proxy.service.",
                TOKEN_ENV_VAR,
            )
            return (503, f"Proxy misconfigured: {TOKEN_ENV_VAR} is not set")

        presented = (self.headers.get(AUTH_HEADER) or "").strip()
        # compare_digest on bytes: a str comparison raises TypeError on a non-ASCII
        # header value, which would turn a bad token into a 500 instead of a 401.
        if not hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8")):
            logger.warning(
                "Refusing POST from %s: missing or invalid %s",
                self.client_address[0] if self.client_address else "?",
                AUTH_HEADER,
            )
            return (401, f"Unauthorized: missing or invalid {AUTH_HEADER}")

        return None

    def _drain_body(self):
        """Read (and discard) a bounded amount of the request body."""
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            return
        if length > 0:
            try:
                self.rfile.read(min(length, MAX_DRAIN_BYTES))
            except Exception:
                pass

    def do_POST(self):
        # Authenticate BEFORE reading the body or touching the CLI.
        refusal = self._auth_refusal()
        if refusal is not None:
            status, error = refusal
            self._drain_body()
            self._respond(status, {"success": False, "error": error})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self._respond(400, {"success": False, "error": f"Invalid JSON: {e}"})
            return

        message = data.get("message", "").strip()
        if not message:
            self._respond(400, {"success": False, "error": "Missing 'message' field"})
            return

        system_prompt = data.get("system_prompt", "").strip()
        conversation = data.get("conversation", [])

        # Build full prompt with conversation history
        full_message = self._build_prompt(conversation, message)

        # Build claude CLI command
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        logger.info(f"Processing request: {message[:80]}...")

        try:
            result = subprocess.run(
                cmd,
                input=full_message,
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT,
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"Exit code {result.returncode}"
                logger.error(f"Claude CLI error: {error_msg}")
                self._respond(502, {"success": False, "error": error_msg})
                return

            response_text = result.stdout.strip()
            logger.info(f"Response: {response_text[:80]}...")
            self._respond(200, {"success": True, "response": response_text})

        except subprocess.TimeoutExpired:
            logger.error(f"Claude CLI timed out after {SUBPROCESS_TIMEOUT}s")
            self._respond(504, {"success": False, "error": "Claude CLI timed out"})
        except FileNotFoundError:
            logger.error("Claude CLI not found in PATH")
            self._respond(503, {"success": False, "error": "Claude CLI not found"})
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            self._respond(500, {"success": False, "error": str(e)})

    @staticmethod
    def _build_prompt(conversation, current_message):
        """Build a full prompt with conversation history prepended."""
        if not conversation:
            return current_message

        lines = []
        for entry in conversation:
            role = entry.get("role", "user")
            content = entry.get("content", "")
            if role == "assistant":
                lines.append(f"Assistant: {content}")
            else:
                lines.append(f"Human: {content}")

        lines.append(f"Human: {current_message}")
        lines.append("Assistant:")
        return "\n\n".join(lines)

    def do_GET(self):
        """Health check endpoint"""
        self._respond(200, {"status": "ok", "service": "claude-proxy"})

    def _respond(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        # Suppress default access logs, we log our own
        pass


def main():
    if not expected_token():
        logger.error(
            "%s is unset or empty — every POST will be refused with 503. "
            "The proxy still starts so GET health checks keep answering.",
            TOKEN_ENV_VAR,
        )
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), ClaudeProxyHandler)
    logger.info(f"Claude CLI proxy listening on {LISTEN_HOST}:{LISTEN_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
