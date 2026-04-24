"""
M.A.V.E.N. troubleshoot skill — task #2239.

Codifies the 2026-04-21 diagnostic that traced "nothing downloads in Sonarr"
to a Tailscale-MagicDNS trap inside Docker's embedded resolver. Packages the
same probe chain as a single HTTP call so future failures surface structured
findings with suggested fixes, instead of requiring manual shell archaeology.

Checks (in order — cheap → expensive):
    1. External DNS resolution from inside the container
    2. Each media_hub_services row: client.probe() + last_health_check age
    3. Sonarr /api/v3/health — indexer + import warnings
    4. Radarr /api/v3/health — same
    5. Prowlarr /api/v1/indexerstatus — currently-failing indexers
    6. SABnzbd queue status (paused? disk space?)
    7. SABnzbd warnings feed
    8. Radarr + Sonarr queue — importBlocked items (downloaded but not moved
       into library; common cause: hardlinks across different filesystems)

Exposed as:
    GET  /maven/api/troubleshoot  (JSON, admin-only)
    GET  /maven/troubleshoot       (rendered HTML, admin-only)
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional

import requests
from flask import jsonify, render_template
from flask_login import current_user, login_required

from database import get_db_cursor
from . import maven_bp

log = logging.getLogger("media_hub.maven.troubleshoot")

# Hostnames we probe. api.nzbgeek.info is the canonical "Tailscale MagicDNS
# trap" signal — if it SERVFAILs inside the container we know the DNS chain
# is broken even if every LAN service is reachable.
_DNS_PROBE_TARGETS = ["api.nzbgeek.info", "1.1.1.1"]
_STALENESS_WARN_MIN = 60   # warn if a service hasn't been re-probed in 1h
_STALENESS_CRIT_MIN = 360  # critical if stale > 6h (matches arr sticky flag)


@dataclass
class CheckResult:
    id: str
    title: str
    severity: str            # "ok" | "warning" | "error"
    detail: str
    fix: Optional[str] = None
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


# --- individual checks -----------------------------------------------------

def _check_external_dns() -> List[CheckResult]:
    results = []
    for host in _DNS_PROBE_TARGETS:
        try:
            start = time.perf_counter()
            addr = socket.gethostbyname(host)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            results.append(CheckResult(
                id=f"dns_{host.replace('.', '_')}",
                title=f"DNS: {host}",
                severity="ok",
                detail=f"resolved to {addr} in {elapsed_ms}ms",
                meta={"host": host, "address": addr, "elapsed_ms": elapsed_ms},
            ))
        except socket.gaierror as e:
            results.append(CheckResult(
                id=f"dns_{host.replace('.', '_')}",
                title=f"DNS: {host}",
                severity="error",
                detail=f"SERVFAIL/NXDOMAIN: {e}",
                fix=(
                    "Add an explicit `dns:` block to docker-compose.yml "
                    "(e.g. [192.168.1.200, 1.1.1.1]) and recreate. "
                    "Tailscale MagicDNS hijacks the container's resolver "
                    "when it inherits host /etc/resolv.conf — see "
                    "vault_note #258811 for the full trace."
                ),
                meta={"host": host, "error": str(e)},
            ))
    return results


def _rows_for_type(*service_types):
    with get_db_cursor(cursor_factory=None) as (_c, cur):
        cur.execute(
            """
            SELECT id, service_type, name, host, port, use_ssl,
                   api_key_encrypted, health_status, health_message,
                   last_health_check
              FROM media_hub_services
             WHERE is_enabled = TRUE AND service_type = ANY(%s)
          ORDER BY service_type
            """,
            (list(service_types),),
        )
        return cur.fetchall()


def _decrypt_key(enc: Optional[str]) -> str:
    if not enc:
        return ""
    from tools.media_hub.encryption import decrypt_api_key
    try:
        return decrypt_api_key(enc)
    except Exception as e:
        log.error("decrypt_api_key failed: %s", e)
        return ""


def _check_service_health() -> List[CheckResult]:
    """Compare media_hub_services.health_status + last_health_check freshness
    against our observer's latest run. Either is a tell."""
    results = []
    with get_db_cursor(cursor_factory=None) as (_c, cur):
        cur.execute(
            """
            SELECT service_type, name, health_status, health_message,
                   last_health_check
              FROM media_hub_services
             WHERE is_enabled = TRUE
          ORDER BY service_type
            """
        )
        rows = cur.fetchall()

    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    for stype, name, status, message, last_check in rows:
        if last_check is None:
            severity, detail, fix = "warning", "never checked", (
                "Observer scheduler may not be running — check docker logs "
                "for 'media hub observer scheduler started'"
            )
        else:
            lc = last_check.replace(tzinfo=timezone.utc) if last_check.tzinfo is None else last_check
            age_min = (now - lc).total_seconds() / 60
            if age_min > _STALENESS_CRIT_MIN:
                severity, detail, fix = "error", (
                    f"last check {int(age_min)}min ago (>6h) — observer stalled?"
                ), "Restart mediahub_app so start_scheduler() fires again"
            elif age_min > _STALENESS_WARN_MIN:
                severity, detail, fix = "warning", (
                    f"last check {int(age_min)}min ago — getting stale"
                ), None
            elif status != "healthy":
                severity, detail, fix = (
                    "error" if status == "unhealthy" else "warning",
                    f"{status}: {message or 'no message'}",
                    f"Check {name} directly — container may be down, auth may have rotated, or the service restarted",
                )
            else:
                severity, detail, fix = (
                    "ok",
                    f"{status} ({int(age_min)}min ago): {message or ''}",
                    None,
                )
        results.append(CheckResult(
            id=f"svc_{stype}",
            title=f"{name} ({stype})",
            severity=severity,
            detail=detail,
            fix=fix,
            meta={"service_type": stype, "status": status, "last_check": str(last_check)},
        ))
    return results


def _arr_health(service_type: str) -> List[CheckResult]:
    """Poll Sonarr/Radarr /api/v3/health and surface each warning/error as
    its own CheckResult."""
    rows = _rows_for_type(service_type)
    if not rows:
        return []
    results = []
    for sid, stype, name, host, port, use_ssl, enc, *_ in rows:
        key = _decrypt_key(enc)
        if not key:
            results.append(CheckResult(
                id=f"{stype}_health_no_key",
                title=f"{name} health",
                severity="warning",
                detail="no api key configured; skipping health probe",
            ))
            continue
        scheme = "https" if use_ssl else "http"
        url = f"{scheme}://{host}:{port}/api/v3/health"
        try:
            r = requests.get(url, headers={"X-Api-Key": key}, timeout=8)
            if r.status_code != 200:
                results.append(CheckResult(
                    id=f"{stype}_health",
                    title=f"{name} health",
                    severity="error",
                    detail=f"HTTP {r.status_code}: {r.text[:100]}",
                ))
                continue
            health = r.json()
            if not health:
                results.append(CheckResult(
                    id=f"{stype}_health",
                    title=f"{name} health",
                    severity="ok",
                    detail="no health warnings",
                ))
                continue
            for h in health:
                severity = "error" if (h.get("type") == "error") else "warning"
                source = h.get("source", "?")
                msg = h.get("message", "")
                fix = None
                if "IndexerLongTermStatusCheck" in source or "IndexerRssCheck" in source:
                    fix = (
                        f"Clear sticky flag: "
                        f"POST {scheme}://{host}:{port}/api/v3/indexer/testall "
                        f"then POST /api/v3/command {{\"name\":\"RssSync\"}}"
                    )
                results.append(CheckResult(
                    id=f"{stype}_{source}",
                    title=f"{name}: {source}",
                    severity=severity,
                    detail=msg,
                    fix=fix,
                    meta={"wiki": h.get("wikiUrl")},
                ))
        except Exception as e:
            results.append(CheckResult(
                id=f"{stype}_health_err",
                title=f"{name} health",
                severity="error",
                detail=f"probe exception: {e}",
                fix=(
                    "Container unreachable; check `docker ps` + "
                    "`docker logs {stype}`"
                ),
            ))
    return results


def _prowlarr_indexers() -> List[CheckResult]:
    rows = _rows_for_type("prowlarr")
    if not rows:
        return []
    results = []
    for sid, stype, name, host, port, use_ssl, enc, *_ in rows:
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        try:
            # /indexerstatus only lists indexers that are currently failing.
            # Empty list = all good.
            r = requests.get(
                f"{scheme}://{host}:{port}/api/v1/indexerstatus",
                headers={"X-Api-Key": key}, timeout=8,
            )
            if r.status_code != 200:
                results.append(CheckResult(
                    id="prowlarr_indexerstatus",
                    title=f"{name} indexer status",
                    severity="error",
                    detail=f"HTTP {r.status_code}: {r.text[:100]}",
                ))
                continue
            statuses = r.json()
            if not statuses:
                results.append(CheckResult(
                    id="prowlarr_indexerstatus",
                    title=f"{name} indexer status",
                    severity="ok",
                    detail="all indexers healthy",
                ))
                continue
            for st in statuses:
                iid = st.get("indexerId", "?")
                disabled_till = st.get("disabledTill", "?")
                cause = (st.get("mostRecentFailure")
                         or st.get("initialFailure")
                         or "?")
                results.append(CheckResult(
                    id=f"prowlarr_indexer_{iid}",
                    title=f"Prowlarr indexer {iid} failing",
                    severity="error",
                    detail=f"disabled until {disabled_till}, cause: {cause}",
                    fix=(
                        f"Test in UI: {scheme}://{host}:{port}/ → Indexers → "
                        f"find id={iid} → Test. If 'Resource temporarily "
                        f"unavailable', check container DNS (dns_* checks "
                        f"above)."
                    ),
                    meta=st,
                ))
        except Exception as e:
            results.append(CheckResult(
                id="prowlarr_indexerstatus",
                title=f"{name} indexer status",
                severity="error",
                detail=f"probe exception: {e}",
            ))
    return results


def _sabnzbd_queue() -> List[CheckResult]:
    rows = _rows_for_type("sabnzbd")
    if not rows:
        return []
    results = []
    for sid, stype, name, host, port, use_ssl, enc, *_ in rows:
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}/api"
        try:
            r = requests.get(
                f"{base}?mode=queue&output=json&apikey={key}", timeout=5,
            )
            if r.status_code != 200:
                results.append(CheckResult(
                    id="sabnzbd_queue",
                    title=f"{name} queue",
                    severity="error",
                    detail=f"HTTP {r.status_code}",
                ))
                continue
            q = r.json().get("queue", {})
            paused = q.get("paused")
            disk_gb = q.get("diskspace1")
            if paused:
                results.append(CheckResult(
                    id="sabnzbd_paused",
                    title=f"{name} paused",
                    severity="warning",
                    detail=f"queue is paused (status={q.get('status')})",
                    fix=(
                        f"Resume in UI: {scheme}://{host}:{port}/ "
                        f"or POST {base}?mode=resume&apikey=…"
                    ),
                ))
            else:
                results.append(CheckResult(
                    id="sabnzbd_running",
                    title=f"{name} queue",
                    severity="ok",
                    detail=(
                        f"running, {q.get('noofslots', 0)} slots, "
                        f"{disk_gb} GB free"
                    ),
                ))
            # Disk space warning
            try:
                free_gb = float(disk_gb)
                if free_gb < 50:
                    results.append(CheckResult(
                        id="sabnzbd_disk",
                        title=f"{name} disk space low",
                        severity="warning",
                        detail=f"{free_gb:.1f} GB free on download dir",
                        fix="Clean up completed downloads or resize volume",
                    ))
            except (TypeError, ValueError):
                pass

            # Warnings feed
            w = requests.get(
                f"{base}?mode=warnings&output=json&apikey={key}", timeout=5,
            )
            if w.status_code == 200:
                for warn in w.json().get("warnings", [])[:3]:
                    results.append(CheckResult(
                        id=f"sabnzbd_warn_{warn.get('type','')}",
                        title=f"{name} warning",
                        severity="warning",
                        detail=(warn.get("text") or "")[:200],
                    ))
        except Exception as e:
            results.append(CheckResult(
                id="sabnzbd_probe",
                title=f"{name} probe",
                severity="error",
                detail=f"probe exception: {e}",
            ))
    return results


def _arr_import_blocked() -> List[CheckResult]:
    """Check Radarr + Sonarr queues for importBlocked items — downloads that
    finished but couldn't be moved into the library.

    Common cause: copyUsingHardlinks=true when /downloads and /movies are on
    different filesystems. Hardlinks across filesystems fail (EXDEV), and
    Radarr v6.1's .NET 8 fallback-copy hits a UnixFileMode bug (EACCES).
    Fix: set copyUsingHardlinks=false in Radarr/Sonarr media management.
    """
    results = []
    for service_type, scan_cmd in [
        ("radarr", "DownloadedMoviesScan"),
        ("sonarr", "DownloadedEpisodesScan"),
    ]:
        rows = _rows_for_type(service_type)
        if not rows:
            continue
        for sid, stype, name, host, port, use_ssl, enc, *_ in rows:
            key = _decrypt_key(enc)
            if not key:
                continue
            scheme = "https" if use_ssl else "http"
            base = f"{scheme}://{host}:{port}"
            try:
                r = requests.get(
                    f"{base}/api/v3/queue?pageSize=50&includeMovie=true",
                    headers={"X-Api-Key": key},
                    timeout=8,
                )
                if r.status_code != 200:
                    continue
                recs = r.json().get("records", [])
                blocked = [x for x in recs if x.get("trackedDownloadState") == "importBlocked"]
                if not blocked:
                    results.append(CheckResult(
                        id=f"{stype}_import_blocked",
                        title=f"{name} import queue",
                        severity="ok",
                        detail="no importBlocked items",
                    ))
                    continue
                for item in blocked:
                    title = item.get("title", "?")[:60]
                    msgs = []
                    for sm in item.get("statusMessages", []):
                        msgs += [m for m in sm.get("messages", []) if m]
                        if sm.get("title") and not sm.get("messages"):
                            msgs.append(sm["title"])
                    detail = "; ".join(msgs) or "Failed to import — check Radarr/Sonarr logs"
                    results.append(CheckResult(
                        id=f"{stype}_import_blocked_{item.get('id', '?')}",
                        title=f"{name}: importBlocked — {title}",
                        severity="error",
                        detail=detail,
                        fix=(
                            "1. Check if /downloads and /movies are on different filesystems "
                            "(stat -f /downloads vs /movies — different IDs = different FS). "
                            "If so: PUT /api/v3/config/mediamanagement with copyUsingHardlinks=false. "
                            f"2. Retry: POST {base}/api/v3/command "
                            + '{"name":"' + scan_cmd + '"}. '
                            "3. If still blocked: copy the file manually into the library folder "
                            "then POST /api/v3/command {\"name\":\"RescanMovie\",\"movieId\":…}."
                        ),
                        meta={
                            "output_path": item.get("outputPath", ""),
                            "queue_id": item.get("id"),
                        },
                    ))
            except Exception as e:
                log.error("%s import_blocked check failed: %s", stype, e)
    return results


# --- public API ------------------------------------------------------------

def run_diagnostic() -> dict:
    """Run the full M.A.V.E.N. troubleshoot chain. Pure function — doesn't
    modify state. Safe to call from UI, API, cron, or future agent dispatch.
    """
    checks: List[CheckResult] = []
    checks += _check_external_dns()
    checks += _check_service_health()
    checks += _arr_health("sonarr")
    checks += _arr_health("radarr")
    checks += _prowlarr_indexers()
    checks += _sabnzbd_queue()
    checks += _arr_import_blocked()

    summary = {"ok": 0, "warning": 0, "error": 0}
    for c in checks:
        summary[c.severity] = summary.get(c.severity, 0) + 1

    overall = "ok"
    if summary["error"] > 0:
        overall = "error"
    elif summary["warning"] > 0:
        overall = "warning"

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "overall": overall,
        "summary": summary,
        "checks": [c.as_dict() for c in checks],
    }


# --- routes ----------------------------------------------------------------

def _require_admin():
    from flask import abort
    if not getattr(current_user, "is_admin", False):
        abort(403)


@maven_bp.route("/api/troubleshoot")
@login_required
def api_troubleshoot():
    _require_admin()
    return jsonify(run_diagnostic())


@maven_bp.route("/troubleshoot")
@login_required
def troubleshoot_page():
    _require_admin()
    report = run_diagnostic()
    return render_template("maven_troubleshoot.html", report=report)
