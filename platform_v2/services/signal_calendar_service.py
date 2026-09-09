"""S.I.G.N.A.L. content calendar — Phase 1: backfill + scheduled queue (#3989).

Calendar store = agent_content_posts (platform='linkedin', status='scheduled',
scheduled_at stored as naive UTC per platform convention). Account scoping
lives in post_type ('personal' | 'terry' | 'company' | 'creed'); the owning
identity row is agents.id 342 (Kytran) for personal/company/creed and 377
(Terry Caetano) for terry — the same identities the posting path uses.

Backfill gathers the failed linkedin_post_log backlog plus approved-but-unsent
creed marketing assets, dedupes by content hash (the ~40 failed rows are mostly
retry artifacts of the broken-session window), drops anything already posted /
pending approval / scheduled, and fans the unique remainder forward 1 post per
day per account at 09:00 America/Toronto. Forward-only: LinkedIn cannot
backdate. Release to the approval queue is Phase 2 — nothing here publishes.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from database import get_db_cursor
from services import signal_accounts
from services.signal_content_sanitizer import clean_draft

logger = logging.getLogger("platform.signal_calendar")

_LOCAL_TZ = ZoneInfo("America/Toronto")
RELEASE_HOUR_LOCAL = 9  # 09:00 ET, converted to UTC at insert

# Account model (account_keys, post_type aliases, agent_id/browser_id, label) is resolved
# from the registry via services.signal_accounts (migration 440). account_keys(can_post=True)
# replaces the old fixed ACCOUNTS tuple — so ARCHIE / supporting majors auto-join the calendar
# once their account is established (can_post flips true).


def _fold(content: Optional[str], hashtags: Any) -> str:
    """Canonical post text: content with hashtags appended, stripped."""
    text = (content or "").strip()
    tags = [t for t in (hashtags or []) if t]
    if tags:
        text += "\n\n" + " ".join(f"#{str(t).lstrip('#')}" for t in tags)
    return text


def _hash(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()


def _ensure_import_paths() -> None:
    """agent_loop / department_dispatcher internally do `from db import ...`,
    which resolves from the ai_bridge package dir. That dir differs per
    container mount (/app/ai_bridge vs /mnt/archie_brain/ai_bridge), so add
    /app plus wherever ai_bridge actually resolves from."""
    import importlib.util
    import sys

    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    spec = importlib.util.find_spec("ai_bridge")
    if spec and spec.submodule_search_locations:
        pkg_dir = list(spec.submodule_search_locations)[0]
        if pkg_dir not in sys.path:
            sys.path.insert(0, pkg_dir)


def _seen_hashes(cur) -> set:
    """Content hashes that must NOT be scheduled again: already posted,
    already pending/approved in the queue, or already on the calendar."""
    seen = set()
    cur.execute("SELECT content, hashtags FROM linkedin_post_log WHERE status = 'posted'")
    for row in cur.fetchall():
        seen.add(_hash(_fold(row["content"], row["hashtags"])))
    cur.execute(
        """SELECT action_data FROM autonomy_approval_queue
           WHERE action_type = 'linkedin_post' AND status IN ('pending', 'approved')"""
    )
    for row in cur.fetchall():
        data = row["action_data"] or {}
        seen.add(_hash(_fold(data.get("content"), data.get("hashtags"))))
    cur.execute(
        """SELECT content FROM agent_content_posts
           WHERE platform = 'linkedin' AND status IN ('scheduled', 'released')"""
    )
    for row in cur.fetchall():
        seen.add(_hash(row["content"]))
    return seen


def _candidates(cur) -> List[Dict[str, Any]]:
    """Backlog candidates, newest first: failed post-log rows + approved
    unsent creed linkedin assets."""
    out: List[Dict[str, Any]] = []
    cur.execute(
        """SELECT content, hashtags, post_type, created_at
           FROM linkedin_post_log WHERE status = 'failed'
           ORDER BY created_at DESC"""
    )
    for row in cur.fetchall():
        account = signal_accounts.post_type_to_account(row["post_type"] or "personal", default=None)
        if account:
            out.append({"account": account, "text": _fold(row["content"], row["hashtags"])})
    cur.execute(
        """SELECT content FROM creed_marketing_assets
           WHERE approved = TRUE AND gen_status = 'done' AND channel = 'linkedin'
             AND content IS NOT NULL
           ORDER BY created_at DESC"""
    )
    for row in cur.fetchall():
        out.append({"account": "creed", "text": _fold(row["content"], None)})
    return out


def _next_slot_utc(cur, account: str) -> datetime:
    """First free calendar day for ``account``: the later of tomorrow and the
    day after its last scheduled slot, at 09:00 ET (returned as naive UTC)."""
    post_types = signal_accounts.post_types_for(account)
    cur.execute(
        """SELECT MAX(scheduled_at) AS last FROM agent_content_posts
           WHERE platform = 'linkedin' AND status = 'scheduled'
             AND post_type = ANY(%s)""",
        (list(post_types),),
    )
    last = (cur.fetchone() or {}).get("last")
    today_local = datetime.now(_LOCAL_TZ).date()
    start_local = today_local + timedelta(days=1)
    if last is not None:
        last_local = last.replace(tzinfo=ZoneInfo("UTC")).astimezone(_LOCAL_TZ).date()
        start_local = max(start_local, last_local + timedelta(days=1))
    slot_local = datetime.combine(start_local, datetime.min.time().replace(hour=RELEASE_HOUR_LOCAL), tzinfo=_LOCAL_TZ)
    return slot_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def backfill_calendar() -> Dict[str, Any]:
    """One-shot: dedup the backlog and fan it onto each account's calendar,
    1/day starting tomorrow. Idempotent — re-runs only append genuinely new
    content after the account's last scheduled slot."""
    summary: Dict[str, Any] = {
        a: {"scheduled": 0, "skipped_dupe": 0} for a in signal_accounts.account_keys(can_post=True)
    }
    with get_db_cursor(commit=True) as (_conn, cur):
        seen = _seen_hashes(cur)
        slots = {a: _next_slot_utc(cur, a) for a in signal_accounts.account_keys(can_post=True)}
        for cand in _candidates(cur):
            account, text = cand["account"], cand["text"]
            if not text:
                continue
            h = _hash(text)
            if h in seen:
                summary[account]["skipped_dupe"] += 1
                continue
            seen.add(h)
            cur.execute(
                """INSERT INTO agent_content_posts
                       (agent_id, platform, content, post_type, status, scheduled_at)
                   VALUES (%s, 'linkedin', %s, %s, 'scheduled', %s)""",
                (
                    signal_accounts.agent_id_for(account),
                    text,
                    signal_accounts.post_type_for(account),
                    slots[account],
                ),
            )
            summary[account]["scheduled"] += 1
            slots[account] += timedelta(days=1)
    total = sum(v["scheduled"] for v in summary.values())
    logger.info("[signal-calendar] backfill scheduled %s post(s): %s", total, summary)
    return {"total_scheduled": total, "by_account": summary}


def get_scheduled(account: str, limit: int = 60) -> List[Dict[str, Any]]:
    """Scheduled (not yet released) calendar entries for one account."""
    post_types = signal_accounts.post_types_for(account)
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT id, content, post_type, status, scheduled_at, created_at
               FROM agent_content_posts
               WHERE platform = 'linkedin' AND status = 'scheduled'
                 AND post_type = ANY(%s)
               ORDER BY scheduled_at ASC
               LIMIT %s""",
            (list(post_types), limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        for k in ("scheduled_at", "created_at"):
            if r.get(k):
                r[k] = r[k].isoformat()
    return rows


def cancel_scheduled(post_id: int) -> bool:
    """Cancel one scheduled entry (owner pruning stale backlog content)."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """UPDATE agent_content_posts SET status = 'cancelled'
               WHERE id = %s AND status = 'scheduled'
               RETURNING id""",
            (post_id,),
        )
        return cur.fetchone() is not None


# Account labels + browser identities → services.signal_accounts registry (migration 440).


def _linkedin_profile_healthy(cur, agent_id: int) -> bool:
    """True unless the agent's LinkedIn POSTING profile is KNOWN logged-out/stale (#3948).

    Posting authenticates from the on-disk persistent profile (/profiles/<agent>-linkedin),
    NOT the browser_sessions cookie. But the health probe (browser_profile_service.
    run_session_health_probe) runs a skill IN that same profile, so browser_sessions.status /
    last_probe_ok is a faithful proxy for posting-auth health. FAIL-OPEN: no row / unknown /
    error -> True (only suppress when we POSITIVELY know the profile is dead).
    """
    try:
        # Parameterized query (%s + tuple) — agent_id is an int from the signal_accounts
        # registry resolver, never user input: no injection surface.
        cur.execute(
            "SELECT status FROM browser_sessions " "WHERE agent_id = %s AND platform = 'linkedin' LIMIT 1",
            (agent_id,),
        )
        row = cur.fetchone()
        if not row:
            return True
        status = (row["status"] if isinstance(row, dict) else row[0]) or ""
        # Gate ONLY on a positive 'stale' (a probe POSITIVELY detected a login/authwall,
        # #4372). last_probe_ok is intentionally NOT part of the gate any more: a transient
        # probe failure no longer sets it False (record_probe keeps the last-good values),
        # so the calendar can't be paused for an authed profile that merely had one slow or
        # lock-contended probe — the false-negative that stalled the whole calendar.
        return status != "stale"
    except Exception as exc:
        # Fail-open by design: a health-read bug must never block release. Log for traceability.
        logger.debug("[signal-calendar] linkedin profile health check failed (fail-open True): %s", exc)
        return True


def _alert_linkedin_stale(account: str, agent_id: int) -> None:
    """Deduped (12h/account) Telegram alert: an account's LinkedIn posting profile is logged
    out, so calendar release is paused for it. The fix is a HEADED re-auth via the S.I.G.N.A.L.
    Session subtab (noVNC) — a Cookie-Editor import only refreshes the READ path, not the
    posting profile (#3948). Best-effort; never blocks release."""
    key = f"signal:linkedin_stale_alert:{account}"
    try:
        from datetime import datetime

        from services.time_utils import now_utc

        now = now_utc()
        with get_db_cursor(commit=True) as (_c, c):
            c.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = c.fetchone()
            if row:
                last = row["value"] if isinstance(row, dict) else row[0]
                try:
                    if last and (now - datetime.fromisoformat(last)).total_seconds() < 12 * 3600:
                        return  # already alerted within 12h
                except Exception:
                    pass
            c.execute(
                "INSERT INTO platform_settings(key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, now.isoformat()),
            )
    except Exception as exc:
        logger.debug("[signal-calendar] stale-alert dedup check failed (best-effort): %s", exc)
    try:
        from services import telegram_service

        label = signal_accounts.label_for(account)
        telegram_service.send_system(
            f"LinkedIn posting paused — {label}",
            f"The {label} LinkedIn posting profile (agent {agent_id}, "
            f"/profiles/{agent_id}-linkedin) is logged out — calendar release is PAUSED for "
            f"this account so no failed posts pile up.\n\n"
            f"FIX: DHQ → S.I.G.N.A.L. → 🔐 Session → noVNC headed login for agent {agent_id}. "
            f"A Cookie-Editor import only fixes the READ path, not posting (#3948).",
        )
    except Exception as exc:
        logger.debug("[signal-calendar] stale-alert telegram send failed (best-effort): %s", exc)


def release_due_posts(max_per_account: int = 1) -> Dict[str, Any]:
    """Phase 2 (#3990): promote due scheduled posts into the linkedin_post
    approval queue (Telegram human gate — nothing publishes from here).

    At most ``max_per_account`` per run so an outage drains at the designed
    1/day cadence instead of bursting every overdue post into approvals.
    The existing content-keyed approval dedup still applies downstream.
    """
    import json as _json

    _ensure_import_paths()
    from ai_bridge.agent_loop import request_approval
    from services.time_utils import now_utc

    now_naive_utc = now_utc().replace(tzinfo=None)
    summary: Dict[str, Any] = {a: 0 for a in signal_accounts.account_keys(can_post=True)}
    skipped_stale: List[str] = []
    for account in signal_accounts.account_keys(can_post=True):
        post_types = signal_accounts.post_types_for(account)
        with get_db_cursor(commit=True) as (_conn, cur):
            # #3948: don't release into a logged-out posting profile — the post would just
            # hang ~120s and fail downstream. Pause this account + alert the owner to re-auth;
            # posts stay 'scheduled' and drain once the profile is restored.
            if not _linkedin_profile_healthy(cur, signal_accounts.agent_id_for(account)):
                skipped_stale.append(account)
                logger.warning(
                    "[signal-calendar] %s posting profile logged out — skipping release, alerting owner",
                    account,
                )
                _alert_linkedin_stale(account, signal_accounts.agent_id_for(account))
                continue
            cur.execute(
                """SELECT id, content, post_type FROM agent_content_posts
                   WHERE platform = 'linkedin' AND status = 'scheduled'
                     AND post_type = ANY(%s) AND scheduled_at <= %s
                   ORDER BY scheduled_at ASC
                   LIMIT %s""",
                (list(post_types), now_naive_utc, max_per_account),
            )
            due = [dict(r) for r in cur.fetchall()]
            for row in due:
                approval_id = request_approval(
                    action_type="linkedin_post",
                    action_data={
                        "content": row["content"],
                        "hashtags": [],  # already folded into content at backfill
                        "post_type": row["post_type"],
                        "browser_agent_id": signal_accounts.browser_id_for(account),
                        # S6-P1-8b: precompute the idempotency key from the calendar slot so a
                        # timed-out + retried release cannot double-publish this exact post.
                        "scheduled_post_id": row["id"],
                        "idempotency_key": signal_accounts.idempotency_key_for(
                            account, row["post_type"], row["content"], row["id"]
                        ),
                        "priority": 6,
                    },
                    reason=(
                        f"📅 {signal_accounts.label_for(account)} scheduled post (calendar):\n\n"
                        f"{row['content'][:1500]}"
                    ),
                    tier=2,
                    requested_by="S.I.G.N.A.L. calendar (daily release)",
                    priority=6,
                )
                cur.execute(
                    """UPDATE agent_content_posts
                       SET status = 'released',
                           engagement_stats = engagement_stats || %s::jsonb
                       WHERE id = %s""",
                    (
                        _json.dumps(
                            {
                                "approval_id": approval_id,
                                "released_at": now_utc().isoformat(),
                            }
                        ),
                        row["id"],
                    ),
                )
                summary[account] += 1
                logger.info(
                    "[signal-calendar] released post %s (%s) → approval %s",
                    row["id"],
                    account,
                    approval_id,
                )
    total = sum(summary.values())
    return {"total_released": total, "by_account": summary, "skipped_stale": skipped_stale}


def _terry_profile_established() -> bool:
    """Terry (377) is a separate LinkedIn login — don't generate content for
    an account that can't post yet. Fail closed on any error."""
    import os

    import requests

    try:
        r = requests.get(
            "http://archie_browser_login:4281/status",
            params={"agent_id": 377, "platform": "linkedin"},
            headers={
                "Authorization": f"Bearer {(os.getenv('BROWSER_LOGIN_API_KEY') or os.getenv('INTERNAL_API_KEY', ''))}"
            },
            timeout=5,
        )
        return bool((r.json() or {}).get("profile_established"))
    except Exception:
        return False


def _wtf_recent_headlines(limit: int = 6) -> str:
    """Live grounding for the What The Fact group: recent REAL headlines + outlet
    from the separate ``wtf`` database (same hub postgres). Gives the model
    factual material so it writes about actual coverage instead of inventing
    stories/quotes — a fact-checking brand must never fabricate. Fail-open:
    returns '' on any error (the caller then falls back to theme-only grounding).
    Connection mirrors tools/wtf_hub/routes.py (wtfuser / WTF_DB_PASSWORD)."""
    import os as _os

    try:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            host=_os.getenv("WTF_DB_HOST", "archie_database"),
            port=int(_os.getenv("WTF_DB_PORT", "5432")),
            dbname="wtf",
            user=_os.getenv("WTF_DB_USER", "wtfuser"),
            password=_os.getenv("WTF_DB_PASSWORD", ""),
            options="-c search_path=wtf",
            connect_timeout=5,
        )
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT a.title, s.name AS outlet
                         FROM wtf.articles a
                         JOIN wtf.sources s ON s.id = a.source_id
                        WHERE a.published_at > NOW() - INTERVAL '2 days'
                          AND a.title IS NOT NULL
                        ORDER BY a.published_at DESC
                        LIMIT %s""",
                    (max(1, int(limit)),),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — fail-open grounding, never block generation
        logger.debug("[signal-calendar] wtf headline grounding unavailable: %s", exc)
        return ""

    items = [
        f'- "{(r["title"] or "").strip()}" ({(r.get("outlet") or "outlet").strip()})'
        for r in rows
        if (r.get("title") or "").strip()
    ]
    if not items:
        return ""
    return (
        "Recent What The Fact coverage (REAL headlines — base the post on these, "
        "do NOT invent stories, quotes, or outlets beyond this list):\n" + "\n".join(items)
    )


def _generation_context(cur, account: str) -> str:
    """Grounding for fresh-content generation: today's theme for the account
    (social_content_calendar/themes) + recent platform wins."""
    parts = []
    try:
        weekday = datetime.now(_LOCAL_TZ).weekday()
        cur.execute(
            """SELECT sct.name, sct.tone
               FROM social_content_calendar scc
               JOIN social_content_themes sct ON sct.id = scc.theme_id
               WHERE scc.account = %s AND scc.day_of_week = %s AND scc.is_active = TRUE
               ORDER BY scc.slot_order LIMIT 1""",
            (account, weekday),
        )
        theme = cur.fetchone()
        if theme:
            parts.append(f"Today's theme: {theme['name']} — {theme['tone'] or ''}".strip())
    except Exception:
        pass
    # The What The Fact group AND the WTF journalist (stringer) ground on REAL
    # recent WTF coverage (live wtf DB) so the model writes about actual
    # headlines instead of inventing stories — a fact-checking brand must never
    # fabricate. "Recent platform wins" (the founder/company narrative) is
    # OFF-BRAND there, so it is suppressed.
    if account in ("wtf_group", "stringer"):
        headlines = _wtf_recent_headlines()
        if headlines:
            parts.append(headlines)
    else:
        try:
            # Exclude internal/automation task titles ([DELEGATE:...], [codex],
            # bracket-prefixed bookkeeping) — they leaked into a generated draft
            # verbatim during the #3991 live test.
            cur.execute(
                """SELECT title FROM unified_tasks
                   WHERE status = 'completed' AND updated_at > NOW() - INTERVAL '7 days'
                     AND title NOT LIKE '[%'
                   ORDER BY updated_at DESC LIMIT 5"""
            )
            wins = [r["title"] for r in cur.fetchall()]
            if wins:
                parts.append("Recent platform wins: " + "; ".join(wins[:3]))
        except Exception:
            pass
    return "\n".join(parts) or "No specific theme today — pick a grounded, relevant topic."


def top_up_calendars(min_days_ahead: int = 3) -> Dict[str, Any]:
    """Phase 3 (#3991): when an account's scheduled backlog is thinner than
    ``min_days_ahead`` posts, generate ONE fresh post via S.I.G.N.A.L.
    (capability='social_post_draft' through the DHQ dispatcher) and append it
    to that account's calendar at the next free 1/day slot.

    English-only v1 (non-EN stays on the R.O.S.E.T.T.A. translate path, KB
    #272121). Cold model → skip this run; the daily job retries tomorrow.
    Everything still flows through the Phase 2 release → Telegram approval
    gate — generation never publishes."""
    _ensure_import_paths()
    from signal_dispatch import _PLATFORM_HINTS, _VOICE_HINTS
    from tools.department_hq.services.department_dispatcher import dispatch
    from services.welfare_governance_service import pool_over_budget_by_skill

    # Welfare gate (ADR-002): defer discretionary generation when the social_post_draft
    # pool has no 24h token-budget headroom. Fail-open. Scheduled posts still release on
    # the next signal_calendar_release; only NEW generation is paused. Tunable via
    # platform_settings welfare:signal:pool_pause_ratio (default 0.9).
    if pool_over_budget_by_skill("social_post_draft", "welfare:signal:pool_pause_ratio"):
        logger.info(
            "[signal-calendar] top-up deferred — social_post_draft pool over 24h "
            "token budget (welfare-gated, ADR-002)"
        )
        return {"by_account": {}, "note": "welfare-gated: social_post_draft pool over 24h budget"}

    summary: Dict[str, Any] = {}
    for account in signal_accounts.account_keys(can_post=True):
        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute(
                """SELECT COUNT(*) AS n FROM agent_content_posts
                   WHERE platform = 'linkedin' AND status = 'scheduled'
                     AND post_type = ANY(%s)""",
                (list(signal_accounts.post_types_for(account)),),
            )
            backlog = int((cur.fetchone() or {}).get("n") or 0)
        if backlog >= min_days_ahead:
            summary[account] = {"backlog": backlog, "generated": 0, "note": "topped up"}
            continue
        if account == "terry" and not _terry_profile_established():
            summary[account] = {
                "backlog": backlog,
                "generated": 0,
                "note": "terry profile not established — skipped",
            }
            continue

        with get_db_cursor(commit=False) as (_conn, cur):
            context = _generation_context(cur, account)
        post_type = signal_accounts.post_type_for(account)
        prompt = (
            f"Write a fresh LinkedIn post for the {signal_accounts.label_for(account)} account.\n\n"
            f"Grounding:\n{context}\n\n"
            f"{_VOICE_HINTS.get(post_type, _VOICE_HINTS['personal'])} "
            f"{_PLATFORM_HINTS.get('linkedin', '')}\n"
            f"English only. Under 200 words. End with an engagement question. "
            f"Pick 3-4 relevant hashtags and put them on the final line."
        )
        result = dispatch(
            capability="social_post_draft",
            prompt=prompt,
            prefer_agent="S.I.G.N.A.L.",
        )
        draft = (getattr(result, "response", "") or "").strip()
        draft = clean_draft(draft, kind=post_type)  # #4373 — strip model preamble/sign-offs
        if not draft:
            summary[account] = {
                "backlog": backlog,
                "generated": 0,
                "note": "model cold/queued — retry next run",
            }
            continue

        with get_db_cursor(commit=True) as (_conn, cur):
            if _hash(draft) in _seen_hashes(cur):
                summary[account] = {"backlog": backlog, "generated": 0, "note": "dupe draft"}
                continue
            slot = _next_slot_utc(cur, account)
            cur.execute(
                """INSERT INTO agent_content_posts
                       (agent_id, platform, content, post_type, status, scheduled_at)
                   VALUES (%s, 'linkedin', %s, %s, 'scheduled', %s)
                   RETURNING id""",
                (signal_accounts.agent_id_for(account), draft, post_type, slot),
            )
            new_id = (cur.fetchone() or {}).get("id")
        summary[account] = {"backlog": backlog + 1, "generated": 1, "post_id": new_id}
        logger.info(
            "[signal-calendar] top-up generated post %s for %s (slot %s)",
            new_id,
            account,
            slot,
        )
    return {"by_account": summary}
