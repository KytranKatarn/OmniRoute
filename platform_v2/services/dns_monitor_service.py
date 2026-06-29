"""External-DNS resolution monitor (Task #4571).

Catches the RECURRING OAuth/external-DNS failure: `platform.claude.com` (the Claude
Code login endpoint) intermittently fails to resolve on the hub → login breaks →
gets patched blind with an `/etc/hosts` pin. The failure self-heals before anyone
looks, so it never gets root-caused. This monitor probes each watched name against
AdGuard (the hub's resolver) AND a direct control upstream every ~2 min, persisting
evidence so the next occurrence is caught with a timestamp + classification instead
of a guess.

Per-name status:
  healthy            — AdGuard resolves the name (NOERROR + an answer)
  adguard_fail       — AdGuard fails (SERVFAIL/timeout) but the control upstream
                       resolves it → THE actionable signal (AdGuard broken, internet
                       DNS fine; this is what breaks OAuth login)
  network_fail       — both AdGuard and control fail → upstream/connectivity, not
                       AdGuard-specific
  control_only_fail  — control fails but AdGuard ok → control path blocked
                       (informational; AdGuard — what the host uses — is fine)

Cycle classification = the worst per-name status. Dependency-free (raw UDP DNS
A-query; dnspython is not installed). Writes one dns_probe_log row per cycle; the
agent_loop wrapper (`_run_dns_monitor`) handles Telegram (only on classification
CHANGE) + system_notifications.
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import time
from typing import Optional

from database import get_db_cursor

logger = logging.getLogger("archie_platform")

_TIMEOUT = float(os.getenv("DNS_MONITOR_TIMEOUT", "3.0"))
# AdGuard at the host IP where it publishes :53 — exactly what the host resolver
# (/etc/resolv.conf → 192.168.1.200) uses, so the probe is host-faithful.
_ADGUARD = os.getenv("DNS_MONITOR_ADGUARD", "192.168.1.200")
_CONTROL = os.getenv("DNS_MONITOR_CONTROL", "1.1.1.1")  # direct upstream control
_NAMES = [
    n.strip()
    for n in os.getenv("DNS_MONITOR_NAMES", "platform.claude.com,api.anthropic.com,github.com").split(",")
    if n.strip()
]

_RCODE = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED", -1: "TIMEOUT"}
# escalation order — higher wins as the cycle classification
_ORDER = {"healthy": 0, "control_only_fail": 1, "network_fail": 2, "adguard_fail": 3}
_SEVERITY = {"adguard_fail": "error", "network_fail": "warning", "control_only_fail": "warning", "healthy": "info"}


def _dns_a_query(name: str, server: str, timeout: float = _TIMEOUT) -> dict:
    """Raw UDP A-record query to ``server``:53. Returns {ok, rcode, rcode_name, ip, ms}.
    ok = response RCODE 0 (NOERROR) with >= 1 A answer. rcode -1 = timeout/network error."""
    header = struct.pack(">HHHHHH", 0x4571, 0x0100, 1, 0, 0, 0)  # id, RD=1, 1 question
    try:
        qname = b"".join(struct.pack("B", len(p)) + p.encode("ascii") for p in name.split(".")) + b"\x00"
    except Exception:
        return {"ok": False, "rcode": -1, "rcode_name": "BADNAME", "ip": None, "ms": 0}
    packet = header + qname + struct.pack(">HH", 1, 1)  # QTYPE=A, QCLASS=IN
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    t0 = time.time()
    try:
        s.sendto(packet, (server, 53))
        data, _ = s.recvfrom(2048)
        ms = int((time.time() - t0) * 1000)
        rcode = data[3] & 0x0F
        ancount = struct.unpack(">H", data[6:8])[0]
        ok = rcode == 0 and ancount > 0
        return {
            "ok": ok,
            "rcode": rcode,
            "rcode_name": _RCODE.get(rcode, str(rcode)),
            "ip": _first_a_ip(data) if ok else None,
            "ms": ms,
        }
    except socket.timeout:
        return {"ok": False, "rcode": -1, "rcode_name": "TIMEOUT", "ip": None, "ms": int((time.time() - t0) * 1000)}
    except Exception as exc:
        return {
            "ok": False,
            "rcode": -1,
            "rcode_name": "ERROR:%s" % type(exc).__name__,
            "ip": None,
            "ms": int((time.time() - t0) * 1000),
        }
    finally:
        s.close()


def _skip_name(data: bytes, pos: int) -> int:
    """Advance past a wire-format DNS name (handles compression pointers)."""
    while True:
        length = data[pos]
        if length == 0:
            return pos + 1
        if length & 0xC0 == 0xC0:  # 2-byte compression pointer
            return pos + 2
        pos += 1 + length


def _first_a_ip(data: bytes) -> Optional[str]:
    """Best-effort: return the first A-record (type 1) rdata as a dotted IP, or None."""
    try:
        pos = 12
        for _ in range(struct.unpack(">H", data[4:6])[0]):  # questions
            pos = _skip_name(data, pos) + 4  # + qtype + qclass
        for _ in range(struct.unpack(">H", data[6:8])[0]):  # answers
            pos = _skip_name(data, pos)
            rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[pos : pos + 10])
            pos += 10
            if rtype == 1 and rdlen == 4:
                return ".".join(str(b) for b in data[pos : pos + 4])
            pos += rdlen
    except Exception:
        return None
    return None


def _ip_forward() -> Optional[int]:
    """Best-effort ip_forward snapshot (container-netns view; nullable). The
    'compliance-broke-it-first' suspect toggles this off → forwarding/DNS breaks."""
    try:
        with open("/proc/sys/net/ipv4/ip_forward") as fh:
            return int(fh.read().strip())
    except Exception:
        return None


def run_dns_probe() -> dict:
    """Probe every watched name against AdGuard + the control upstream, persist one
    dns_probe_log row, and return the result dict for the agent_loop wrapper."""
    results = []
    worst = "healthy"
    for name in _NAMES:
        ag = _dns_a_query(name, _ADGUARD)
        ctl = _dns_a_query(name, _CONTROL)
        if ag["ok"]:
            status = "healthy" if ctl["ok"] else "control_only_fail"
        else:
            status = "network_fail" if not ctl["ok"] else "adguard_fail"
        results.append({"name": name, "adguard": ag, "control": ctl, "status": status})
        if _ORDER[status] > _ORDER[worst]:
            worst = status

    notes = ""
    if worst == "adguard_fail":
        bad = [r["name"] for r in results if r["status"] == "adguard_fail"]
        notes = "AdGuard SERVFAIL/timeout on %s while the control upstream resolves — OAuth/login at risk." % ", ".join(
            bad
        )
    elif worst == "network_fail":
        bad = [r["name"] for r in results if r["status"] == "network_fail"]
        notes = "Both AdGuard and control failed on %s — upstream/connectivity issue." % ", ".join(bad)

    out = {
        "classification": worst,
        "severity": _SEVERITY[worst],
        "results": results,
        "ip_forward": _ip_forward(),
        "notes": notes,
        "adguard_server": _ADGUARD,
        "control_server": _CONTROL,
    }
    _persist(out)
    return out


def _persist(out: dict) -> None:
    """Best-effort dns_probe_log insert — never let logging break the probe."""
    try:
        import json

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO dns_probe_log (classification, severity, results, ip_forward, notes)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    out["classification"],
                    out["severity"],
                    json.dumps(out["results"]),
                    out["ip_forward"],
                    out["notes"] or None,
                ),
            )
    except Exception as exc:
        logger.warning("dns_monitor: dns_probe_log insert failed: %s", exc)


def format_dns_alert(out: dict) -> str:
    """Human-readable Telegram / system_notifications body."""
    emoji = {"error": "🔴", "warning": "🟡", "info": "🟢"}.get(out["severity"], "ℹ️")
    lines = ["%s DNS monitor — %s" % (emoji, out["classification"].upper())]
    if out.get("notes"):
        lines.append(out["notes"])
    for r in out["results"]:
        ag, ctl = r["adguard"], r["control"]
        lines.append(
            "• %s: AdGuard=%s(%dms%s) | control=%s(%dms)"
            % (
                r["name"],
                ag["rcode_name"],
                ag["ms"],
                (" %s" % ag["ip"]) if ag["ip"] else "",
                ctl["rcode_name"],
                ctl["ms"],
            )
        )
    if out.get("ip_forward") is not None:
        lines.append("ip_forward=%s (container view)" % out["ip_forward"])
    return "\n".join(lines)
