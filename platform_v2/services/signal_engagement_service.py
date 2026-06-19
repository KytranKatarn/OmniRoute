"""S.I.G.N.A.L. engagement proposals — queue approval-gated LinkedIn likes/comments.

Every engagement action (like / proactive comment) is PROPOSED here, not fired
directly: it creates an ``autonomy_approval_queue`` row (action_type
``linkedin_like`` / ``linkedin_comment``) which the triage consumer escalates to
Telegram with Approve/Deny buttons (#4325) and the approval executor fires only on
Approve (agent_loop._execute_approved_action). Nothing reaches LinkedIn without a
human tap.

Used by the manual trigger (POST /api/signal/engage) now; an auto engagement
monitor (Phase 2) can call the same helpers.
"""

import logging

logger = logging.getLogger(__name__)

# Which browser identity acts for each account. terry = its own session (377);
# personal/company/creed ride the Kytran 342 session (company/creed actor-switch
# only matters for POSTING — a like/comment is made as the logged-in identity).
_ACCOUNT_BROWSER_ID = {"personal": 342, "terry": 377, "company": 342, "creed": 342}

_VALID_REACTIONS = {"like", "celebrate", "support", "love", "insightful", "funny"}


def _request_approval(action_type: str, action_data: dict, reason: str, requested_by: str):
    """Enqueue a Tier-2 approval via the same path signal_calendar_service uses."""
    from services.signal_calendar_service import _ensure_import_paths

    _ensure_import_paths()
    from ai_bridge.agent_loop import request_approval

    return request_approval(
        action_type=action_type,
        action_data=action_data,
        reason=reason,
        tier=2,
        requested_by=requested_by,
        priority=6,
    )


def propose_like(
    post_url: str,
    account: str = "personal",
    reaction: str = "like",
    agent_id: int = None,
    requested_by: str = "S.I.G.N.A.L. engagement (manual)",
) -> int:
    """Queue an approval-gated reaction on a post. Returns the approval id."""
    post_url = (post_url or "").strip()
    if not post_url:
        raise ValueError("post_url is required")
    reaction = (reaction or "like").lower()
    if reaction not in _VALID_REACTIONS:
        raise ValueError(f"reaction must be one of {sorted(_VALID_REACTIONS)}")
    aid = agent_id or _ACCOUNT_BROWSER_ID.get(account, 342)
    return _request_approval(
        "linkedin_like",
        {"post_url": post_url, "reaction": reaction, "browser_agent_id": aid, "account": account},
        reason=f"👍 Approve {reaction} on {post_url} (as {account})",
        requested_by=requested_by,
    )


def propose_comment(
    post_url: str,
    comment: str,
    account: str = "personal",
    agent_id: int = None,
    requested_by: str = "S.I.G.N.A.L. engagement (manual)",
) -> int:
    """Queue an approval-gated proactive comment on a post. Returns the approval id."""
    post_url = (post_url or "").strip()
    comment = (comment or "").strip()
    if not post_url:
        raise ValueError("post_url is required")
    if not comment:
        raise ValueError("comment is required")
    aid = agent_id or _ACCOUNT_BROWSER_ID.get(account, 342)
    return _request_approval(
        "linkedin_comment",
        {"post_url": post_url, "comment": comment, "browser_agent_id": aid, "account": account},
        reason=f"💬 Approve comment on {post_url} (as {account}):\n\n{comment[:500]}",
        requested_by=requested_by,
    )
