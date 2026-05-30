"""Live Security & Network briefing injected into V.I.G.I.L. chat context."""

from services.time_utils import now_local_str


def _build_security_network_briefing() -> str:
    """
    Return a plain-text briefing of the Security & Network module's current state.
    Prepended to every V.I.G.I.L. message so she can answer status questions
    and give informed suggestions without extra fetches.
    """
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[V.I.G.I.L. SECURITY & NETWORK BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # Network devices
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'online' OR last_seen_at > NOW() - INTERVAL '10 minutes') AS online
                FROM network_devices
                """
            )
            d = cur.fetchone() or {}
            lines.append(f"Devices: {d.get('total', 0)} known | " f"{d.get('online', 0)} online")

            # Security events (24h)
            cur.execute(
                """
                SELECT event_type, COUNT(*) as cnt
                FROM security_events
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY event_type
                ORDER BY cnt DESC
                LIMIT 6
                """
            )
            events = cur.fetchall()
            if events:
                ev_str = " | ".join(f"{r['event_type']}:{r['cnt']}" for r in events)
                lines.append(f"Security events (24h): {ev_str}")
            else:
                lines.append("Security events (24h): none")

            # Compliance scan results — latest per pack
            try:
                cur.execute(
                    """
                    SELECT rule_pack, pass_count, fail_count, score_pct,
                           scanned_at
                    FROM compliance_scan_results
                    WHERE scanned_at = (
                        SELECT MAX(scanned_at) FROM compliance_scan_results r2
                        WHERE r2.rule_pack = compliance_scan_results.rule_pack
                    )
                    ORDER BY score_pct ASC
                    LIMIT 5
                    """
                )
                scans = cur.fetchall()
                if scans:
                    for s in scans:
                        pct = s.get("score_pct", 0)
                        flag = "⚠️" if pct < 80 else "✅"
                        lines.append(
                            f"{flag} {s['rule_pack']}: {pct:.0f}% " f"({s['pass_count']} pass / {s['fail_count']} fail)"
                        )
                else:
                    lines.append("Compliance scans: no results yet")
            except Exception:
                lines.append("Compliance scans: unavailable")

            # DNS changes (24h)
            try:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM security_dns_changes
                    WHERE changed_at > NOW() - INTERVAL '24 hours'
                    """
                )
                dns_changes = (cur.fetchone() or {}).get("cnt", 0)
                lines.append(f"DNS changes (24h): {dns_changes}")
            except Exception:
                pass

            # Recon scans (recent)
            try:
                cur.execute(
                    """
                    SELECT status, COUNT(*) as cnt
                    FROM security_recon_scans
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    GROUP BY status
                    ORDER BY cnt DESC
                    """
                )
                recon = cur.fetchall()
                if recon:
                    r_str = " | ".join(f"{r['status']}:{r['cnt']}" for r in recon)
                    lines.append(f"Recon scans (7d): {r_str}")
            except Exception:
                pass

            # Active supervision schedules
            try:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM supervision_schedules
                    WHERE is_active = true
                    """
                )
                sched = (cur.fetchone() or {}).get("cnt", 0)
                if sched:
                    lines.append(f"Active supervision schedules: {sched}")
            except Exception:
                pass

    except Exception as exc:
        lines.append(f"[Briefing data unavailable: {exc}]")

    lines.append(
        "\n[V.I.G.I.L. SECURITY & NETWORK FEATURES]\n"
        "Tabs: Overview (status + alerts + events) | Traffic (network activity) | "
        "DNS (Hostinger DNS CRUD + audit trail) | Devices (discovery + supervision) | "
        "Compliance (5 rule packs: Ubuntu STIG/Docker STIG/HIPAA/Network STIG/CIS) | "
        "Cameras (Home Assistant streams) | Recon (nmap/port scans) | "
        "SSL (cert watch + expiry alerts) | NPM (proxy host lifecycle) | Settings.\n"
        "Compliance scoring: Green ≥90%, Blue ≥80%, Yellow ≥70%, Red <60%.\n"
        "Supervision: per-device AdGuard blocking by category + time window.\n"
        "Lockout: auto-block on port scan detection, rate-limit alerts via Telegram.\n"
        "[End briefing — use this data to answer questions and suggest remediation. "
        "Propose actions using the [ACTION]{...}[/ACTION] format when asked to act.]\n"
    )
    return "\n".join(lines)
