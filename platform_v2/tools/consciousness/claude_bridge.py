"""
Claude Bridge - Communication layer for Claude CLI

Handles:
- Sending messages to Claude CLI via ttyd WebSocket
- Capturing Claude's responses
- Session management
"""

import asyncio
import logging
import os
import re
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# ttyd configuration
TTYD_HOST = os.getenv("TTYD_HOST", "localhost")
TTYD_PORT = int(os.getenv("TTYD_PORT", "7681"))
TTYD_WS_URL = f"ws://{TTYD_HOST}:{TTYD_PORT}/ws"


class ClaudeBridge:
    """Bridge to Claude CLI via ttyd WebSocket"""

    def __init__(self):
        self.ws = None
        self.connected = False
        self.response_buffer = ""

    async def connect(self) -> bool:
        """Connect to ttyd WebSocket"""
        try:
            import websockets

            self.ws = await websockets.connect(TTYD_WS_URL)
            self.connected = True
            logger.info("Connected to Claude CLI via ttyd")
            return True
        except ImportError:
            logger.error("websockets package not installed. Run: pip install websockets")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to ttyd: {e}")
            return False

    async def send_message(self, message: str) -> Optional[str]:
        """Send message to Claude and get response"""
        if not self.connected:
            await self.connect()

        if not self.ws:
            return None

        try:
            # Send message to terminal
            await self.ws.send(message + "\n")

            # Collect response until prompt returns
            response = await self._collect_response()
            return response

        except Exception as e:
            logger.error(f"Error sending to Claude: {e}")
            return None

    async def _collect_response(self, timeout: float = 120.0) -> str:
        """Collect response from Claude until done"""
        response = ""
        try:
            while True:
                msg = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
                response += msg

                # Check for completion indicators
                if self._is_response_complete(response):
                    break

        except asyncio.TimeoutError:
            logger.warning("Claude response timeout")

        return self._clean_response(response)

    def _is_response_complete(self, response: str) -> bool:
        """Check if Claude has finished responding"""
        # Look for prompt return or other indicators
        indicators = ["\n> ", "\n$ ", "\n% ", "claude>"]
        return any(ind in response[-100:] for ind in indicators)

    def _clean_response(self, response: str) -> str:
        """Clean terminal escape codes and formatting"""
        # Remove ANSI escape codes
        ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        clean = ansi_escape.sub("", response)
        return clean.strip()

    async def disconnect(self):
        """Close WebSocket connection"""
        if self.ws:
            await self.ws.close()
            self.connected = False

    def health_check(self) -> dict:
        """Check if Claude CLI is available"""
        try:
            result = subprocess.run(["which", "claude"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return {
                    "status": "healthy",
                    "path": result.stdout.decode().strip(),
                    "ttyd_url": f"http://{TTYD_HOST}:{TTYD_PORT}",
                }
            return {"status": "unhealthy", "error": "claude not found"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def get_ttyd_status(self) -> dict:
        """Check if ttyd is running and accessible"""
        import socket

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((TTYD_HOST, TTYD_PORT))
            sock.close()

            if result == 0:
                return {
                    "status": "running",
                    "host": TTYD_HOST,
                    "port": TTYD_PORT,
                    "url": f"http://{TTYD_HOST}:{TTYD_PORT}",
                }
            else:
                return {"status": "not_running", "error": f"Cannot connect to {TTYD_HOST}:{TTYD_PORT}"}
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
