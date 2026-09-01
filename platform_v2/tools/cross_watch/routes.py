"""Cross-Watch Alert System — API routes.

Blueprint prefix: none (all routes served at /api/cross-watch/*).
Auth: Bearer CROSS_WATCH_SERVICE_TOKEN + X-User-Email header.

Routes
------
POST   /api/cross-watch/signal                — ingest a signal from a Watch product
GET    /api/cross-watch/alerts                — unread alerts for the calling user
POST   /api/cross-watch/alerts/<id>/read      — mark one alert read
GET    /api/cross-watch/entities              — full entity list (follow UI)
POST   /api/cross-watch/follow                — follow an entity
DELETE /api/cross-watch/follow/<entity_id>   — unfollow an entity
GET    /api/cross-watch/following             — list user's followed entities
GET    /api/cross-watch/procurement           — gov_watch tenders matching article title (#3019)
GET    /api/cross-watch/legal-rulings        — legal_watch SCC/regulation/ethics signals (#3020)
GET    /api/cross-watch/search               — unified free-text search across all signal types (#3128)
"""

import logging
import os
import re
import time
from threading import Lock

from flask import jsonify, request

from database import get_db_cursor

from . import cross_watch_bp

logger = logging.getLogger(__name__)

# ── In-process entity cache (refreshed every 60s) ─────────────────────────────
_entity_cache: list = []
_entity_cache_at: float = 0.0
_entity_cache_lock = Lock()
_ENTITY_CACHE_TTL = 60  # seconds


def _entity_ids_matching_title(title: str) -> list:
    """Entity ids whose name or alias appears in `title` as a WHOLE WORD.

    ⚠️ WORD BOUNDARIES ARE THE WHOLE POINT. This was four copies of a naive
    `alias.lower() in title_lower` substring test, which fires on ordinary
    English because several aliases are two letters:

        "Cape Breton hockey player…"      -> bre(TO)n        -> Toronto
        "Storm watch … Dartmouth"         -> wa(TC)h         -> Transport Canada
        "Saskatchewan teacher strike"     -> saska(TC)hewan  -> Transport Canada
        "Doctors warn about flu season"   -> doc(TO)rs       -> Toronto

    Measured live: a hockey story about a moose returned 5 "Related Parliament
    Votes", every one attached to Toronto, purely because "Breton" contains
    "to". Meanwhile "Carney government tables budget bill on carbon pricing in
    Parliament" returned ZERO — so the matcher false-positived on irrelevant
    stories while missing the obviously relevant one.

    The two-letter aliases (TO, HC, TC) are the dangerous ones; CRA/DND/MTL are
    long enough to be safe by luck, not by design. Boundaries fix the class,
    not just the instances.

    ONE definition, called by all four endpoints. Four copies is how three of
    them stay broken after someone fixes the fourth.
    """
    return [e["id"] for e in _entities_matching_title(title)]


def _entities_matching_title(title: str) -> list:
    """Full entity dicts whose name/alias appears in `title` as a whole word.

    The WRITE path (ingest_signal) needs the objects; the four READ endpoints
    need only ids. Both go through here so the boundary rule cannot be fixed in
    one and left broken in the other — which is exactly the state this file was
    in: five copies of the same substring test, one of them spelled
    `headline_lower` instead of `title_lower` and therefore invisible to a grep
    for the other four.
    """
    if not title:
        return []
    title_lower = title.lower()
    matched = []
    for ent in _get_entities():
        needles = [ent["name"]] + list(ent.get("aliases") or [])
        for needle in needles:
            if not needle:
                continue
            # \b on both sides: "TO" matches "TO" and "to," but never "Breton".
            if re.search(r"\b" + re.escape(needle.lower()) + r"\b", title_lower):
                matched.append(ent)
                break
    return matched


def _get_entities() -> list:
    """Return entity list from cache, refreshing if stale."""
    global _entity_cache, _entity_cache_at
    now = time.monotonic()
    if now - _entity_cache_at < _ENTITY_CACHE_TTL and _entity_cache:
        return _entity_cache

    with _entity_cache_lock:
        # Double-checked locking
        if now - _entity_cache_at < _ENTITY_CACHE_TTL and _entity_cache:
            return _entity_cache

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, entity_type, name, slug, aliases
                    FROM shared.entities
                    ORDER BY name
                    """
                )
                rows = cur.fetchall()
                _entity_cache = [dict(r) for r in rows]
                _entity_cache_at = time.monotonic()
                logger.debug("[cross_watch] entity cache refreshed — %d entities", len(_entity_cache))
        except Exception as exc:
            logger.error("[cross_watch] entity cache refresh failed: %s", exc)
            # Return stale cache rather than crashing callers
        return _entity_cache


def _invalidate_entity_cache():
    """Force next call to _get_entities() to re-query the DB."""
    global _entity_cache_at
    _entity_cache_at = 0.0


# ── Auth helpers ──────────────────────────────────────────────────────────────


def _verify_token() -> bool:
    """Return True if the request carries a valid service token."""
    expected = os.getenv("CROSS_WATCH_SERVICE_TOKEN", "")
    if not expected:
        return False
    bearer = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return bearer == expected


def _resolve_user(email: str):
    """Resolve email → users.id; returns int or None."""
    if not email:
        return None
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id FROM users WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                (email,),
            )
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as exc:
        logger.error("[cross_watch] _resolve_user failed: %s", exc)
        return None


def _auth_gate():
    """
    Verify token + resolve user.  Returns (user_id, error_response).
    Callers that need user_id must check for error_response first.
    """
    if not _verify_token():
        return None, (jsonify({"error": "unauthorized"}), 401)

    email = request.headers.get("X-User-Email", "").strip()
    user_id = _resolve_user(email)
    if not user_id:
        return None, (jsonify({"error": "user not found", "email": email}), 404)

    return user_id, None


# ── Signal endpoint ───────────────────────────────────────────────────────────


@cross_watch_bp.route("/api/cross-watch/signal", methods=["POST"])
def ingest_signal():
    """
    Ingest a cross-product signal from any Watch product.

    Body (JSON):
      signal_type    — one of the CHECK constraint values
      source_product — e.g. 'gov_watch', 'wtf'
      source_item_id — PK of the triggering item in the source product
      headline       — human-readable title / description
      url            — optional deep-link back to the source item
      metadata       — optional JSONB blob
    """
    if not _verify_token():
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    signal_type = body.get("signal_type", "")
    source_product = body.get("source_product", "")
    source_item_id = str(body.get("source_item_id", ""))
    headline = body.get("headline", "")
    url = body.get("url")
    metadata = body.get("metadata", {})

    if not all([signal_type, source_product, source_item_id, headline]):
        return jsonify({"error": "missing required fields: signal_type, source_product, source_item_id, headline"}), 400

    # Match entities by name/alias as a WHOLE WORD in the headline.
    #
    # ⚠️ This is the WRITE path — it creates the entity->signal links the four
    # read endpoints later surface, so a false match here persists as bad data
    # rather than just a bad render. It was a fifth copy of the same substring
    # bug, spelled `headline_lower` instead of `title_lower`, which is why it
    # survived a grep that found the other four.
    matched = _entities_matching_title(headline)

    if not matched:
        return jsonify({"signals_created": 0, "entities_matched": []}), 200

    signals_created = 0
    matched_names = []
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            for ent in matched:
                cur.execute(
                    """
                    INSERT INTO shared.cross_watch_signals
                        (entity_id, signal_type, source_product, source_item_id,
                         headline, url, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (entity_id, source_product, source_item_id) DO NOTHING
                    """,
                    (
                        ent["id"],
                        signal_type,
                        source_product,
                        source_item_id,
                        headline,
                        url,
                        (
                            __import__("psycopg2").extras.Json(metadata)
                            if metadata
                            else __import__("psycopg2").extras.Json({})
                        ),
                    ),
                )
                if cur.rowcount:
                    signals_created += 1
                    matched_names.append(ent["name"])
    except Exception as exc:
        logger.error("[cross_watch] ingest_signal failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    if signals_created:
        logger.info(
            "[cross_watch] signal ingested — source=%s type=%s entities=%s",
            source_product,
            signal_type,
            matched_names,
        )

    return jsonify({"signals_created": signals_created, "entities_matched": matched_names}), 200


# ── Alerts ────────────────────────────────────────────────────────────────────


@cross_watch_bp.route("/api/cross-watch/alerts", methods=["GET"])
def get_alerts():
    """Return all alerts for the calling user (newest first)."""
    user_id, err = _auth_gate()
    if err:
        return err

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT a.id, a.entity_id, a.signal_id, a.message, a.url,
                       a.is_read, a.created_at,
                       e.name AS entity_name, e.entity_type,
                       s.signal_type, s.source_product
                FROM shared.cross_watch_alerts a
                JOIN shared.entities e ON e.id = a.entity_id
                JOIN shared.cross_watch_signals s ON s.id = a.signal_id
                WHERE a.user_id = %s
                ORDER BY a.created_at DESC
                LIMIT 100
                """,
                (user_id,),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("[cross_watch] get_alerts failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    alerts = [
        {
            "id": r["id"],
            "entity_id": r["entity_id"],
            "entity_name": r["entity_name"],
            "entity_type": r["entity_type"],
            "signal_id": r["signal_id"],
            "signal_type": r["signal_type"],
            "source_product": r["source_product"],
            "message": r["message"],
            "url": r["url"],
            "is_read": r["is_read"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    return jsonify({"alerts": alerts, "unread": sum(1 for a in alerts if not a["is_read"])}), 200


@cross_watch_bp.route("/api/cross-watch/alerts/<int:alert_id>/read", methods=["POST"])
def mark_alert_read(alert_id: int):
    """Mark one alert as read (user-scoped — cannot touch another user's alerts)."""
    user_id, err = _auth_gate()
    if err:
        return err

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE shared.cross_watch_alerts SET is_read = TRUE WHERE id = %s AND user_id = %s",
                (alert_id, user_id),
            )
            updated = cur.rowcount
    except Exception as exc:
        logger.error("[cross_watch] mark_alert_read failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    if not updated:
        return jsonify({"error": "alert not found"}), 404
    return jsonify({"ok": True}), 200


# ── Entity list ───────────────────────────────────────────────────────────────


@cross_watch_bp.route("/api/cross-watch/entities", methods=["GET"])
def list_entities():
    """Return all followable entities (for follow UI autocomplete / browse)."""
    if not _verify_token():
        return jsonify({"error": "unauthorized"}), 401

    entities = _get_entities()
    return (
        jsonify(
            {
                "entities": [
                    {
                        "id": e["id"],
                        "name": e["name"],
                        "entity_type": e["entity_type"],
                        "slug": e["slug"],
                    }
                    for e in entities
                ]
            }
        ),
        200,
    )


# ── Follow / unfollow ─────────────────────────────────────────────────────────


@cross_watch_bp.route("/api/cross-watch/follow", methods=["POST"])
def follow_entity():
    """Create a user→entity follow. Body: {entity_id: int}."""
    user_id, err = _auth_gate()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    entity_id = body.get("entity_id")
    if not entity_id:
        return jsonify({"error": "entity_id required"}), 400

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO shared.user_follows (user_id, entity_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, entity_id) DO NOTHING
                """,
                (user_id, entity_id),
            )
            created = bool(cur.rowcount)
    except Exception as exc:
        logger.error("[cross_watch] follow_entity failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    return jsonify({"ok": True, "created": created}), 200


@cross_watch_bp.route("/api/cross-watch/follow/<int:entity_id>", methods=["DELETE"])
def unfollow_entity(entity_id: int):
    """Remove a user→entity follow."""
    user_id, err = _auth_gate()
    if err:
        return err

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "DELETE FROM shared.user_follows WHERE user_id = %s AND entity_id = %s",
                (user_id, entity_id),
            )
            deleted = bool(cur.rowcount)
    except Exception as exc:
        logger.error("[cross_watch] unfollow_entity failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    return jsonify({"ok": True, "deleted": deleted}), 200


@cross_watch_bp.route("/api/cross-watch/procurement", methods=["GET"])
def get_procurement_signals():
    """
    Return recent gov_watch tender signals whose entities match keywords in
    the given article title. Used by WTF article pages to surface related tenders.

    Query params:
      title — article headline to match against entity names (substring, same
              logic as ingest_signal)
      limit — max results, default 5, capped at 10

    Auth: Bearer token only — no user session required (page-level lookup).
    """
    if not _verify_token():
        return jsonify({"error": "unauthorized"}), 401

    title = request.args.get("title", "").strip()
    if not title:
        return jsonify({"tenders": [], "count": 0}), 200

    try:
        limit = min(int(request.args.get("limit", 5)), 10)
    except (ValueError, TypeError):
        limit = 5

    # Reuse cached entity list + same substring matching as ingest_signal
    # Word-boundary matching — see _entity_ids_matching_title. A substring test
    # here matched "Toronto" inside "Breton" and put Parliament votes on a
    # hockey story.
    matched_ids = _entity_ids_matching_title(title)

    if not matched_ids:
        return jsonify({"tenders": [], "count": 0}), 200

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT s.id, s.headline, s.url, s.created_at,
                       e.name AS entity_name, e.entity_type
                FROM shared.cross_watch_signals s
                JOIN shared.entities e ON e.id = s.entity_id
                WHERE s.entity_id = ANY(%s)
                  AND s.source_product = 'gov_watch'
                  AND s.signal_type = 'new_tender'
                  AND s.created_at > NOW() - INTERVAL '30 days'
                ORDER BY s.created_at DESC
                LIMIT %s
                """,
                (matched_ids, limit),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("[cross_watch] get_procurement_signals failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    tenders = [
        {
            "id": r["id"],
            "entity_name": r["entity_name"],
            "entity_type": r["entity_type"],
            "headline": r["headline"],
            "url": r["url"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    return jsonify({"tenders": tenders, "count": len(tenders)}), 200


@cross_watch_bp.route("/api/cross-watch/parliament-votes", methods=["GET"])
def get_parliament_votes():
    """
    Return recent parliament_vote signals whose entities match keywords in
    the given article title. Used by WTF article pages to surface related votes.

    Query params:
      title — article headline to match against entity names (same substring logic
              as procurement / ingest_signal)
      limit — max results, default 5, capped at 10

    Auth: Bearer token only — no user session required (page-level lookup).
    """
    if not _verify_token():
        return jsonify({"error": "unauthorized"}), 401

    title = request.args.get("title", "").strip()
    if not title:
        return jsonify({"votes": [], "count": 0}), 200

    try:
        limit = min(int(request.args.get("limit", 5)), 10)
    except (ValueError, TypeError):
        limit = 5

    # Word-boundary matching — see _entity_ids_matching_title. A substring test
    # here matched "Toronto" inside "Breton" and put Parliament votes on a
    # hockey story.
    matched_ids = _entity_ids_matching_title(title)

    if not matched_ids:
        return jsonify({"votes": [], "count": 0}), 200

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT s.id, s.headline, s.url, s.created_at,
                       e.name AS entity_name, e.entity_type,
                       s.metadata
                FROM shared.cross_watch_signals s
                JOIN shared.entities e ON e.id = s.entity_id
                WHERE s.entity_id = ANY(%s)
                  AND s.source_product = 'civic_watch'
                  AND s.signal_type = 'parliament_vote'
                  AND s.created_at > NOW() - INTERVAL '90 days'
                ORDER BY s.created_at DESC
                LIMIT %s
                """,
                (matched_ids, limit),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("[cross_watch] get_parliament_votes failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    votes = [
        {
            "id": r["id"],
            "entity_name": r["entity_name"],
            "entity_type": r["entity_type"],
            "headline": r["headline"],
            "url": r["url"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "result": (r["metadata"] or {}).get("result"),
            "yeas": (r["metadata"] or {}).get("yeas"),
            "nays": (r["metadata"] or {}).get("nays"),
            "bill_number": (r["metadata"] or {}).get("bill_number"),
        }
        for r in rows
    ]
    return jsonify({"votes": votes, "count": len(votes)}), 200


@cross_watch_bp.route("/api/cross-watch/legal-rulings", methods=["GET"])
def get_legal_rulings():
    """
    Return recent legal_watch signals whose entities match keywords in
    the given article title. Covers SCC decisions, regulations, and ethics rulings.

    Query params:
      title — article headline to match against entity names (same substring logic)
      limit — max results, default 5, capped at 10

    Auth: Bearer token only — no user session required (page-level lookup).
    """
    if not _verify_token():
        return jsonify({"error": "unauthorized"}), 401

    title = request.args.get("title", "").strip()
    if not title:
        return jsonify({"rulings": [], "count": 0}), 200

    try:
        limit = min(int(request.args.get("limit", 5)), 10)
    except (ValueError, TypeError):
        limit = 5

    # Word-boundary matching — see _entity_ids_matching_title. A substring test
    # here matched "Toronto" inside "Breton" and put Parliament votes on a
    # hockey story.
    matched_ids = _entity_ids_matching_title(title)

    if not matched_ids:
        return jsonify({"rulings": [], "count": 0}), 200

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT s.id, s.headline, s.url, s.created_at,
                       e.name AS entity_name, e.entity_type,
                       s.metadata
                FROM shared.cross_watch_signals s
                JOIN shared.entities e ON e.id = s.entity_id
                WHERE s.entity_id = ANY(%s)
                  AND s.source_product = 'legal_watch'
                  AND s.signal_type = 'legal_ruling'
                  AND s.created_at > NOW() - INTERVAL '365 days'
                ORDER BY s.created_at DESC
                LIMIT %s
                """,
                (matched_ids, limit),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("[cross_watch] get_legal_rulings failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    rulings = [
        {
            "id": r["id"],
            "entity_name": r["entity_name"],
            "entity_type": r["entity_type"],
            "headline": r["headline"],
            "url": r["url"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "ruling_type": (r["metadata"] or {}).get("ruling_type"),
            "outcome": (r["metadata"] or {}).get("outcome"),
            "citation": (r["metadata"] or {}).get("citation"),
        }
        for r in rows
    ]
    return jsonify({"rulings": rulings, "count": len(rulings)}), 200


@cross_watch_bp.route("/api/cross-watch/civic-events", methods=["GET"])
def get_civic_events():
    """
    Return recent civic_event signals whose city entity matches keywords in
    the given article title. Covers municipal council decisions, bylaws,
    spending, and development permits from Civic Watch.

    Query params:
      title — article headline to match against entity names / city aliases
      limit — max results, default 5, capped at 10

    Auth: Bearer token only — no user session required (page-level lookup).
    """
    if not _verify_token():
        return jsonify({"error": "unauthorized"}), 401

    title = request.args.get("title", "").strip()
    if not title:
        return jsonify({"events": [], "count": 0}), 200

    try:
        limit = min(int(request.args.get("limit", 5)), 10)
    except (ValueError, TypeError):
        limit = 5

    # Word-boundary matching — see _entity_ids_matching_title. A substring test
    # here matched "Toronto" inside "Breton" and put Parliament votes on a
    # hockey story.
    matched_ids = _entity_ids_matching_title(title)

    if not matched_ids:
        return jsonify({"events": [], "count": 0}), 200

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT s.id, s.headline, s.url, s.created_at,
                       e.name AS entity_name, e.entity_type,
                       s.metadata
                FROM shared.cross_watch_signals s
                JOIN shared.entities e ON e.id = s.entity_id
                WHERE s.entity_id = ANY(%s)
                  AND s.source_product = 'civic_watch'
                  AND s.signal_type = 'civic_event'
                  AND s.created_at > NOW() - INTERVAL '180 days'
                ORDER BY s.created_at DESC
                LIMIT %s
                """,
                (matched_ids, limit),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("[cross_watch] get_civic_events failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    events = [
        {
            "id": r["id"],
            "city": r["entity_name"],
            "headline": r["headline"],
            "url": r["url"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "event_type": (r["metadata"] or {}).get("event_type"),
            "level": (r["metadata"] or {}).get("level"),
            "jurisdiction": (r["metadata"] or {}).get("jurisdiction"),
            "amount": (r["metadata"] or {}).get("amount"),
            "event_date": (r["metadata"] or {}).get("event_date"),
        }
        for r in rows
    ]
    return jsonify({"events": events, "count": len(events)}), 200


# ── Unified search ────────────────────────────────────────────────────────────

_VALID_TYPES = {"procurement", "parliament_vote", "legal_ruling", "civic_event"}
_TYPE_TO_SIGNAL = {
    "procurement": "new_tender",
    "parliament_vote": "parliament_vote",
    "legal_ruling": "legal_ruling",
    "civic_event": "civic_event",
}
_SIGNAL_TO_TYPE = {v: k for k, v in _TYPE_TO_SIGNAL.items()}


@cross_watch_bp.route("/api/cross-watch/search", methods=["GET"])
def get_unified_search():
    """
    Unified free-text search across all cross-watch signal types.

    Query params:
      q      — free-text matched against s.headline (ILIKE, required)
      types  — optional comma-separated filter from:
                 procurement, parliament_vote, legal_ruling, civic_event
               Defaults to all four types.
      limit  — max results per type, default 3, capped at 5

    Returns:
      {query, results: {procurement:[...], parliament_vote:[...],
                        legal_ruling:[...], civic_event:[...]}, total}

    Each result: {id, signal_type, headline, url, created_at,
                  source_product, entity_name, metadata}

    Auth: Bearer token only — no user session required (#3128).
    """
    if not _verify_token():
        return jsonify({"error": "unauthorized"}), 401

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q parameter required"}), 400

    try:
        limit = min(int(request.args.get("limit", 3)), 5)
    except (ValueError, TypeError):
        limit = 3

    raw_types = request.args.get("types", "").strip()
    if raw_types:
        requested = {t.strip() for t in raw_types.split(",") if t.strip()}
        active_types = requested & _VALID_TYPES
        if not active_types:
            return jsonify({"error": f"invalid types — valid values: {sorted(_VALID_TYPES)}"}), 400
    else:
        active_types = set(_VALID_TYPES)

    signal_types = [_TYPE_TO_SIGNAL[t] for t in active_types]

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT s.id, s.signal_type, s.source_product,
                       s.headline, s.url, s.created_at, s.metadata,
                       e.name AS entity_name
                FROM shared.cross_watch_signals s
                JOIN shared.entities e ON e.id = s.entity_id
                WHERE s.headline ILIKE %s
                  AND s.signal_type = ANY(%s)
                  AND s.created_at > NOW() - INTERVAL '180 days'
                ORDER BY s.created_at DESC
                """,
                (f"%{q}%", signal_types),
            )
            all_rows = cur.fetchall()
    except Exception as exc:
        logger.error("[cross_watch] get_unified_search failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    # Group by logical type, cap at limit per type
    buckets: dict = {t: [] for t in active_types}
    for r in all_rows:
        logical = _SIGNAL_TO_TYPE.get(r["signal_type"])
        if logical and logical in buckets and len(buckets[logical]) < limit:
            buckets[logical].append(
                {
                    "id": r["id"],
                    "signal_type": logical,
                    "headline": r["headline"],
                    "url": r["url"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "source_product": r["source_product"],
                    "entity_name": r["entity_name"],
                    "metadata": r["metadata"] or {},
                }
            )

    total = sum(len(v) for v in buckets.values())
    return jsonify({"query": q, "results": buckets, "total": total}), 200


@cross_watch_bp.route("/api/cross-watch/following", methods=["GET"])
def list_following():
    """Return the list of entities the calling user follows."""
    user_id, err = _auth_gate()
    if err:
        return err

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT e.id, e.name, e.entity_type, e.slug, f.created_at
                FROM shared.user_follows f
                JOIN shared.entities e ON e.id = f.entity_id
                WHERE f.user_id = %s
                ORDER BY e.name
                """,
                (user_id,),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("[cross_watch] list_following failed: %s", exc)
        return jsonify({"error": "internal error"}), 500

    following = [
        {
            "id": r["id"],
            "name": r["name"],
            "entity_type": r["entity_type"],
            "slug": r["slug"],
            "followed_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    return jsonify({"following": following}), 200
