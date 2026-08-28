"""Live Account Center briefing injected into R.E.S.O.L.V.E. chat context."""

from services.time_utils import now_local_str


def _build_account_center_briefing() -> str:
    """
    Return a plain-text briefing of the Account Center's current state.
    Prepended to every R.E.S.O.L.V.E. message so she can answer status
    questions and give informed suggestions without extra fetches.
    """
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[R.E.S.O.L.V.E. ACCOUNT CENTER BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # User counts by role
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE role = 'admin' OR is_admin = true) AS admins,
                    COUNT(*) FILTER (WHERE locked_until IS NOT NULL AND locked_until > NOW()) AS locked,
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') AS new_this_week
                FROM users
                """
            )
            u = cur.fetchone() or {}
            lines.append(
                f"Users: {u.get('total', 0)} total | "
                f"{u.get('admins', 0)} admins | "
                f"{u.get('locked', 0)} locked | "
                f"{u.get('new_this_week', 0)} new this week"
            )

            # Subscription tiers
            cur.execute(
                """
                SELECT subscription_tier, COUNT(*) as cnt
                FROM users
                WHERE subscription_tier IS NOT NULL
                GROUP BY subscription_tier
                ORDER BY cnt DESC
                LIMIT 5
                """
            )
            tiers = cur.fetchall()
            if tiers:
                tier_str = ", ".join(f"{r['subscription_tier']}:{r['cnt']}" for r in tiers)
                lines.append(f"Subscription tiers: {tier_str}")

            # Failed logins — from users.failed_login_count (no auth_events table)
            cur.execute("SELECT COALESCE(SUM(failed_login_count), 0) AS fails FROM users")
            fails = (cur.fetchone() or {}).get("fails", 0)
            if fails and fails > 5:
                lines.append(f"⚠️ {fails} accumulated failed-login attempts across accounts")

            # Pending invites
            cur.execute(
                """
                SELECT COUNT(*) AS cnt FROM user_invites
                WHERE accepted_at IS NULL
                  AND (expires_at IS NULL OR expires_at > NOW())
                """
            )
            invites = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Pending invites: {invites}" if invites else "Pending invites: none")

            # Active API keys
            cur.execute("SELECT COUNT(*) AS cnt FROM chat_api_keys WHERE is_active = true")
            keys = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Active API keys: {keys}")

            # Active sessions (last 1h)
            try:
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT user_id) AS cnt FROM user_sessions
                    WHERE last_activity > NOW() - INTERVAL '1 hour'
                    """
                )
                sessions = (cur.fetchone() or {}).get("cnt", 0)
                lines.append(f"Active sessions (1h): {sessions}")
            except Exception:
                pass

    except Exception as exc:
        lines.append(f"[Briefing data unavailable: {exc}]")

    lines.append(
        "\n[R.E.S.O.L.V.E. ACCOUNT CENTER FEATURES]\n"
        "Tabs: Overview (stats + security alerts + quick actions) | Users (CRUD, roles, search) | "
        "Permissions (role hierarchy GUEST→SUPER_ADMIN) | Subscriptions | Security (lockout, 2FA) | "
        "Sessions (active, revoke) | API Keys (scopes: chat/read/admin) | Bulk Ops | Activity log | Orgs.\n"
        "Role levels: GUEST=5, USER=10, COLLABORATOR=15, PREMIUM=20, ADMIN=90, SUPER_ADMIN=100.\n"
        "Invite system: email+role via user_invites table, sent via Stalwart SMTP.\n"
        "Lockout: 5 failed attempts → 15min lock. IP rate limit: 20/15min.\n"
        "[End briefing — use this data to answer questions and suggest actions. "
        "Propose actions using the [ACTION]{...}[/ACTION] format when asked to do something.]\n"
    )
    return "\n".join(lines)
