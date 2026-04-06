"""
Honeypot Service — Lightweight TCP honeypot that logs connection attempts to suspicious ports.
Runs in a background daemon thread using asyncio.
"""

import asyncio
import logging
import threading
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Default honeypot ports (common attack targets)
DEFAULT_PORTS = [22, 23, 445, 3389, 8080]


class HoneypotService:
    def __init__(self):
        self._running = False
        self._thread = None
        self._ports = DEFAULT_PORTS

    def start(self, ports=None):
        """Start honeypot listeners on given ports in a daemon thread."""
        if self._running:
            return
        self._ports = ports or DEFAULT_PORTS
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[Honeypot] Started on ports %s", self._ports)

    def stop(self):
        """Signal the honeypot to shut down."""
        self._running = False
        logger.info("[Honeypot] Stop requested")

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except Exception as e:
            logger.error("[Honeypot] Event loop error: %s", e)
        finally:
            loop.close()
            self._running = False

    async def _serve(self):
        servers = []
        for port in self._ports:
            actual_port = port + 30000  # offset to avoid conflicts with real services
            try:
                server = await asyncio.start_server(self._handle_connection, "0.0.0.0", actual_port)
                servers.append(server)
                logger.info(
                    "[Honeypot] Listening on :%d (simulating port %d)",
                    actual_port,
                    port,
                )
            except Exception as e:
                logger.warning("[Honeypot] Cannot bind port %d: %s", actual_port, e)

        while self._running:
            await asyncio.sleep(1)

        for s in servers:
            s.close()

    async def _handle_connection(self, reader, writer):
        """Log any connection attempt -- any traffic to honeypot ports is suspicious."""
        peername = writer.get_extra_info("peername")
        sockname = writer.get_extra_info("sockname")
        source_ip = peername[0] if peername else "unknown"
        dest_port = sockname[1] - 30000 if sockname else 0  # reverse offset

        # Read up to 256 bytes of payload (non-blocking, 2s timeout)
        payload = ""
        try:
            data = await asyncio.wait_for(reader.read(256), timeout=2.0)
            payload = data.hex()[:512] if data else ""
        except Exception:
            pass

        try:
            writer.close()
        except Exception:
            pass

        # Log to DB
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO honeypot_events "
                    "(source_ip, dest_port, protocol, payload_preview) "
                    "VALUES (%s, %s, 'tcp', %s)",
                    (source_ip, dest_port, payload),
                )
            logger.warning("[Honeypot] Connection from %s to port %d", source_ip, dest_port)
        except Exception as e:
            logger.error("[Honeypot] DB log failed: %s", e)

    def get_events(self, limit=100, source_ip=None):
        """Retrieve honeypot events from DB, optionally filtered by source IP."""
        with get_db_cursor() as (conn, cur):
            if source_ip:
                cur.execute(
                    "SELECT * FROM honeypot_events " "WHERE source_ip = %s " "ORDER BY detected_at DESC LIMIT %s",
                    (source_ip, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM honeypot_events " "ORDER BY detected_at DESC LIMIT %s",
                    (limit,),
                )
            return cur.fetchall()

    def get_config(self):
        """Return current honeypot configuration."""
        return {"running": self._running, "ports": self._ports}
