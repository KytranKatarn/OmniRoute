#!/usr/bin/env python3
"""
Claude CLI HTTP Proxy for A.R.C.H.I.E.

Simple HTTP server that wraps `claude -p` CLI calls, allowing Docker
containers to use Claude Max subscription without API keys.

Listens on port 7682, accepts POST requests with JSON body:
    {"message": "...", "system_prompt": "..."}

Returns:
    {"response": "...", "success": true}
"""

import json
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


class ClaudeProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
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

        # Build claude CLI command
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        logger.info(f"Processing request: {message[:80]}...")

        try:
            result = subprocess.run(
                cmd,
                input=message,
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
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), ClaudeProxyHandler)
    logger.info(f"Claude CLI proxy listening on {LISTEN_HOST}:{LISTEN_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
