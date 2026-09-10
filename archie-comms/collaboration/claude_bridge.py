"""
Claude Bridge — Communication layer for Claude collaboration.

Two modes:
1. Anthropic API (ANTHROPIC_API_KEY env var) — direct API calls, works immediately
2. CLI proxy (CLAUDE_PROXY_URL) — HTTP proxy to Claude CLI (Max sub, no API costs)

Falls back gracefully: API first if key exists, then proxy, then unavailable.
"""

import json
import logging
import os
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

CLAUDE_PROXY_URL = os.getenv("CLAUDE_PROXY_URL", "http://192.168.1.200:7682")
CLAUDE_PROXY_TOKEN_HEADER = "X-Claude-Proxy-Token"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
REQUEST_TIMEOUT = 130

DEFAULT_SYSTEM_PROMPT = (
    "You are Claude, participating in a collaborative session with "
    "A.R.C.H.I.E. (Autonomous Resource & Cognitive Hyperintelligence Engine), "
    "COO of Kytran Empowerment Inc. A.R.C.H.I.E. is an AI business partner "
    "who manages 17 departments through her directors. "
    "Kytran is the CEO. You are the backup/ally — called in when "
    "A.R.C.H.I.E.'s local team can't handle a task. "
    "Be helpful, insightful, and collaborative. Keep responses focused "
    "and concise (2-3 paragraphs max)."
)


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
    """Bridge to Claude — API direct or CLI proxy."""

    def __init__(self):
        self.connected = False
        self.conversation_history = []
        self.mode = "api" if ANTHROPIC_API_KEY else "proxy"
        logger.info("claude_bridge: mode=%s", self.mode)

    def connect(self) -> bool:
        """Check if Claude is reachable."""
        if self.mode == "api" and ANTHROPIC_API_KEY:
            self.connected = True
            return True
        try:
            req = Request(CLAUDE_PROXY_URL, method="GET")
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read())
            self.connected = data.get("status") == "ok"
            return self.connected
        except Exception as e:
            logger.warning("claude_bridge: proxy unreachable: %s", e)
            self.connected = False
            return False

    def send_message(self, message: str, system_prompt: str = None) -> Optional[str]:
        """Send message to Claude and get response."""
        prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

        # Try API first if key exists
        if ANTHROPIC_API_KEY:
            result = self._send_via_api(message, prompt)
            if result:
                return result

        # Fall back to proxy
        result = self._send_via_proxy(message, prompt)
        return result

    def _send_via_api(self, message: str, system_prompt: str) -> Optional[str]:
        """Send via Anthropic API directly."""
        try:
            messages = list(self.conversation_history)
            messages.append({"role": "user", "content": message})

            payload = json.dumps({
                "model": CLAUDE_MODEL,
                "max_tokens": 2048,
                "system": system_prompt,
                "messages": messages,
            }).encode()

            req = Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )

            resp = urlopen(req, timeout=REQUEST_TIMEOUT)
            data = json.loads(resp.read())

            if data.get("content"):
                response_text = data["content"][0].get("text", "")
                self.conversation_history.append({"role": "user", "content": message})
                self.conversation_history.append({"role": "assistant", "content": response_text})
                self.connected = True
                return response_text

        except Exception as e:
            logger.warning("claude_bridge: API call failed: %s", e)
        return None

    def _send_via_proxy(self, message: str, system_prompt: str) -> Optional[str]:
        """Send via CLI HTTP proxy."""
        try:
            payload = {"message": message, "system_prompt": system_prompt}
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

        except Exception as e:
            logger.warning("claude_bridge: proxy call failed: %s", e)
            self.connected = False
        return None

    def clear_history(self):
        """Clear conversation history for new session."""
        self.conversation_history = []

    def disconnect(self):
        """Clean up."""
        self.conversation_history = []
        self.connected = False

    def health_check(self) -> dict:
        """Check Claude availability."""
        if ANTHROPIC_API_KEY:
            return {
                "status": "healthy",
                "mode": "api",
                "model": CLAUDE_MODEL,
                "note": "Direct Anthropic API",
            }
        try:
            req = Request(CLAUDE_PROXY_URL, method="GET")
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read())
            if data.get("status") == "ok":
                return {"status": "healthy", "mode": "proxy", "proxy_url": CLAUDE_PROXY_URL}
        except Exception:
            pass
        return {"status": "unavailable", "note": "Set ANTHROPIC_API_KEY or start Claude proxy"}


_bridge: Optional[ClaudeBridge] = None


def get_claude_bridge() -> ClaudeBridge:
    """Get the Claude bridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = ClaudeBridge()
    return _bridge
