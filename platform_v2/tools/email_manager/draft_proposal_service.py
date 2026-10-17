"""Mail HQ Smart Inbox — Slices 3 + 4: agent-drafted, approve-to-send proposals.

Slice 3 (background job `run_mailhq_draft_proposals`): for newly-triaged
**action-priority** owner/business mail with no existing proposal, dispatch
R.E.S.O.L.V.E. (DHQ `capability='support'`, local fleet) to draft a reply, then
persist the proposal as an `autonomy_approval_queue` row (`action_type='email_reply'`)
and ping the owner via A.R.C.H.I.E. on Telegram with Approve / Cancel buttons.

Slice 4 executor (`execute_email_reply`): sends the drafted reply via the shared
`send_service.send_email_via_stalwart`. Called from BOTH the Telegram approve button
(`telegram_gateway._email_callback` action `replysend`) and the DHQ web Approvals tab
(`approvals_routes._approve_autonomy`). Idempotent — a double-tap cannot double-send.

Guardrails (mailhq-smart-inbox-design.md): nothing sends without the owner's tap; all
inference via DHQ dispatch (local fleet); A.R.C.H.I.E. is the sole outbound voice; the
draft job is gated OFF by default (`platform_settings mailhq:draft:enabled`) until the
send executor has been safety-tested.

NOTE: This module has been split into two sub-modules. This file re-exports everything
for backward compatibility.
"""

from .draft_proposal_helpers import (
    # Constants
    DRAFT_FLAG_KEY,
    COLLAB_FLAG_KEY,
    _ATTACHMENT_RE,
    _ATTEMPTS_KEY,
    _COLLAB_ATTEMPTS_KEY,
    _COLLAB_MAILBOX_TYPE,
    _COLLAB_MODEL,
    _COOLDOWN_MIN_KEY,
    _DEFAULT_COOLDOWN_MIN,
    _DEFAULT_MAX_ATTEMPTS,
    _DRAFT_MAILBOX_TYPES,
    _DRAFT_PREVIEW_CHARS,
    _MAX_ATTEMPTS_KEY,
    _MAX_PER_RUN,
    _NO_FABRICATION_CONTRACT,
    _NUMBER_RE,
    _RECENCY_HOURS,
    _REJECTED,
    # Functions
    _collaborators_enabled,
    _draft_enabled,
    _inbound_text,
    _int_setting,
    _load_attempts,
    _numbers_in,
    _parse_iso,
    _save_attempts,
    _set_setting,
    _setting,
    validate_draft_no_fabrication,
)

from .draft_proposal_jobs import (
    _create_collaborator_proposal,
    _create_proposal,
    _process_candidates,
    _send_proposal_buttons,
    execute_email_reply,
    reject_email_reply,
    run_mailhq_collaborator_drafts,
    run_mailhq_draft_proposals,
)

__all__ = [
    # Constants
    "DRAFT_FLAG_KEY",
    "COLLAB_FLAG_KEY",
    "_ATTACHMENT_RE",
    "_ATTEMPTS_KEY",
    "_COLLAB_ATTEMPTS_KEY",
    "_COLLAB_MAILBOX_TYPE",
    "_COLLAB_MODEL",
    "_COOLDOWN_MIN_KEY",
    "_DEFAULT_COOLDOWN_MIN",
    "_DEFAULT_MAX_ATTEMPTS",
    "_DRAFT_MAILBOX_TYPES",
    "_DRAFT_PREVIEW_CHARS",
    "_MAX_ATTEMPTS_KEY",
    "_MAX_PER_RUN",
    "_NO_FABRICATION_CONTRACT",
    "_NUMBER_RE",
    "_RECENCY_HOURS",
    "_REJECTED",
    # Functions
    "_collaborators_enabled",
    "_draft_enabled",
    "_inbound_text",
    "_int_setting",
    "_load_attempts",
    "_numbers_in",
    "_parse_iso",
    "_save_attempts",
    "_set_setting",
    "_setting",
    "validate_draft_no_fabrication",
    "_create_collaborator_proposal",
    "_create_proposal",
    "_process_candidates",
    "_send_proposal_buttons",
    "execute_email_reply",
    "reject_email_reply",
    "run_mailhq_collaborator_drafts",
    "run_mailhq_draft_proposals",
]
