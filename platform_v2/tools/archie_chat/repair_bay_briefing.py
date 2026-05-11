"""Live Repair Bay briefing injected into F.O.R.G.E. chat context."""

from services.time_utils import now_local_str


def _build_repair_bay_briefing() -> str:
    """
    Return a plain-text briefing of the Repair Bay's current state.
    Prepended to the user's first message in new F.O.R.G.E. conversations
    so he can answer status questions without extra fetches.
    """
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[F.O.R.G.E. REPAIR BAY BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Open pull requests
            cur.execute("SELECT COUNT(*) AS cnt FROM pull_requests WHERE state = 'open'")
            open_prs = (cur.fetchone() or {}).get("cnt", 0)

            cur.execute(
                "SELECT pr_number, title, created_at FROM pull_requests "
                "WHERE state = 'open' ORDER BY created_at DESC LIMIT 1"
            )
            latest_pr = cur.fetchone()
            if latest_pr:
                from datetime import datetime, timezone

                age = datetime.now(timezone.utc) - latest_pr["created_at"].replace(tzinfo=timezone.utc)
                h = int(age.total_seconds() // 3600)
                lines.append(
                    f"Open PRs: {open_prs} (newest: #{latest_pr['pr_number']} — {latest_pr['title'][:60]}, {h}h ago)"
                )
            else:
                lines.append(f"Open PRs: {open_prs}")

            # Improvement proposals by status
            cur.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM improvement_proposals
                WHERE status IN ('pending', 'proposed', 'approved', 'sandbox_testing', 'sandbox_failed')
                GROUP BY status
                ORDER BY cnt DESC
                """
            )
            proposal_rows = cur.fetchall() or []
            if proposal_rows:
                proposal_parts = [f"{r['status']}={r['cnt']}" for r in proposal_rows]
                total_pending = sum(r["cnt"] for r in proposal_rows)
                lines.append(f"Proposals pending action: {total_pending} ({', '.join(proposal_parts)})")
            else:
                lines.append("Proposals pending action: none")

            # Last code scan
            cur.execute(
                "SELECT file_path, issues_found, security_issues, quality_score, scanned_at "
                "FROM code_scans ORDER BY scanned_at DESC LIMIT 1"
            )
            last_scan = cur.fetchone()
            if last_scan:
                from datetime import datetime, timezone

                age = datetime.now(timezone.utc) - last_scan["scanned_at"].replace(tzinfo=timezone.utc)
                h = int(age.total_seconds() // 3600)
                score = round(float(last_scan["quality_score"] or 0), 1)
                lines.append(
                    f"Last scan: {h}h ago — {last_scan['issues_found']} issues "
                    f"({last_scan['security_issues']} security), quality score {score}"
                )
            else:
                lines.append("Last scan: no scan recorded")

            # Repair queue (dependency / vuln items)
            cur.execute(
                "SELECT severity, COUNT(*) AS cnt FROM repair_queue "
                "WHERE status NOT IN ('dismissed', 'resolved', 'fixed') "
                "GROUP BY severity ORDER BY cnt DESC"
            )
            rq_rows = cur.fetchall() or []
            if rq_rows:
                rq_parts = [f"{r['severity']}={r['cnt']}" for r in rq_rows]
                total_rq = sum(r["cnt"] for r in rq_rows)
                lines.append(f"Repair queue: {total_rq} open items ({', '.join(rq_parts)})")
            else:
                lines.append("Repair queue: clear")

            # Last QA run
            cur.execute(
                """
                SELECT r.status, r.passed, r.failed, r.errors, r.completed_at,
                       s.name AS suite_name
                FROM qa_test_runs r
                LEFT JOIN qa_test_suites s ON s.id = r.suite_id
                WHERE r.completed_at IS NOT NULL
                ORDER BY r.completed_at DESC LIMIT 1
                """
            )
            last_qa = cur.fetchone()
            if last_qa:
                from datetime import datetime, timezone

                age = datetime.now(timezone.utc) - last_qa["completed_at"].replace(tzinfo=timezone.utc)
                h = int(age.total_seconds() // 3600)
                verdict = "✅" if last_qa["failed"] == 0 and last_qa["errors"] == 0 else "⚠️"
                lines.append(
                    f"Last QA run: {verdict} {last_qa['suite_name'] or 'unknown'} — "
                    f"{last_qa['passed']} passed, {last_qa['failed']} failed, "
                    f"{last_qa['errors']} errors ({h}h ago)"
                )
            else:
                lines.append("Last QA run: no runs recorded")

    except Exception as e:
        lines.append(f"[Briefing fetch error: {e}]")

    lines.append(
        "\nYou are F.O.R.G.E. — Full-cycle Optimization & Regenerative GitHub Engine. "
        "You own the Repair Bay: scanning, proposals, sandboxing, QA, and deployments. "
        "Be direct, technical, and action-oriented."
    )
    lines.append("")
    return "\n".join(lines)
