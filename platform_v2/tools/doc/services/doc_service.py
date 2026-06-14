"""
DOC Service — DB persistence for symptom logs, medications, and health stats.
"""

from __future__ import annotations

from database import get_db_cursor
from datetime import datetime, timedelta
import logging
from typing import Any

logger = logging.getLogger(__name__)


def log_symptoms(
    user_id: int,
    symptoms: str | list[str],
    severity: int | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Insert a DOC symptom log entry for a user.

    Assumes the ``health_symptom_logs`` table has ``user_id``, ``symptoms``
    JSONB, nullable ``severity`` constrained to 1-10, nullable ``notes``, and
    ``logged_at`` with a database default timestamp. String symptoms are stored
    as a one-item JSON array for consistency with route callers.

    Args:
        user_id: Authenticated platform user id that owns the symptom log.
        symptoms: Symptom name or list of symptom names to persist as JSONB.
        severity: Optional 1-10 severity score accepted by the DB constraint.
        notes: Optional free-text note about the symptom event.

    Returns:
        Dictionary with the inserted row ``id`` and ISO-formatted ``logged_at``.

    Raises:
        psycopg2.Error: Propagated from ``get_db_cursor`` or the insert query.
        ValueError: Propagated if the database rejects ``severity``.

    Example:
        >>> log_symptoms(7, "fatigue", severity=4, notes="After lunch")
        {'id': 42, 'logged_at': '2026-06-11T14:30:00'}
    """
    with get_db_cursor(commit=True) as (conn, cur):
        import psycopg2.extras

        # symptoms can be a list or a string; normalise to list
        if isinstance(symptoms, str):
            symptoms = [symptoms]
        cur.execute(
            """
            INSERT INTO health_symptom_logs (user_id, symptoms, severity, notes)
            VALUES (%s, %s, %s, %s)
            RETURNING id, logged_at
            """,
            (user_id, psycopg2.extras.Json(symptoms), severity, notes),
        )
        row = cur.fetchone()
        return {"id": row[0], "logged_at": row[1].isoformat()}


def get_symptom_history(user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent DOC symptom logs for a user.

    Assumes ``health_symptom_logs`` contains ``id``, ``symptoms`` JSONB,
    ``severity``, ``notes``, and ``logged_at`` columns and has an index suitable
    for ``WHERE user_id = ... ORDER BY logged_at DESC``.

    Args:
        user_id: Authenticated platform user id whose logs should be returned.
        limit: Maximum number of rows to return.

    Returns:
        A list of dictionaries ordered newest first, with ``logged_at`` rendered
        as an ISO string.

    Raises:
        psycopg2.Error: Propagated from ``get_db_cursor`` or the select query.

    Example:
        >>> get_symptom_history(7, limit=1)
        [{'id': 42, 'symptoms': ['fatigue'], 'severity': 4,
        'notes': 'After lunch', 'logged_at': '2026-06-11T14:30:00'}]
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, symptoms, severity, notes, logged_at
            FROM health_symptom_logs
            WHERE user_id = %s
            ORDER BY logged_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "symptoms": r[1],
                "severity": r[2],
                "notes": r[3],
                "logged_at": r[4].isoformat(),
            }
            for r in rows
        ]


def add_medication(
    user_id: int,
    name: str,
    dosage: str = "",
    frequency: str = "",
    start_date: str | None = None,
) -> dict[str, Any]:
    """Insert a DOC medication record for a user.

    Assumes the ``health_medications`` table has required ``user_id`` and
    ``name`` columns, nullable ``dosage``, ``frequency``, and ``start_date``
    columns, and ``created_at`` with a database default timestamp. The table
    also provides ``active`` as a default-true boolean for later filtering.

    Args:
        user_id: Authenticated platform user id that owns the medication row.
        name: Medication name. The database requires this value.
        dosage: Optional dosage text, such as ``"10 mg"``.
        frequency: Optional schedule text, such as ``"Daily"``.
        start_date: Optional ISO date string accepted by PostgreSQL DATE.

    Returns:
        Dictionary with the inserted row ``id`` and ISO-formatted ``created_at``.

    Raises:
        TypeError: If required Python arguments such as ``name`` are omitted.
        psycopg2.Error: Propagated from ``get_db_cursor`` or the insert query.

    Example:
        >>> add_medication(
        ...     7, "Loratadine", dosage="10 mg", frequency="Daily",
        ...     start_date="2026-06-11",
        ... )
        {'id': 99, 'created_at': '2026-06-11T15:00:00'}
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO health_medications (user_id, name, dosage, frequency, start_date)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (user_id, name, dosage, frequency, start_date),
        )
        row = cur.fetchone()
        return {"id": row[0], "created_at": row[1].isoformat()}


def get_medications(user_id: int, active_only: bool = True) -> list[dict[str, Any]]:
    """Return DOC medications for a user.

    Assumes ``health_medications`` contains ``id``, ``name``, ``dosage``,
    ``frequency``, ``start_date``, ``end_date``, ``active``, and ``created_at``.
    The active-only path relies on ``active`` being a boolean column with active
    medications marked ``TRUE``.

    Args:
        user_id: Authenticated platform user id whose medications should return.
        active_only: When true, only rows with ``active = TRUE`` are returned.

    Returns:
        A list of medication dictionaries ordered newest first. Date/timestamp
        fields are ISO strings when present.

    Raises:
        psycopg2.Error: Propagated from ``get_db_cursor`` or the select query.

    Example:
        >>> get_medications(7, active_only=True)
        [{'id': 99, 'name': 'Loratadine', 'dosage': '10 mg',
        'frequency': 'Daily', 'start_date': '2026-06-11',
        'end_date': None, 'active': True,
        'created_at': '2026-06-11T15:00:00'}]
    """
    with get_db_cursor() as (conn, cur):
        if active_only:
            cur.execute(
                """
                SELECT id, name, dosage, frequency, start_date, end_date, active, created_at
                FROM health_medications
                WHERE user_id = %s AND active = TRUE
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
        else:
            cur.execute(
                """
                SELECT id, name, dosage, frequency, start_date, end_date, active, created_at
                FROM health_medications
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "dosage": r[2],
                "frequency": r[3],
                "start_date": r[4].isoformat() if r[4] else None,
                "end_date": r[5].isoformat() if r[5] else None,
                "active": r[6],
                "created_at": r[7].isoformat(),
            }
            for r in rows
        ]


def update_medication(
    med_id: int,
    user_id: int,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Update whitelisted DOC medication fields for a user-owned row.

    Assumes ``health_medications`` contains ``dosage``, ``frequency``,
    ``end_date``, and ``active`` columns. The update is scoped by both ``id`` and
    ``user_id`` so one user cannot update another user's medication row. Unknown
    keys are ignored rather than written.

    Args:
        med_id: Medication row id to update.
        user_id: Authenticated platform user id that must own the row.
        updates: Candidate field/value mapping. Only ``dosage``, ``frequency``,
            ``end_date``, and ``active`` are persisted.

    Returns:
        ``{"updated": True}`` when a row was changed, ``{"updated": False}``
        when no row matched, or an error dictionary when no valid fields were
        provided.

    Raises:
        psycopg2.Error: Propagated from ``get_db_cursor`` or the update query.

    Example:
        >>> update_medication(99, 7, {"dosage": "20 mg", "active": False})
        {'updated': True}
    """
    allowed = {"dosage", "frequency", "end_date", "active"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return {"updated": False, "error": "No valid fields to update"}
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [med_id, user_id]
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE health_medications SET {set_clause} WHERE id = %s AND user_id = %s",
            values,
        )
        return {"updated": cur.rowcount > 0}


def get_health_stats(user_id: int) -> dict[str, int | None]:
    """Return aggregate DOC health stats for a user.

    Assumes ``health_medications`` has ``user_id`` and boolean ``active`` columns
    and ``health_symptom_logs`` has ``user_id`` plus ``logged_at`` timestamps.
    The 30-day symptom window is computed in application time and compared
    against stored timestamps.

    Args:
        user_id: Authenticated platform user id whose health stats should return.

    Returns:
        Dictionary containing ``active_medications``, ``symptom_logs_30d``, and
        nullable ``days_since_last_log``.

    Raises:
        psycopg2.Error: Propagated from ``get_db_cursor`` or aggregate queries.

    Example:
        >>> get_health_stats(7)
        {'active_medications': 2, 'symptom_logs_30d': 4, 'days_since_last_log': 5}
    """
    with get_db_cursor() as (conn, cur):
        # Active med count
        cur.execute(
            "SELECT COUNT(*) FROM health_medications WHERE user_id = %s AND active = TRUE",
            (user_id,),
        )
        active_meds = cur.fetchone()[0]

        # Total symptom logs last 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)
        cur.execute(
            "SELECT COUNT(*) FROM health_symptom_logs WHERE user_id = %s AND logged_at >= %s",
            (user_id, thirty_days_ago),
        )
        symptom_count_30d = cur.fetchone()[0]

        # Days since last symptom log
        cur.execute(
            "SELECT MAX(logged_at) FROM health_symptom_logs WHERE user_id = %s",
            (user_id,),
        )
        last_log = cur.fetchone()[0]
        days_since_last = None
        if last_log:
            days_since_last = (datetime.now() - last_log).days

        return {
            "active_medications": active_meds,
            "symptom_logs_30d": symptom_count_30d,
            "days_since_last_log": days_since_last,
        }


def schedule_appointment(
    user_id: int,
    title: str,
    datetime_str: str,
    duration: int = 30,
) -> dict[str, Any]:
    """Schedule a DOC appointment through Google Calendar when available.

    This helper does not currently write a DOC-local appointment table. It
    assumes Google Work Suite account records can be resolved by
    ``owner_type='user'`` and ``owner_id=user_id``; when no account exists or the
    optional Google services fail, the function returns a local-success fallback
    used by the DOC routes.

    Args:
        user_id: Authenticated platform user id requesting the appointment.
        title: Calendar event title.
        datetime_str: ISO 8601 appointment start datetime accepted by
            ``datetime.fromisoformat``.
        duration: Appointment duration in minutes.

    Returns:
        The Google Calendar ``create_event`` result when an account is
        connected, otherwise ``{"success": True, "note": ...}``.

    Raises:
        This function intentionally swallows Google import/API/date parsing
        exceptions and returns the fallback dictionary.

    Example:
        >>> schedule_appointment(7, "Checkup", "2026-06-13T12:00:00-04:00")
        {'success': True, 'note': 'Saved locally (no Google Calendar connected)'}
    """
    try:
        from tools.google_work_suite.services.google_api_service import list_accounts
        from tools.google_work_suite.services.calendar_service import create_event

        accounts = list_accounts(owner_type="user", owner_id=user_id)
        if accounts:
            start = datetime.fromisoformat(datetime_str)
            end = start + timedelta(minutes=duration)
            return create_event(
                accounts[0]["id"],
                title,
                start.isoformat(),
                end.isoformat(),
                description="Scheduled via DOC module",
            )
    except Exception:
        pass
    return {"success": True, "note": "Saved locally (no Google Calendar connected)"}


def get_ai_context(user_id: int) -> str:
    """Return recent DOC context text for Dr. Amara prompt injection.

    Assumes ``get_symptom_history`` and ``get_medications`` can read the
    ``health_symptom_logs`` and ``health_medications`` schemas documented above.
    The returned text is a lightweight context summary only; DOC routes still
    own medical disclaimers and safety wording for user-facing responses.

    Args:
        user_id: Authenticated platform user id whose recent health context
            should be summarized.

    Returns:
        Prompt-context text containing recent symptoms and active medications, or
        an empty string if DB/service lookup fails.

    Raises:
        This function catches lookup/formatting exceptions, logs a warning, and
        returns an empty string so chat routes can continue safely.

    Example:
        >>> get_ai_context(7)
        '[User Health Context]\\nRecent symptoms:\\n  - fatigue ...'
    """
    try:
        symptoms = get_symptom_history(user_id, limit=5)
        meds = get_medications(user_id, active_only=True)
        lines = ["[User Health Context]"]
        if symptoms:
            lines.append("Recent symptoms:")
            for s in symptoms:
                sym_list = ", ".join(s["symptoms"]) if isinstance(s["symptoms"], list) else str(s["symptoms"])
                severity = f" (severity {s['severity']}/10)" if s["severity"] else ""
                lines.append(f"  - {sym_list}{severity} ({s['logged_at'][:10]})")
        if meds:
            lines.append("Active medications:")
            for m in meds:
                lines.append(f"  - {m['name']} {m['dosage']} {m['frequency']}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"get_ai_context failed: {e}")
        return ""
