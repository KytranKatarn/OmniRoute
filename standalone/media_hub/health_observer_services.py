"""Media Hub scheduled health jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from health_observer_common import *  # noqa: F401,F403


def service_health_probe() -> None:
    """Call each client's probe() and update media_hub_services row."""
    from tools.media_hub.services import get_service_client

    rows = _services_rows()
    log.info("service_health_probe: %d service(s) to check", len(rows))

    for row in rows:
        sid, stype, name, host, port, use_ssl, enc, prev_status = row
        try:
            client = get_service_client(stype, host, port, _decrypt(enc), use_ssl)
            ok, msg = client.probe()
            new_status = "healthy" if ok else "unhealthy"
            if new_status != (prev_status or "unknown"):
                log.warning(
                    "health transition: %s (%s) %s → %s: %s",
                    name, stype, prev_status, new_status, msg,
                )
            else:
                log.info("health ok: %s (%s): %s", name, stype, msg)
            _write_health(sid, new_status, msg)
        except Exception as e:
            log.exception("probe failed: %s (%s)", name, stype)
            _write_health(sid, "error", f"probe exception: {e}")

def indexer_health_probe() -> None:
    """Probe Sonarr/Radarr health + Prowlarr indexerstatus. Log anything
    that's been failing. Alerts land in docker logs for now — project #279
    tracks the hub-webhook integration."""
    rows = _services_rows()

    for row in rows:
        sid, stype, name, host, port, use_ssl, enc, _ = row
        key = _decrypt(enc)
        if not key:
            continue

        if stype in ("sonarr", "radarr"):
            health, err = _arr_health(stype, host, port, key, use_ssl)
            if err is not None:
                log.warning("indexer probe: %s unreachable (%s)", name, err)
                continue
            if not health:
                log.info("indexer probe: %s health = clean", name)
                continue
            for h in health:
                severity = (h.get("type") or "info").upper()
                source = h.get("source", "?")
                msg = h.get("message", "")
                log.warning(
                    "indexer probe: %s [%s] %s → %s",
                    name, severity, source, msg,
                )

        elif stype == "prowlarr":
            statuses, err = _prowlarr_indexer_status(host, port, key, use_ssl)
            if err is not None:
                log.warning("indexer probe: %s unreachable (%s)", name, err)
                continue
            if not statuses:
                log.info("indexer probe: %s indexerstatus = clean", name)
                continue
            # Prowlarr only lists indexers that are CURRENTLY failing.
            # Presence here = problem.
            for st in statuses:
                indexer_id = st.get("indexerId", "?")
                disabled_till = st.get("disabledTill", "?")
                cause = st.get("mostRecentFailure") or st.get("initialFailure") or "?"
                log.warning(
                    "indexer probe: prowlarr indexer %s failing (disabled until %s, cause=%s)",
                    indexer_id, disabled_till, cause,
                )

def maven_diagnostic_probe() -> None:
    """Run the full M.A.V.E.N. troubleshoot diagnostic chain every 30 min.

    On error-level findings:
    - Logs each error to stdout (captured by docker logs / V.I.G.I.L.)
    - Attempts to notify the platform hub via POST /api/notifications so
      A.R.C.H.I.E. can escalate to the user via Telegram.
    """
    import os

    try:
        from maven.troubleshoot import run_diagnostic

        report = run_diagnostic()
        _last_diagnostic.clear()
        _last_diagnostic.update({
            "overall": report["overall"],
            "summary": report["summary"],
            "generated_at": report["generated_at"],
            "errors": [c for c in report["checks"] if c["severity"] == "error"],
        })

        if report["overall"] == "error":
            error_titles = [c["title"] for c in _last_diagnostic["errors"]]
            log.warning(
                "M.A.V.E.N. diagnostic: %d error(s) — %s",
                len(error_titles),
                ", ".join(error_titles[:3]),
            )

            # Best-effort: notify the A.R.C.H.I.E. platform hub
            hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
            api_key = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
            if api_key:
                try:
                    requests.post(
                        f"{hub_url}/api/internal/notify",
                        json={
                            "type": "warning",
                            "title": "M.A.V.E.N. — Media Hub alert",
                            "message": f"{len(error_titles)} issue(s): {', '.join(error_titles[:3])}",
                            "source": "media_hub_maven",
                            "priority": "high",
                        },
                        headers={"Authorization": f"Bearer {api_key}"},
                        timeout=5,
                    )
                except Exception:
                    pass  # Platform unreachable — stdout log above is the fallback
        else:
            log.info("M.A.V.E.N. diagnostic: %s", report["overall"])
    except Exception as exc:
        log.error("maven_diagnostic_probe failed: %s", exc)

def quality_probe() -> None:
    """Run movie quality + disk space audit every 12h.

    Logs flagged movies and attempts to notify the A.R.C.H.I.E. hub so
    A.R.C.H.I.E. can escalate to Kytran via Telegram.
    """
    import os

    try:
        from maven.quality import _get_movie_quality_report, check_disk_space

        flagged = [m for m in _get_movie_quality_report() if m.flagged]
        disk_issues = [c for c in check_disk_space() if c.severity != "ok"]

        if not flagged and not disk_issues:
            log.info("quality_probe: all movies within guidelines, disk healthy")
            return

        msgs = []
        for c in disk_issues:
            log.warning("quality_probe: disk — %s: %s", c.title, c.detail)
            msgs.append(f"{c.title}: {c.detail}")

        for m in flagged[:5]:
            log.warning(
                "quality_probe: flagged — %s (%s) %s %.1fGB: %s",
                m.title, m.year, m.quality, m.size_gb, m.reason,
            )
            msgs.append(f"{m.title} {m.size_gb:.0f}GB")

        if len(flagged) > 5:
            msgs.append(f"…+{len(flagged) - 5} more")

        hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
        api_key = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
        if api_key:
            try:
                requests.post(
                    f"{hub_url}/api/notifications",
                    json={
                        "type": "warning",
                        "title": "M.A.V.E.N. — Quality alert",
                        "message": (
                            f"{len(flagged)} oversized movie(s). "
                            f"{'; '.join(msgs[:3])}. "
                            f"Run /maven/api/upgrade-oversized to fix."
                        ),
                        "source": "media_hub_maven_quality",
                        "priority": "normal",
                    },
                    headers={"X-Internal-Key": api_key},
                    timeout=5,
                )
            except Exception:
                pass  # hub unreachable — stdout log is the fallback

    except Exception as exc:
        log.error("quality_probe failed: %s", exc)

def arr_database_probe() -> None:
    """Report Arr API database-health warnings without restarting containers.

    The host monitor checks the actual live SQLite files and scheduled archives
    read-only. Restarting a service cannot repair a corrupt database and risks
    disturbing its WAL, so this API-level probe only alerts for human review.
    """
    import os

    rows = _services_rows()
    by_type = {r[1]: r for r in rows}
    issues: list[str] = []

    for arr_type in ("sonarr", "radarr"):
        arr_row = by_type.get(arr_type)
        if not arr_row:
            continue
        _, _, arr_name, host, port, use_ssl, enc, _ = arr_row
        key = _decrypt(enc)
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}/api/v3"

        try:
            response = requests.get(
                f"{base}/health", headers={"X-Api-Key": key}, timeout=8
            )
            response.raise_for_status()
            health = response.json()
        except Exception as exc:
            log.warning("arr_database_probe: %s health check failed: %s", arr_name, exc)
            continue

        db_errors = [
            h for h in health
            if h.get("type") in ("error", "warning")
            and any(kw in h.get("message", "").lower() for kw in ("database", "vacuum", "sqlite"))
        ]
        for item in db_errors:
            detail = str(item.get("message", "database warning"))[:240]
            issues.append(f"{arr_name}: {detail}")
            log.warning("arr_database_probe: %s DB issue: %s", arr_name, detail)

    if not issues:
        return

    hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
    api_key_env = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
    if not api_key_env:
        log.error("arr_database_probe: ARCHIE_INTERNAL_API_KEY is unset; cannot deliver DB alert")
        return
    try:
        response = requests.post(
            f"{hub_url}/api/internal/notify",
            json={
                "title": "M.A.V.E.N. — Arr database issue",
                "message": "; ".join(issues),
                "priority": "high",
                "source": "media_hub_maven_arrdb",
            },
            headers={"Authorization": f"Bearer {api_key_env}"},
            timeout=6,
        )
        response.raise_for_status()
    except Exception as exc:
        log.error("arr_database_probe: failed to deliver DB alert: %s", exc)

def grab_notify_probe() -> None:
    """Detect Overseerr requests that transitioned to processing (3) or
    available (5) in the last 10 minutes and fire a Telegram notification
    via the A.R.C.H.I.E. hub notification API. In-memory dedup prevents
    duplicate alerts within a container lifecycle."""
    import os
    from datetime import timezone

    global _seen_grab_ids

    rows = _services_rows()
    by_type = {r[1]: r for r in rows}

    overseerr_row = by_type.get("overseerr") or by_type.get("jellyseerr")
    if not overseerr_row:
        return

    _, stype, _, host, port, use_ssl, enc, _ = overseerr_row
    key = _decrypt(enc)
    if not key:
        return

    scheme = "https" if use_ssl else "http"
    base = f"{scheme}://{host}:{port}"

    try:
        r = requests.get(
            f"{base}/api/v1/request",
            params={"sort": "modified", "take": 20},
            headers={"X-Api-Key": key},
            timeout=8,
        )
        if r.status_code != 200:
            log.warning("grab_notify_probe: overseerr HTTP %s", r.status_code)
            return
        results = r.json().get("results", [])
    except Exception as e:
        log.warning("grab_notify_probe: request failed: %s", e)
        return

    cutoff = datetime.now(tz=timezone.utc).timestamp() - 600  # 10 min
    STATUS_LABEL = {3: "downloading now 📥", 5: "available ✅"}

    hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
    api_key_env = os.getenv("ARCHIE_INTERNAL_API_KEY", "")

    for req in results:
        req_id = req.get("id")
        status = req.get("status")
        if req_id is None or status not in STATUS_LABEL:
            continue
        if req_id in _seen_grab_ids:
            continue

        updated_raw = req.get("updatedAt", "")
        try:
            if isinstance(updated_raw, (int, float)):
                updated_ts = float(updated_raw)
            else:
                from datetime import datetime as _dt
                updated_ts = _dt.fromisoformat(
                    str(updated_raw).replace("Z", "+00:00")
                ).timestamp()
        except Exception:
            continue

        if updated_ts < cutoff:
            continue

        _seen_grab_ids.add(req_id)
        media = req.get("media", {})
        title = media.get("title") or media.get("originalTitle") or f"request #{req_id}"
        media_type = "movie" if media.get("mediaType") == "movie" else "TV"
        label = STATUS_LABEL[status]
        message = f"M.A.V.E.N. grabbed {title} ({media_type}) — {label}"
        log.info("grab_notify_probe: %s", message)

        if api_key_env:
            try:
                requests.post(
                    f"{hub_url}/api/notifications",
                    json={
                        "type": "info",
                        "title": "M.A.V.E.N. — Media grabbed",
                        "message": message,
                        "source": "media_hub_maven_grab",
                        "priority": "normal",
                    },
                    headers={"Authorization": f"Bearer {api_key_env}"},
                    timeout=5,
                )
            except Exception:
                pass
