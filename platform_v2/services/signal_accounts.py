"""S.I.G.N.A.L. account registry resolver (scale phase Slice 4a).

ONE place that answers "what is account X?" — replacing the ~5 duplicated literal dicts
(_ACCOUNT_AGENT_ID / _ACCOUNT_BROWSER_ID / _ACCOUNT_LABEL / _POST_TYPE_TO_ACCOUNT) across
signal_calendar_service, signal_engagement_service, linkedin_comment_monitor,
signal_calendar_live_service. Backed by the agent_platform_accounts registry (migration
440) so ARCHIE becomes a 3rd major + a supporting-agent fleet by DATA, not code.

Pattern mirrors creed_emit.py: TTL-cached read with a HARDCODED FALLBACK equal to today's
literals, so if the registry is empty/unreachable the behavior is IDENTICAL — no call site
can regress while we migrate them over.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("platform.signal_accounts")

_PLATFORM = "linkedin"
_TTL_S = 60.0
_cache: Dict[str, Any] = {"at": 0.0, "accounts": None, "pt_to_acct": None}

# Hardcoded fallback = the EXACT current literals (the 4 working accounts). ARCHIE is NOT
# here — it only exists once the registry is migrated, and it can't post until established.
_FALLBACK_ACCOUNTS: Dict[str, Dict[str, Any]] = {
    "personal": {
        "account_key": "personal",
        "agent_id": 342,
        "browser_agent_id": 342,
        "role": "major_author",
        "post_type": "personal",
        "company_slug": None,
        "display_label": "👤 Kytran Katarn",
        "can_post": True,
        "can_engage": False,
        "egress_pref": None,
        "profile_established": True,
    },
    "terry": {
        "account_key": "terry",
        "agent_id": 377,
        "browser_agent_id": 377,
        "role": "major_author",
        "post_type": "terry",
        "company_slug": None,
        "display_label": "👤 Terry Caetano",
        "can_post": True,
        "can_engage": False,
        "egress_pref": None,
        "profile_established": True,
    },
    "company": {
        "account_key": "company",
        "agent_id": 342,
        "browser_agent_id": 342,
        "role": "company_page",
        "post_type": "company",
        "company_slug": "106863155",
        "display_label": "🏢 Kytran Empowerment Inc.",
        "can_post": True,
        "can_engage": False,
        "egress_pref": None,
        "profile_established": True,
    },
    "creed": {
        "account_key": "creed",
        "agent_id": 342,
        "browser_agent_id": 342,
        "role": "company_page",
        "post_type": "creed",
        "company_slug": "115977300",
        "display_label": "⚖️ Creed-AI",
        "can_post": True,
        "can_engage": False,
        "egress_pref": None,
        "profile_established": True,
    },
}

# post_type alias → canonical account_key (preserves the existing _POST_TYPE_TO_ACCOUNT map).
_FALLBACK_PT_TO_ACCT = {
    "personal": "personal",
    "terry": "terry",
    "company": "company",
    "company_page": "company",
    "creed": "creed",
    "creed_ai": "creed",
}


def _load() -> None:
    """Refresh the cache from the registry; fall back to the literals on any failure."""
    now = time.monotonic()
    if _cache["accounts"] is not None and (now - _cache["at"]) < _TTL_S:
        return
    accounts: Optional[Dict[str, Dict[str, Any]]] = None
    pt_to_acct: Optional[Dict[str, str]] = None
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_c, cur):
            cur.execute(
                """SELECT account_key, agent_id, browser_agent_id, role, post_type,
                          company_slug, display_label, can_post, can_engage, egress_pref,
                          profile_established
                     FROM agent_platform_accounts
                    WHERE platform = %s AND account_key IS NOT NULL AND is_active = TRUE""",
                (_PLATFORM,),
            )
            rows = cur.fetchall()
        if rows:
            accounts = {}
            pt_to_acct = {}
            for r in rows:
                d = dict(r)
                key = d["account_key"]
                accounts[key] = d
                # canonical post_type → account_key, plus the known aliases
                pt = d.get("post_type") or key
                pt_to_acct[pt] = key
                pt_to_acct.setdefault(key, key)
            # keep the legacy aliases working even if a registry row omits them
            for alias, acct in _FALLBACK_PT_TO_ACCT.items():
                pt_to_acct.setdefault(alias, acct if acct in accounts else pt_to_acct.get(acct, acct))
    except Exception as exc:
        logger.debug("[signal_accounts] registry read failed, using fallback: %s", exc)
        accounts = None

    if not accounts:
        accounts = {k: dict(v) for k, v in _FALLBACK_ACCOUNTS.items()}
        pt_to_acct = dict(_FALLBACK_PT_TO_ACCT)
    _cache.update({"at": now, "accounts": accounts, "pt_to_acct": pt_to_acct})


def invalidate() -> None:
    _cache.update({"at": 0.0, "accounts": None, "pt_to_acct": None})


def get(account_key: str) -> Optional[Dict[str, Any]]:
    """Full registry row for an account_key (or None)."""
    _load()
    return _cache["accounts"].get(account_key)


def all_accounts(
    role: Optional[str] = None, can_post: Optional[bool] = None, can_engage: Optional[bool] = None
) -> List[Dict[str, Any]]:
    _load()
    out = []
    for d in _cache["accounts"].values():
        if role is not None and d.get("role") != role:
            continue
        if can_post is not None and bool(d.get("can_post")) != can_post:
            continue
        if can_engage is not None and bool(d.get("can_engage")) != can_engage:
            continue
        out.append(d)
    return out


def account_keys(**filters) -> List[str]:
    return [d["account_key"] for d in all_accounts(**filters)]


def post_type_to_account(post_type: str, default: Optional[str] = "personal") -> Optional[str]:
    """Map a post_type alias to its account_key. ``default`` is returned for an unknown
    post_type — pass default=None to preserve a 'skip unknown' caller (legacy
    _POST_TYPE_TO_ACCOUNT.get() returned None)."""
    _load()
    return _cache["pt_to_acct"].get((post_type or "").lower(), default)


def _field(account_key: str, field: str, default: Any = None) -> Any:
    d = get(account_key)
    return d.get(field) if d else default


def agent_id_for(account_key: str) -> int:
    return _field(account_key, "agent_id", 342) or 342


def browser_id_for(account_key: str) -> int:
    return _field(account_key, "browser_agent_id", 342) or 342


def label_for(account_key: str) -> str:
    return _field(account_key, "display_label", account_key) or account_key


def company_slug_for(account_key: str) -> Optional[str]:
    return _field(account_key, "company_slug")


def egress_for(account_key: str) -> Optional[str]:
    return _field(account_key, "egress_pref")


def post_type_for(account_key: str) -> str:
    """The canonical single post_type for an account (what the publish handler receives)."""
    return _field(account_key, "post_type", account_key) or account_key


def post_types_for(account_key: str) -> tuple:
    """All post_type aliases that map to this account (e.g. company -> (company, company_page)),
    canonical first. Behavior-identical to the legacy _ACCOUNT_TO_POST_TYPES tuple; defaults to
    (account_key,) for an unknown account."""
    _load()
    aliases = [pt for pt, acct in _cache["pt_to_acct"].items() if acct == account_key]
    if not aliases:
        return (account_key,)
    canon = post_type_for(account_key)
    ordered = ([canon] if canon in aliases else []) + [a for a in aliases if a != canon]
    return tuple(ordered)
