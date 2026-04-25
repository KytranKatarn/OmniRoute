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


# --- request pipeline check ------------------------------------------------

_STUCK_PENDING_HOURS = 2    # warn if pending this long without approval
_STUCK_APPROVED_HOURS = 2   # error if approved this long without entering arr queue

_REQUEST_STATUS = {1: "pending", 2: "approved", 3: "declined", 4: "failed", 5: "completed"}
_MEDIA_STATUS   = {1: "unknown", 2: "pending", 3: "processing", 4: "partial", 5: "available"}


def _check_request_pipeline() -> List[CheckResult]:
    """Query Overseerr for requests stuck at pending or approved.

    Pending > 2h usually means auto-approval is disabled — the request will
    never reach Radarr/Sonarr without a human approving it in Overseerr.

    Approved > 2h with no queue entry in Radarr/Sonarr means the arr push
    failed silently — common when Overseerr → Radarr/Sonarr connection drifts
    (API key rotated, container restarted, etc.).
    """
    rows = _rows_for_type("overseerr", "jellyseerr")
    if not rows:
        return []

    results = []
    for sid, stype, name, host, port, use_ssl, enc, *_ in rows:
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}"
        try:
            r = requests.get(
                f"{base}/api/v1/request",
                headers={"X-Api-Key": key},
                params={"take": 100, "skip": 0},
                timeout=10,
            )
            if r.status_code != 200:
                results.append(CheckResult(
                    id="overseerr_req_list",
                    title=f"{name} request list",
                    severity="error",
                    detail=f"HTTP {r.status_code}: {r.text[:100]}",
                    fix=f"Check Overseerr is running at {base}",
                ))
                continue

            all_requests = r.json().get("results", [])
            now = datetime.utcnow().replace(tzinfo=timezone.utc)
            stuck_pending: list = []
            stuck_approved: list = []

            for req in all_requests:
                req_status = req.get("status")
                media = req.get("media") or {}
                media_status = media.get("status", 0)

                # Skip anything already moving through the pipeline
                if media_status in (3, 4, 5) or req_status in (3, 4, 5):
                    continue

                try:
                    created_at = datetime.fromisoformat(
                        req.get("createdAt", "").replace("Z", "+00:00")
                    )
                    age_h = (now - created_at).total_seconds() / 3600
                except Exception:
                    age_h = 0

                title = (
                    media.get("title") or media.get("name")
                    or f"tmdb:{media.get('tmdbId', '?')}"
                )[:60]

                if req_status == 1 and age_h >= _STUCK_PENDING_HOURS:
                    stuck_pending.append((title, age_h))
                elif req_status == 2 and age_h >= _STUCK_APPROVED_HOURS:
                    stuck_approved.append((title, age_h))

            if not stuck_pending and not stuck_approved:
                results.append(CheckResult(
                    id="overseerr_pipeline",
                    title=f"{name} request pipeline",
                    severity="ok",
                    detail=f"{len(all_requests)} request(s) — all progressing normally",
                ))

            for title, age_h in stuck_pending:
                results.append(CheckResult(
                    id=f"overseerr_pending_{title[:20].replace(' ','_')}",
                    title=f"Request stuck pending: {title}",
                    severity="warning",
                    detail=f"pending for {age_h:.1f}h with no approval",
                    fix=(
                        f"Enable auto-approval in Overseerr: {base}/settings/main → "
                        "scroll to 'Default Permissions' → enable 'Auto-Approve'. "
                        "Or approve the request manually in Overseerr → Requests."
                    ),
                ))

            for title, age_h in stuck_approved:
                results.append(CheckResult(
                    id=f"overseerr_approved_{title[:20].replace(' ','_')}",
                    title=f"Request approved, not downloading: {title}",
                    severity="error",
                    detail=f"approved for {age_h:.1f}h but not found in Radarr/Sonarr queue",
                    fix=(
                        "Use 'Fix Stuck Requests' (POST /maven/api/fix-stuck-requests) to "
                        "trigger targeted searches in Radarr/Sonarr. Also check Prowlarr "
                        "indexer status above — if all indexers are failing, no results "
                        "can be found regardless of how many times we search."
                    ),
                ))

        except Exception as e:
            results.append(CheckResult(
                id="overseerr_pipeline_err",
                title=f"{name} pipeline check",
                severity="error",
                detail=f"probe exception: {e}",
            ))

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
    checks += _check_request_pipeline()
    # Disk space check (imported here to avoid circular import at module level)
    from .quality import check_disk_space as _check_disk_space
    checks += _check_disk_space()

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


@maven_bp.route("/api/status")
@login_required
def api_maven_status():
    """Return the last cached M.A.V.E.N. diagnostic summary (no re-run).
    Used by the nav badge to show a red dot when errors exist."""
    from health_observer import _last_diagnostic
    return jsonify({"success": True, "diagnostic": _last_diagnostic})


@maven_bp.route("/api/troubleshoot")
@login_required
def api_troubleshoot():
    _require_admin()
    return jsonify(run_diagnostic())


@maven_bp.route("/api/overseerr-sync", methods=["POST"])
@login_required
def api_overseerr_sync():
    """Trigger Overseerr availability-sync + radarr-scan so media that was
    manually imported gets marked available without waiting for the nightly run."""
    _require_admin()
    results = []
    for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type("overseerr", "jellyseerr"):
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}"
        for job in ("availability-sync", "radarr-scan"):
            try:
                r = requests.post(
                    f"{base}/api/v1/settings/jobs/{job}/run",
                    headers={"X-Api-Key": key},
                    timeout=8,
                )
                results.append({"service": name, "job": job, "ok": r.status_code == 200})
            except Exception as e:
                results.append({"service": name, "job": job, "ok": False, "error": str(e)})
    return jsonify({"success": True, "results": results})


@maven_bp.route("/api/retry-scan", methods=["POST"])
@login_required
def api_retry_scan():
    """Trigger DownloadedMoviesScan + DownloadedEpisodesScan on Radarr/Sonarr."""
    _require_admin()
    results = []
    for service_type, scan_cmd in [
        ("radarr", "DownloadedMoviesScan"),
        ("sonarr", "DownloadedEpisodesScan"),
    ]:
        for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type(service_type):
            key = _decrypt_key(enc)
            if not key:
                continue
            scheme = "https" if use_ssl else "http"
            try:
                r = requests.post(
                    f"{scheme}://{host}:{port}/api/v3/command",
                    headers={"X-Api-Key": key},
                    json={"name": scan_cmd},
                    timeout=5,
                )
                results.append({"service": name, "ok": r.status_code in (200, 201)})
            except Exception as e:
                results.append({"service": name, "ok": False, "error": str(e)})

    # Also trigger Plex library scan so newly imported files appear immediately
    for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type("plex"):
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        try:
            r = requests.get(
                f"{scheme}://{host}:{port}/library/sections/all/refresh",
                params={"X-Plex-Token": key},
                timeout=8,
                verify=False,
            )
            results.append({"service": name, "ok": r.status_code in (200, 201)})
        except Exception as e:
            results.append({"service": name, "ok": False, "error": str(e)})

    return jsonify({"success": True, "results": results})


@maven_bp.route("/api/fix-stuck-requests", methods=["POST"])
@login_required
def api_fix_stuck_requests():
    """Unstick approved-but-not-downloading requests.

    Strategy (in order):
    1. Pull approved requests from Overseerr, look each one up in Radarr/Sonarr
       by TMDB ID, and trigger a targeted search for items that are already
       monitored but have no queue entry.
    2. Run DownloadedMoviesScan + DownloadedEpisodesScan to import anything
       already downloaded but stuck in importBlocked.
    3. Run Overseerr availability-sync + radarr-scan to re-push any approved
       requests that never reached the arr services.
    4. Trigger a Plex library refresh so newly imported files appear immediately.
    """
    _require_admin()
    results = []

    # Step 1 — targeted arr searches for approved requests
    overseerr_rows = _rows_for_type("overseerr", "jellyseerr")
    approved_movies: list = []   # tmdb IDs
    approved_tv: list = []       # tmdb IDs

    for _, stype, name, host, port, use_ssl, enc, *_ in overseerr_rows:
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        try:
            r = requests.get(
                f"{scheme}://{host}:{port}/api/v1/request",
                headers={"X-Api-Key": key},
                params={"take": 100, "skip": 0, "filter": "approved"},
                timeout=10,
            )
            if r.status_code != 200:
                results.append({"step": "overseerr_fetch", "ok": False,
                                 "error": f"HTTP {r.status_code}"})
                continue
            for req in r.json().get("results", []):
                media = req.get("media") or {}
                media_status = media.get("status", 0)
                if media_status in (3, 4, 5):
                    continue   # already progressing
                tmdb_id = media.get("tmdbId")
                if not tmdb_id:
                    continue
                if req.get("type") == "movie":
                    approved_movies.append(tmdb_id)
                else:
                    approved_tv.append(tmdb_id)
        except Exception as e:
            results.append({"step": "overseerr_fetch", "ok": False, "error": str(e)})

    # Trigger targeted Radarr search for each approved movie
    for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type("radarr"):
        key = _decrypt_key(enc)
        if not key or not approved_movies:
            continue
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}"
        try:
            all_movies_r = requests.get(
                f"{base}/api/v3/movie",
                headers={"X-Api-Key": key},
                timeout=10,
            )
            if all_movies_r.status_code != 200:
                continue
            radarr_id_map = {m["tmdbId"]: m["id"] for m in all_movies_r.json()
                             if m.get("tmdbId") and m.get("id")}
            ids_to_search = [radarr_id_map[t] for t in approved_movies
                             if t in radarr_id_map]
            if ids_to_search:
                sr = requests.post(
                    f"{base}/api/v3/command",
                    headers={"X-Api-Key": key},
                    json={"name": "MoviesSearch", "movieIds": ids_to_search},
                    timeout=8,
                )
                results.append({
                    "step": "radarr_search", "service": name,
                    "count": len(ids_to_search),
                    "ok": sr.status_code in (200, 201),
                })
        except Exception as e:
            results.append({"step": "radarr_search", "service": name,
                            "ok": False, "error": str(e)})

    # Trigger targeted Sonarr search for each approved TV request
    for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type("sonarr"):
        key = _decrypt_key(enc)
        if not key or not approved_tv:
            continue
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}"
        try:
            all_series_r = requests.get(
                f"{base}/api/v3/series",
                headers={"X-Api-Key": key},
                timeout=10,
            )
            if all_series_r.status_code != 200:
                continue
            sonarr_id_map = {s["tmdbId"]: s["id"] for s in all_series_r.json()
                             if s.get("tmdbId") and s.get("id")}
            for tmdb_id in approved_tv:
                sonarr_id = sonarr_id_map.get(tmdb_id)
                if not sonarr_id:
                    continue
                sr = requests.post(
                    f"{base}/api/v3/command",
                    headers={"X-Api-Key": key},
                    json={"name": "SeriesSearch", "seriesId": sonarr_id},
                    timeout=8,
                )
                results.append({
                    "step": "sonarr_search", "service": name,
                    "tmdb_id": tmdb_id,
                    "ok": sr.status_code in (200, 201),
                })
        except Exception as e:
            results.append({"step": "sonarr_search", "service": name,
                            "ok": False, "error": str(e)})

    # Step 2 — scan for already-downloaded but not-imported files
    for service_type, scan_cmd in [
        ("radarr", "DownloadedMoviesScan"),
        ("sonarr", "DownloadedEpisodesScan"),
    ]:
        for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type(service_type):
            key = _decrypt_key(enc)
            if not key:
                continue
            scheme = "https" if use_ssl else "http"
            try:
                r = requests.post(
                    f"{scheme}://{host}:{port}/api/v3/command",
                    headers={"X-Api-Key": key},
                    json={"name": scan_cmd},
                    timeout=5,
                )
                results.append({"step": scan_cmd, "service": name,
                                 "ok": r.status_code in (200, 201)})
            except Exception as e:
                results.append({"step": scan_cmd, "service": name,
                                "ok": False, "error": str(e)})

    # Step 3 — Overseerr availability-sync + radarr-scan
    for _, stype, name, host, port, use_ssl, enc, *_ in overseerr_rows:
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        for job in ("availability-sync", "radarr-scan"):
            try:
                r = requests.post(
                    f"{scheme}://{host}:{port}/api/v1/settings/jobs/{job}/run",
                    headers={"X-Api-Key": key},
                    timeout=8,
                )
                results.append({"step": f"overseerr_{job}", "service": name,
                                 "ok": r.status_code == 200})
            except Exception as e:
                results.append({"step": f"overseerr_{job}", "service": name,
                                "ok": False, "error": str(e)})

    # Step 4 — Plex library refresh
    for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type("plex"):
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        try:
            r = requests.get(
                f"{scheme}://{host}:{port}/library/sections/all/refresh",
                params={"X-Plex-Token": key},
                timeout=8,
                verify=False,
            )
            results.append({"step": "plex_refresh", "service": name,
                             "ok": r.status_code in (200, 201)})
        except Exception as e:
            results.append({"step": "plex_refresh", "service": name,
                            "ok": False, "error": str(e)})

    ok_count = sum(1 for r in results if r.get("ok"))
    return jsonify({
        "success": True,
        "results": results,
        "summary": f"{ok_count}/{len(results)} actions succeeded",
        "note": (
            "Searches have been triggered. Downloads appear in SABnzbd within "
            "60–120s if Prowlarr finds results. Run /maven/api/troubleshoot "
            "again in a few minutes to verify progress."
        ),
    })


@maven_bp.route("/troubleshoot")
@login_required
def troubleshoot_page():
    _require_admin()
    report = run_diagnostic()
    return render_template("maven_troubleshoot.html", report=report)
