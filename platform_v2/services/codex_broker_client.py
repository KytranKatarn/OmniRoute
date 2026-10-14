"""Opt-in, read-only Unix broker client. No assignment/start/stop operations."""

from pathlib import Path
import socket
import stat
import struct
import time

from services.codex_stop_receipts import (
    ReceiptObservation,
    canonical_bytes,
    strict_json,
    verify_current_receipt,
)

MAX_RESPONSE_BYTES = 262144


class BrokerUnavailable(RuntimeError):
    """Sanitized transport failure; never contains receipt or task contents."""


class BrokerClient:
    def __init__(self, socket_path: str, broker_uid: int, *, enabled=False, timeout=3.0):
        if not Path(socket_path).is_absolute() or type(broker_uid) is not int or broker_uid < 0:
            raise ValueError("Invalid broker endpoint")
        if not 0 < timeout <= 10:
            raise ValueError("Invalid broker timeout")
        self.socket_path = socket_path
        self.broker_uid = broker_uid
        self.enabled = enabled is True
        self.timeout = timeout

    def journal(self, assignment_id: str) -> list:
        """Read one assignment; authenticated peer and bounded EOF framing."""
        if not self.enabled:
            raise BrokerUnavailable("broker_disabled")
        if type(assignment_id) is not str or not assignment_id or len(assignment_id) > 128:
            raise BrokerUnavailable("assignment_invalid")
        try:
            path = Path(self.socket_path)
            info = path.lstat()
            parent = path.parent.lstat()
            if (
                not stat.S_ISSOCK(info.st_mode)
                or info.st_uid != self.broker_uid
                or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != self.broker_uid
                or parent.st_mode & 0o022
            ):
                raise BrokerUnavailable("broker_endpoint_untrusted")
            deadline = time.monotonic() + self.timeout
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:

                def remaining():
                    seconds = deadline - time.monotonic()
                    if seconds <= 0:
                        raise BrokerUnavailable("broker_timeout")
                    conn.settimeout(seconds)

                remaining()
                conn.connect(self.socket_path)
                credentials = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                _pid, uid, _gid = struct.unpack("3i", credentials)
                if uid != self.broker_uid:
                    raise BrokerUnavailable("broker_peer_untrusted")
                remaining()
                conn.sendall(canonical_bytes({"type": "get_journal", "assignment_id": assignment_id}))
                conn.shutdown(socket.SHUT_WR)  # broker reads until EOF before replying
                response = bytearray()
                while True:
                    remaining()
                    chunk = conn.recv(min(4096, MAX_RESPONSE_BYTES + 1 - len(response)))
                    if not chunk:
                        break
                    response.extend(chunk)
                    if len(response) > MAX_RESPONSE_BYTES:
                        raise BrokerUnavailable("broker_response_oversized")
            data = strict_json(bytes(response), limit=MAX_RESPONSE_BYTES)
            if (
                not isinstance(data, dict)
                or set(data) != {"type", "entries"}
                or data["type"] != "journal_response"
                or type(data["entries"]) is not list
                or len(data["entries"]) > 256
            ):
                raise BrokerUnavailable("broker_response_invalid")
            return data["entries"]
        except BrokerUnavailable:
            raise
        except (
            OSError,
            ValueError,
            TypeError,
            UnicodeError,
            RecursionError,
            OverflowError,
        ):
            raise BrokerUnavailable("broker_unavailable") from None

    def inspect_receipt(self, blob, signature, *, pin, expected):
        try:
            entries = self.journal(expected.assignment_id)
        except BrokerUnavailable as exc:
            return ReceiptObservation(False, str(exc))
        return verify_current_receipt(blob, signature, pin=pin, expected=expected, journal_entries=entries)

    def assign_task(self, assignment_data: dict) -> dict:
        """Request assignment; returns {'assignment': {...}, 'error': ...}."""
        if not self.enabled:
            raise BrokerUnavailable("broker_disabled")
        try:
            path = Path(self.socket_path)
            info = path.lstat()
            parent = path.parent.lstat()
            if (
                not stat.S_ISSOCK(info.st_mode)
                or info.st_uid != self.broker_uid
                or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != self.broker_uid
                or parent.st_mode & 0o022
            ):
                raise BrokerUnavailable("broker_endpoint_untrusted")
            deadline = time.monotonic() + self.timeout
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:

                def remaining():
                    seconds = deadline - time.monotonic()
                    if seconds <= 0:
                        raise BrokerUnavailable("broker_timeout")
                    conn.settimeout(seconds)

                remaining()
                conn.connect(self.socket_path)
                credentials = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                _pid, uid, _gid = struct.unpack("3i", credentials)
                if uid != self.broker_uid:
                    raise BrokerUnavailable("broker_peer_untrusted")

                payload = canonical_bytes({"type": "assign_task", "assignment_data": assignment_data})
                conn.sendall(payload)
                conn.shutdown(socket.SHUT_WR)
                remaining()
                response = b""
                while len(response) < MAX_RESPONSE_BYTES:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                data = strict_json(response)
                if data.get("type") != "assignment_response":
                    raise BrokerUnavailable("broker_invalid_response")
                return {"assignment": data.get("assignment"), "error": data.get("error")}
        except (
            OSError,
            ValueError,
            TypeError,
            UnicodeError,
            RecursionError,
            OverflowError,
        ):
            raise BrokerUnavailable("broker_unavailable") from None

    def complete_assignment(
        self, assignment_id: str, runner_id: str = "", success: bool = False, details: dict = None
    ) -> dict:
        """Complete assignment; returns {'success': ..., 'error': ...}."""
        if not self.enabled:
            raise BrokerUnavailable("broker_disabled")
        if type(assignment_id) is not str or not assignment_id or len(assignment_id) > 128:
            raise BrokerUnavailable("assignment_invalid")
        if details is None:
            details = {}
        try:
            path = Path(self.socket_path)
            info = path.lstat()
            parent = path.parent.lstat()
            if (
                not stat.S_ISSOCK(info.st_mode)
                or info.st_uid != self.broker_uid
                or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != self.broker_uid
                or parent.st_mode & 0o022
            ):
                raise BrokerUnavailable("broker_endpoint_untrusted")
            deadline = time.monotonic() + self.timeout
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:

                def remaining():
                    seconds = deadline - time.monotonic()
                    if seconds <= 0:
                        raise BrokerUnavailable("broker_timeout")
                    conn.settimeout(seconds)

                remaining()
                conn.connect(self.socket_path)
                credentials = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                _pid, uid, _gid = struct.unpack("3i", credentials)
                if uid != self.broker_uid:
                    raise BrokerUnavailable("broker_peer_untrusted")

                payload = canonical_bytes(
                    {
                        "type": "complete_assignment",
                        "assignment_id": assignment_id,
                        "runner_id": runner_id,
                        "success": bool(success),
                        "details": details,
                    }
                )
                conn.sendall(payload)
                conn.shutdown(socket.SHUT_WR)
                remaining()
                response = b""
                while len(response) < MAX_RESPONSE_BYTES:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                data = strict_json(response)
                if data.get("type") != "completion_response":
                    raise BrokerUnavailable("broker_invalid_response")
                return {"success": data.get("success", False), "error": data.get("error")}
        except (
            OSError,
            ValueError,
            TypeError,
            UnicodeError,
            RecursionError,
            OverflowError,
        ):
            raise BrokerUnavailable("broker_unavailable") from None
