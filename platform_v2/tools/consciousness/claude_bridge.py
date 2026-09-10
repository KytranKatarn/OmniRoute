"""
Claude Bridge - Communication layer for Claude CLI via HTTP proxy

Handles:
- Sending messages to Claude via claude-proxy (Claude Max CLI)
- Capturing Claude's responses
- Session management for collaborations
- Health checks for proxy and ttyd services
"""

import json
import logging
import os
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

# Claude proxy configuration
CLAUDE_PROXY_URL = os.getenv("CLAUDE_PROXY_URL", "http://host.docker.internal:7682")
CLAUDE_PROXY_TOKEN_HEADER = "X-Claude-Proxy-Token"
TTYD_HOST = os.getenv("TTYD_HOST", "host.docker.internal")
TTYD_PORT = int(os.getenv("TTYD_PORT", "7681"))
REQUEST_TIMEOUT = 130  # Slightly above proxy's 120s subprocess timeout


def _proxy_headers() -> dict:
    """Headers for a proxy POST, carrying the shared secret.

    A proxy POST runs the Claude CLI with permissions skipped on the host, so it is gated
    on CLAUDE_PROXY_TOKEN (see scripts/claude_proxy.py). Read at call time, not import
    time, so a restart is the only thing needed to pick up a rotated secret. The GET
    health check is deliberately unauthenticated and gets no header.
    """
    headers = {"Content-Type": "application/json"}
    token = os.getenv("CLAUDE_PROXY_TOKEN", "").strip()
    if token:
        headers[CLAUDE_PROXY_TOKEN_HEADER] = token
    return headers


class ClaudeBridge:
    """Bridge to Claude via CLI HTTP proxy (uses Max subscription, no API costs)"""

    def __init__(self):
        self.connected = False
        self.conversation_history = []

    async def connect(self) -> bool:
        """Check proxy is reachable"""
        try:
            req = Request(CLAUDE_PROXY_URL, method="GET")
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read())
            self.connected = data.get("status") == "ok"
            return self.connected
        except Exception as e:
            logger.error(f"Failed to connect to Claude proxy: {e}")
            self.connected = False
            return False

    async def send_message(self, message: str, system_prompt: str = None) -> Optional[str]:
        """Send message to Claude via CLI proxy and get response"""
        try:
            # Build request payload
            payload = {"message": message}

            if system_prompt is None:
                system_prompt = (
                    "You are Claude, participating in a collaborative discussion "
                    "with A.R.C.H.I.E. (another AI assistant). Be helpful, insightful, "
                    "and collaborative. Share your knowledge and perspectives "
                    "while building on A.R.C.H.I.E.'s points. Keep responses focused "
                    "and concise (2-3 paragraphs max). If you think the topic "
                    "has been thoroughly addressed, indicate that naturally in "
                    "your response."
                )

            if system_prompt:
                payload["system_prompt"] = system_prompt

            # Include conversation history for context persistence
            if self.conversation_history:
                payload["conversation"] = self.conversation_history

            body = json.dumps(payload).encode()
            req = Request(
                CLAUDE_PROXY_URL,
                data=body,
                headers=_proxy_headers(),
                method="POST",
            )

            resp = urlopen(req, timeout=REQUEST_TIMEOUT)
            data = json.loads(resp.read())

            if data.get("success"):
                response_text = data["response"]
                self.conversation_history.append({"role": "user", "content": message})
                self.conversation_history.append({"role": "assistant", "content": response_text})
                self.connected = True
                return response_text
            else:
                error = data.get("error", "Unknown error")
                logger.error(f"Claude proxy returned error: {error}")
                return None

        except URLError as e:
            logger.error(f"Cannot reach Claude proxy at {CLAUDE_PROXY_URL}: {e}")
            self.connected = False
            return None
        except Exception as e:
            logger.error(f"Error sending to Claude proxy: {e}")
            return None

    def clear_history(self):
        """Clear conversation history for new session"""
        self.conversation_history = []

    async def disconnect(self):
        """Clean up"""
        self.conversation_history = []
        self.connected = False

    def health_check(self) -> dict:
        """Check if Claude proxy is accessible"""
        try:
            req = Request(CLAUDE_PROXY_URL, method="GET")
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read())

            if data.get("status") == "ok":
                return {
                    "status": "healthy",
                    "method": "Claude CLI proxy (Max subscription)",
                    "proxy_url": CLAUDE_PROXY_URL,
                    "note": "Uses Claude Max CLI - no API costs",
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": "Proxy returned unexpected response",
                }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": f"Cannot reach proxy: {e}",
                "proxy_url": CLAUDE_PROXY_URL,
            }

    def get_ttyd_status(self) -> dict:
        """Check ttyd-claude service on port 7681"""
        try:
            url = f"http://{TTYD_HOST}:{TTYD_PORT}"
            req = Request(url, method="GET")
            resp = urlopen(req, timeout=5)
            return {
                "status": "running",
                "url": f"http://192.168.1.200:{TTYD_PORT}",
                "http_code": resp.status,
            }
        except URLError as e:
            # 401 means ttyd is running but requires auth
            if hasattr(e, "code") and e.code == 401:
                return {
                    "status": "running",
                    "url": f"http://192.168.1.200:{TTYD_PORT}",
                    "note": "Requires authentication",
                }
            return {
                "status": "not_running",
                "error": str(e),
                "url": f"http://192.168.1.200:{TTYD_PORT}",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


# Singleton instance
_bridge: Optional[ClaudeBridge] = None


def get_claude_bridge() -> ClaudeBridge:
    """Get the Claude bridge singleton instance"""
    global _bridge
    if _bridge is None:
        _bridge = ClaudeBridge()
    return _bridge
