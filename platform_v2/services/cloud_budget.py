"""Cloud provider budget tracking — rolling 7-day usage vs free weekly limits.

Read-only foundation for Cloud Dispatch Governance (Dev HQ #3661 / component A).
Combines actual usage from ``cloud_model_usage`` with the per-provider free-tier
limits declared in ``contractor_providers.rate_limits`` so the rest of the
governance stack can answer one question: *does this provider have headroom left
this week?*

Consumed by:
  - the pre-dispatch budget guard (#3659) — block/rotate before exceeding a limit,
  - A.R.M.A.D.A. per-provider usage meters (#3662),
  - K.I.N. ops view + A.R.C.H.I.E. briefing (budget awareness),
  - C.R.E.E.D. governance posture (#3663).

Everything here is read-only and fail-safe (returns empty / fail-open on error)
so it can never block a real dispatch by itself.
"""

from typing import List, Dict, Optional

# Rolling window the free weekly limits are measured against.
_WINDOW_DAYS = 7


def cloud_budget_status(tier: str = "free") -> List[Dict]:
    """Per-provider budget rows for the given pricing ``tier`` (default 'free').

    Each row: ``{provider, model, used_7d, weekly_limit, remaining, pct_used,
    over_limit}``. ``weekly_limit``/``remaining``/``pct_used`` are ``None`` when a
    provider declares no limit (unlimited). Providers with no declared limit for
    the tier are skipped. Fail-safe → ``[]``.
    """
    rows: List[Dict] = []
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_c, cur):
            cur.execute(
                """
                SELECT cp.provider_key,
                       cp.default_model,
                       cp.is_cloud_proxy,
                       (cp.rate_limits -> %s ->> 'weekly_limit') AS weekly_limit,
                       COALESCE(u.used_7d, 0)                    AS used_7d
                FROM contractor_providers cp
                LEFT JOIN (
                    SELECT model_name, COUNT(*) AS used_7d
                    FROM cloud_model_usage
                    WHERE created_at > NOW() - (%s || ' days')::interval
                    GROUP BY model_name
                ) u ON u.model_name = cp.default_model
                WHERE cp.is_active
                  AND cp.rate_limits ? %s
                ORDER BY cp.provider_key
                """,
                (tier, str(_WINDOW_DAYS), tier),
            )
            for r in cur.fetchall():
                raw_limit = r.get("weekly_limit")
                limit = int(raw_limit) if raw_limit not in (None, "", "null") else None
                used = int(r.get("used_7d") or 0)
                remaining = (limit - used) if limit is not None else None
                pct = round(100.0 * used / limit, 1) if limit else None
                rows.append(
                    {
                        "provider": r["provider_key"],
                        "model": r["default_model"],
                        "is_cloud_proxy": bool(r.get("is_cloud_proxy")),
                        "used_7d": used,
                        "weekly_limit": limit,
                        "remaining": remaining,
                        "pct_used": pct,
                        "over_limit": (limit is not None and used >= limit),
                    }
                )
    except Exception:
        return []
    return rows


def _row_for_model(model: str, tier: str = "free") -> Optional[Dict]:
    """Match a (possibly ':cloud'-suffixed) model name to its budget row."""
    base = (model or "").replace(":cloud", "").strip()
    for row in cloud_budget_status(tier):
        if row["model"] == base or base.startswith(row["model"]) or row["model"].startswith(base):
            return row
    return None


def has_cloud_headroom(model: str, margin: int = 0, tier: str = "free") -> bool:
    """True if the provider serving ``model`` is under ``weekly_limit - margin``.

    Fail-open: unknown model or no declared limit → ``True`` (never block on
    uncertainty). The actual enforcement decision lives in the budget guard
    (#3659); this is the shared predicate it will use.
    """
    row = _row_for_model(model, tier)
    if not row or row["weekly_limit"] is None:
        return True
    return row["used_7d"] < (row["weekly_limit"] - max(0, margin))


def providers_with_headroom(margin: int = 0, tier: str = "free") -> List[Dict]:
    """Budget rows that still have headroom, most-remaining first.

    Drives provider rotation in the budget guard (try the freest provider first).
    Unlimited providers sort ahead of limited ones.
    """
    rows = [r for r in cloud_budget_status(tier) if not r["over_limit"]]
    rows = [r for r in rows if r["weekly_limit"] is None or r["used_7d"] < (r["weekly_limit"] - max(0, margin))]
    rows.sort(
        key=lambda r: (r["remaining"] is not None, r["remaining"] if r["remaining"] is not None else 0), reverse=True
    )
    return rows
