"""
Scan input validation — hardens the security scanner command paths.
======================================================================

The Security & Network scanners shell out to nmap / nikto / nuclei / testssl /
ZAP by placing a caller-supplied ``target`` (and ``ports`` / ``severity``)
into an ``["docker", "exec", ...]`` argv. Because the argv is a list, there is
no *shell* injection — but an unvalidated value can still be:

  * **Argument injection** — a ``target`` beginning with ``-`` is parsed by the
    tool as an *option* (e.g. ``-oN /etc/cron.d/x`` writes an arbitrary file via
    nmap, ``--script`` runs arbitrary NSE). Same for ``ports`` (``--script=...``).
  * **SSRF / unauthorized scan** — a ``target`` of ``169.254.169.254`` (cloud
    metadata), ``127.0.0.1``, a ``100.64.0.0/10`` mesh peer, or an RFC-1918
    host lets an authenticated caller pivot the scanner into internal infra.

This module is the single validation chokepoint used by BOTH scan paths
(``argus_service._docker_scan`` and the ``/api/scanner/*`` routes). It fails
CLOSED: anything it cannot positively classify as safe is rejected.

Callers pass ``allow_internal=True`` only after an explicit operator opt-in
(the ``confirm_internal`` flag / an authorized client scope).
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

# A conservative charset for a bare host / IP / CIDR: letters, digits, dot,
# hyphen, colon (IPv6), slash (CIDR). Deliberately NO whitespace, no shell
# metacharacters, no '@', no '%'. URLs are handled separately below.
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.\-:/]{0,253}[A-Za-z0-9])?$")

# The nmap ports field is legitimately a single-token *flag* ("-F", "-p-",
# "-p80,443") OR a bare port list. We allow exactly those safe forms and reject
# every other option (blocks "--script", "-oN /path", "-iL", "--datadir", ...).
_PORT_FLAG_ALLOW = {"-F", "-p-", "-p1-65535"}
_PORT_P_FLAG_RE = re.compile(r"^-p[0-9]{1,5}(?:-[0-9]{1,5})?(?:,[0-9]{1,5}(?:-[0-9]{1,5})?)*$")
_PORT_LIST_RE = re.compile(r"^[0-9]{1,5}(?:-[0-9]{1,5})?(?:,[0-9]{1,5}(?:-[0-9]{1,5})?)*$")
_TOP_PORTS_RE = re.compile(r"^--top-ports=?[0-9]{1,5}$")

_SEVERITY_ALLOW = {"info", "low", "medium", "high", "critical", "unknown"}

# Hostnames that must never be scanned without an explicit internal opt-in.
_BLOCKED_HOST_KEYWORDS = ("localhost", "metadata.google.internal")

MAX_TARGET_LEN = 255


class ScanInputError(ValueError):
    """Raised when a scan input fails validation (fail-closed)."""


def _ip_is_sensitive(ip: ipaddress._BaseAddress) -> bool:
    """True for ranges that must not be scanned without an internal opt-in."""
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return True
    if ip.is_private:  # RFC1918 / fc00::/7 / etc.
        return True
    # Carrier-grade NAT 100.64.0.0/10 — the A.R.C.H.I.E. Headscale mesh range.
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        return True
    return False


def _host_is_sensitive(host: str) -> bool:
    host_l = host.strip("[]").lower()
    if host_l in _BLOCKED_HOST_KEYWORDS:
        return True
    try:
        ip = ipaddress.ip_address(host_l)
    except ValueError:
        # Not a literal IP — it's a hostname. We do NOT resolve DNS here (that
        # would itself be an SSRF primitive); the caller's allow_internal /
        # scope gate is the second line of defence.
        return False
    return _ip_is_sensitive(ip)


def validate_target(target: str, *, allow_internal: bool = False) -> str:
    """Validate and return a scan target (bare host/IP/CIDR or http(s) URL).

    Raises ``ScanInputError`` on anything unsafe. Never returns a value that
    begins with ``-`` (argument-injection guard).
    """
    if not isinstance(target, str):
        raise ScanInputError("target must be a string")
    target = target.strip()
    if not target:
        raise ScanInputError("target is empty")
    if len(target) > MAX_TARGET_LEN:
        raise ScanInputError("target too long")
    if target.startswith("-"):
        raise ScanInputError("target may not begin with '-' (argument injection)")
    # Reject any whitespace or shell metacharacter outright.
    if re.search(r"[\s;&|`$<>(){}\[\]!*?\"'\\]", target.replace("[", "").replace("]", "")):
        # (IPv6 literals legitimately use [ ]; strip those before the metachar test)
        raise ScanInputError("target contains illegal characters")

    scheme = urlsplit(target).scheme.lower()
    if scheme in ("http", "https"):
        parts = urlsplit(target)
        host = parts.hostname or ""
        if not host:
            raise ScanInputError("URL has no host")
        if not allow_internal and _host_is_sensitive(host):
            raise ScanInputError(f"internal/sensitive target blocked: {host}")
        return target
    if scheme:
        raise ScanInputError(f"unsupported URL scheme: {scheme}")

    # Bare host / IP / CIDR.
    host_only = target.split("/", 1)[0]  # strip CIDR suffix for the host test
    if not _HOST_RE.match(target):
        raise ScanInputError("target is not a valid host/IP/CIDR")
    if not allow_internal and _host_is_sensitive(host_only):
        raise ScanInputError(f"internal/sensitive target blocked: {host_only}")
    return target


def validate_ports(ports: str) -> str:
    """Validate an nmap ports/profile field. Rejects option injection.

    Accepts: a literal port list (``80,443,8000-8100``), the whitelisted
    profile flags (``-F``, ``-p-``), or ``--top-ports=N``.
    """
    if ports is None or ports == "":
        return "-F"
    if not isinstance(ports, str):
        raise ScanInputError("ports must be a string")
    ports = ports.strip()
    if ports in _PORT_FLAG_ALLOW:
        return ports
    if _PORT_P_FLAG_RE.match(ports):  # "-p80,443", "-p1-1000"
        return ports
    if _TOP_PORTS_RE.match(ports):  # "--top-ports=100"
        return ports
    if _PORT_LIST_RE.match(ports):  # bare "80,443" (no flag)
        return ports
    raise ScanInputError(f"invalid ports specification: {ports!r}")


def validate_severity(severity: str) -> str:
    """Validate a nuclei severity CSV. Rejects anything outside the enum."""
    if not severity:
        return "medium,high,critical"
    if not isinstance(severity, str):
        raise ScanInputError("severity must be a string")
    levels = [s.strip().lower() for s in severity.split(",") if s.strip()]
    if not levels:
        return "medium,high,critical"
    bad = [s for s in levels if s not in _SEVERITY_ALLOW]
    if bad:
        raise ScanInputError(f"invalid severity level(s): {bad}")
    return ",".join(levels)
