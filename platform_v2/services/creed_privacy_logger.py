"""C.R.E.E.D. Privacy Event Logger

Writes to governance_audit_log with event_category='data_management'.
The creed_reporter job (agent_loop.py) picks these up every 5 min and
maps 'data_management' → 'privacy' pillar in the creed standalone.

Severity → creed score impact (via SEVERITY_MAP in creed_reporter):
  outcome='success'  → severity='info'      (routine, no score impact)
  outcome='failed'   → severity='warning'   (minor score impact)
  outcome='denied'   → severity='violation' (moderate score impact)
  outcome='error'    → severity='critical'  (high score impact)

PIPEDA alignment:
  - Accountability       : log_privacy_event('policy_check', ...)
  - Limiting Collection  : log_privacy_event('data_minimization', ...)
  - Limiting Use         : log_privacy_event('data_retention_check', ...)
  - Safeguards           : log_privacy_event('access_control', ...)
  - Individual Access    : log_privacy_event('user_data_access', ...)
"""

import json
import logging

logger = logging.getLogger(__name__)

# Valid data categories (PIPEDA-informed)
DATA_CATEGORIES = frozenset({"personal", "sensitive", "anonymized", "aggregate", "system"})


def log_privacy_event(
    event_type: str,
    action: str,
    outcome: str = "success",
    agent_id: int | None = None,
    data_category: str = "personal",
    description: str | None = None,
    details: dict | None = None,
) -> int | None:
    """Log a privacy-relevant event to governance_audit_log.

    Args:
        event_type: What happened, e.g.:
            'email_data_processed'    — email content accessed for triage/sync
            'knowledge_base_write'    — user-related data stored in KB
            'api_external_access'     — API key used for external platform request
            'user_data_read'          — user profile / account record accessed
            'data_retention_check'    — scheduled retention policy verification
            'third_party_data_share'  — data sent to an external service (TMDB, Google, etc.)
            'pii_detected'            — PII found in an unexpected context
            'access_control_check'    — permission/auth gate evaluated on personal data
            'consent_verification'    — consent status checked before data use
        action: Short verb describing the operation (e.g. 'read', 'write', 'sync', 'export')
        outcome: 'success' | 'failed' | 'denied' | 'error'
        agent_id: Platform agent that performed the action (None = system/job)
        data_category: 'personal' | 'sensitive' | 'anonymized' | 'aggregate' | 'system'
        description: Human-readable description (defaults to event_type)
        details: Extra context dict (counts, service names, etc.)

    Returns:
        New governance_audit_log row id, or None on failure.
    """
    if data_category not in DATA_CATEGORIES:
        data_category = "personal"

    payload = {"data_category": data_category, **(details or {})}

    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO governance_audit_log
                    (event_type, event_category, action, outcome, agent_id, reason, details, timestamp)
                VALUES (%s, 'data_management', %s, %s, %s, %s, %s::jsonb, NOW())
                RETURNING id
                """,
                (
                    event_type,
                    action,
                    outcome,
                    agent_id,
                    (description or event_type)[:500],
                    json.dumps(payload),
                ),
            )
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as e:
        logger.warning("[PrivacyLogger] Failed to log %s: %s", event_type, e)
        return None


def log_email_sync(
    mailboxes_synced: int,
    new_messages: int,
    errors: int,
) -> None:
    """Log an email IMAP sync cycle — data processing event under PIPEDA."""
    outcome = "failed" if errors > mailboxes_synced / 2 else "success"
    log_privacy_event(
        event_type="email_data_processed",
        action="sync",
        outcome=outcome,
        data_category="personal",
        description=(f"IMAP sync: {mailboxes_synced} mailboxes, " f"{new_messages} new messages, {errors} errors"),
        details={
            "mailboxes": mailboxes_synced,
            "new_messages": new_messages,
            "errors": errors,
            "pipeda_principle": "safeguards",
        },
    )


def log_api_key_access(
    scope: str,
    endpoint: str,
    granted: bool,
    key_id: int | None = None,
) -> None:
    """Log an API key–authenticated external request (PIPEDA: safeguards + accountability)."""
    log_privacy_event(
        event_type="api_external_access",
        action="authenticate",
        outcome="success" if granted else "denied",
        data_category="aggregate",
        description=f"API key access ({scope}) → {endpoint}",
        details={
            "scope": scope,
            "endpoint": endpoint,
            "key_id": key_id,
            "pipeda_principle": "accountability",
        },
    )
