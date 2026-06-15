"""entity_graph_routes.py — Shared Entity Graph INGEST endpoint (T-ING-1).

THE SINGLE WRITER for the canonical accountability graph.

  POST /api/internal/entity-graph/ingest   (auth: X-Internal-Key == INTERNAL_API_KEY)

Architecture (ADR-EG-001 §5 + must-fix I1):
  - This endpoint lives INSIDE the WTF consumer app because the consumer already
    holds WTF_DATABASE_URL and the resolver lives in this repo (ingest.shared.entity_graph).
  - gov-watch / civic-watch / legal-watch / market-watch adapters POST their
    entities/mentions/relationships HERE over the mesh. They do NOT open a
    cross-host DB connection. Only WTF's own hub-resident adapters write the DB
    directly. => single-writer; ONE resolver (_upsert_entity); NO third resolver.

DUAL-SCHEMA BOUNDARY (ADR-EG-001 §3 — must-fix S6):
  The CANONICAL graph is the hub `wtf` DB `shared` schema (entity_type
  person|organization|journalist). The hub `archie` DB ALSO has a
  shared.entities table (migration 393) but that is a SEPARATE follow/alert
  SIGNAL BUS (entity_type department|topic|keyword) and is NEVER written or
  read here. This endpoint connects ONLY to WTF_DATABASE_URL (the `wtf` DB).

Body (JSON):
  {
    "product": "gov-watch" | "civic-watch" | "legal-watch" | "market-watch" | "wtf",
    "entities": [
      {"canonical_name": "...", "slug": "...", "entity_type": "person|organization|journalist",
       "role": {"type": "...", ...}, "raw_name": "..."(optional, defaults canonical_name)}
    ],
    "mentions": [
      {"entity": <entity ref>, "content_type": "...", "content_id": "...",
       "mention_context": "..."(optional), "confidence": 0.0-1.0 (optional)}
    ],
    "relationships": [
      {"from": <entity ref>, "to": <entity ref>, "relationship_type": "donated_to|...",
       "source_id": "..."(optional), "valid_from": "YYYY-MM-DD"(optional),
       "valid_to": "YYYY-MM-DD"(optional), "metadata": {...}(optional)}
    ]
  }

  An <entity ref> is EITHER an inline entity object (resolved + upserted, same shape
  as an `entities[]` element) OR {"slug": "..."} to point at an already-known node.

Idempotent: entity upsert keys on slug (via _upsert_entity); mentions UPSERT on
  the migration-030 UNIQUE (entity_id, product, content_type, content_id);
  relationships UPSERT on UNIQUE (from_entity_id, to_entity_id, relationship_type,
  source_product, source_id).
"""
import json
import logging
import os

from flask import Blueprint, jsonify, request
from sqlalchemy import create_engine, text

# Reuse the ONE resolver (ADR-EG-001 §5 / must-fix I1 — never write a third).
from ingest.shared.entity_graph import _upsert_entity

logger = logging.getLogger("wtf-consumer.entity_graph_ingest")

entity_graph_bp = Blueprint("entity_graph", __name__)

# ── Frozen vocabulary (ADR-EG-001 §1 + §2.4). Import-verbatim; never hand-type. ──

VALID_NODE_TYPES = frozenset({"person", "organization", "journalist"})

# Spine edges (walk the chain) + enrichment edges (attach to nodes).
VALID_EDGE_TYPES = frozenset({
    # SPINE
    "donated_to",          # Link 1  has_data=TRUE
    "cast_vote",           # Link 3  has_data=TRUE
    "enacted_as",          # Link 4  has_data=FALSE (placeholder, no writer)
    "awarded_to",          # Link 5  has_data=TRUE
    "contracts_with",      # Link 5  has_data=TRUE
    "market_reaction_to",  # Link 6  has_data=FALSE (placeholder, no writer)
    "covered_by",          # Link 7  has_data=TRUE (normally derived at query time)
    # ENRICHMENT
    "lobbied_by",          # attach@2  has_data=TRUE
    "appointed_to",        # attach@5  has_data=TRUE
    "employs",             # attach@2  has_data=TRUE
})

VALID_PRODUCTS = frozenset({
    "wtf", "gov-watch", "civic-watch", "legal-watch", "market-watch",
})

_MAX_ENTITIES = 5000
_MAX_MENTIONS = 5000
_MAX_RELATIONSHIPS = 5000

_engine = None


def _eng():
    global _engine
    if _engine is None:
        url = os.environ.get("WTF_DATABASE_URL")
        if not url:
            raise RuntimeError("WTF_DATABASE_URL not set")
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


# All direct SQL hardcodes the `shared` schema to match the _upsert_entity resolver
# (ADR-EG-001 §3). No WTF_SHARED_SCHEMA env indirection — a non-default value would
# split entities (written by _upsert_entity in `shared`) from their mentions/edges.

# ── Entity resolution (reuses the ONE _upsert_entity resolver) ────────────────

def _resolve_entity_ref(conn, ref, *, slug_cache):
    """Resolve an <entity ref> to an entity id.

    ref is EITHER:
      - {"slug": "..."}  → look up an already-known node by slug (no upsert)
      - a full entity object {canonical_name, slug, entity_type, role, ...}
        → resolve + upsert via _upsert_entity (the single resolver)

    Returns (entity_id, action) or raises ValueError on bad input.
    """
    if not isinstance(ref, dict):
        raise ValueError("entity reference must be an object")

    slug = (ref.get("slug") or "").strip()

    # Pure pointer form: {"slug": "..."} with no canonical_name → must already exist.
    if slug and not ref.get("canonical_name"):
        if slug in slug_cache:
            return slug_cache[slug], "ref"
        row = conn.execute(
            text(f"SELECT id FROM shared.entities WHERE slug = :slug"),
            {"slug": slug},
        ).mappings().fetchone()
        if row is None:
            raise ValueError(f"entity slug not found: {slug!r}")
        slug_cache[slug] = row["id"]
        return row["id"], "ref"

    # Full entity object → validate + upsert.
    return _upsert_inline_entity(conn, ref, slug_cache=slug_cache)


def _upsert_inline_entity(conn, ent, *, slug_cache):
    """Validate a full entity object and upsert it via the single resolver.

    Returns (entity_id, action) where action is from _upsert_entity
    ('created'|'updated'|'noop').
    """
    canonical_name = (ent.get("canonical_name") or "").strip()
    slug = (ent.get("slug") or "").strip()
    entity_type = (ent.get("entity_type") or "").strip().lower()
    role = ent.get("role") or {}
    raw_name = (ent.get("raw_name") or canonical_name).strip()

    if not canonical_name:
        raise ValueError("entity.canonical_name is required")
    if not slug:
        raise ValueError("entity.slug is required")
    if entity_type not in VALID_NODE_TYPES:
        raise ValueError(
            f"entity_type {entity_type!r} not in frozen node set "
            f"{sorted(VALID_NODE_TYPES)} (ADR-EG-001 §1)"
        )
    if not isinstance(role, dict):
        raise ValueError("entity.role must be an object")

    entity_id, action = _upsert_entity(
        conn,
        canonical_name=canonical_name,
        slug=slug,
        entity_type=entity_type,
        role=role,
        raw_name=raw_name,
        dry_run=False,
    )
    slug_cache[slug] = entity_id
    return entity_id, action


def _upsert_mention(conn, *, entity_id, product, m):
    content_type = (m.get("content_type") or "").strip()
    content_id = m.get("content_id")
    content_id = str(content_id).strip() if content_id is not None else ""
    if not content_type or not content_id:
        raise ValueError("mention requires content_type and content_id")

    confidence = m.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            raise ValueError("mention.confidence must be a number")
        if not (0.0 <= confidence <= 1.0):
            raise ValueError("mention.confidence must be between 0 and 1")

    conn.execute(
        text(f"""
            INSERT INTO shared.entity_mentions
                (entity_id, product, content_type, content_id, mention_context, confidence)
            VALUES
                (:eid, :product, :ctype, :cid, :ctx, :conf)
            ON CONFLICT (entity_id, product, content_type, content_id)
            DO UPDATE SET
                mention_context = COALESCE(EXCLUDED.mention_context, shared.entity_mentions.mention_context),
                confidence      = COALESCE(EXCLUDED.confidence, shared.entity_mentions.confidence)
        """),
        {
            "eid": entity_id,
            "product": product,
            "ctype": content_type,
            "cid": content_id,
            "ctx": m.get("mention_context"),
            "conf": confidence,
        },
    )


def _upsert_relationship(conn, *, from_id, to_id, product, r):
    rel_type = (r.get("relationship_type") or "").strip()
    if rel_type not in VALID_EDGE_TYPES:
        raise ValueError(
            f"relationship_type {rel_type!r} not in frozen edge vocabulary "
            f"{sorted(VALID_EDGE_TYPES)} (ADR-EG-001 §2.4). "
            f"No new edge string ships without amending the ADR first."
        )
    conn.execute(
        text(f"""
            INSERT INTO shared.entity_relationships
                (from_entity_id, to_entity_id, relationship_type,
                 source_product, source_id, valid_from, valid_to, metadata)
            VALUES
                (:from_id, :to_id, :rtype, :product, :source_id,
                 :valid_from, :valid_to, CAST(:meta AS JSONB))
            ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
            DO UPDATE SET
                valid_from = EXCLUDED.valid_from,
                valid_to   = EXCLUDED.valid_to,
                metadata   = EXCLUDED.metadata
        """),
        {
            "from_id": from_id,
            "to_id": to_id,
            "rtype": rel_type,
            "product": product,
            "source_id": (str(r["source_id"]).strip() if r.get("source_id") is not None else None),
            "valid_from": r.get("valid_from"),
            "valid_to": r.get("valid_to"),
            "meta": json.dumps(r.get("metadata") or {}),
        },
    )


# ── The endpoint ──────────────────────────────────────────────────────────────

@entity_graph_bp.route("/api/internal/entity-graph/ingest", methods=["POST"])
def ingest_entity_graph():
    """Single-writer ingest for the shared entity graph (T-ING-1).

    CANONICAL ENTITY / NODE / EDGE writes go to the hub `wtf` DB `shared` schema
    ONLY (ADR-EG-001 §3). NEVER the `archie` DB `shared.entities` signal bus.
    """
    # Auth — same pattern as internal_set_tier (routes.py).
    expected = os.environ.get("INTERNAL_API_KEY", "")
    if not expected:
        return jsonify({"error": "internal key not configured"}), 503
    if request.headers.get("X-Internal-Key", "") != expected:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    product = (data.get("product") or "").strip().lower()
    if product not in VALID_PRODUCTS:
        return jsonify({
            "error": f"product {product!r} not in {sorted(VALID_PRODUCTS)}"
        }), 400

    entities = data.get("entities") or []
    mentions = data.get("mentions") or []
    relationships = data.get("relationships") or []
    for name, coll, cap in (
        ("entities", entities, _MAX_ENTITIES),
        ("mentions", mentions, _MAX_MENTIONS),
        ("relationships", relationships, _MAX_RELATIONSHIPS),
    ):
        if not isinstance(coll, list):
            return jsonify({"error": f"{name} must be a list"}), 400
        if len(coll) > cap:
            return jsonify({"error": f"{name} exceeds batch cap {cap}"}), 413

    stats = {
        "product": product,
        "entities_created": 0,
        "entities_updated": 0,
        "entities_noop": 0,
        "mentions_upserted": 0,
        "relationships_upserted": 0,
    }

    try:
        # ONE transaction — partial adapter batches never half-write the graph.
        with _eng().begin() as conn:
            slug_cache = {}

            # 1) Entities — resolve + upsert via the single resolver.
            for ent in entities:
                _, action = _upsert_inline_entity(conn, ent, slug_cache=slug_cache)
                if action == "created":
                    stats["entities_created"] += 1
                elif action == "updated":
                    stats["entities_updated"] += 1
                else:
                    stats["entities_noop"] += 1

            # 2) Mentions — resolve the entity ref, then UPSERT the content pointer.
            for m in mentions:
                entity_id, _ = _resolve_entity_ref(conn, m.get("entity"), slug_cache=slug_cache)
                _upsert_mention(conn, entity_id=entity_id, product=product, m=m)
                stats["mentions_upserted"] += 1

            # 3) Relationships — resolve both ends, then UPSERT the typed edge.
            for r in relationships:
                from_id, _ = _resolve_entity_ref(conn, r.get("from"), slug_cache=slug_cache)
                to_id, _ = _resolve_entity_ref(conn, r.get("to"), slug_cache=slug_cache)
                _upsert_relationship(conn, from_id=from_id, to_id=to_id, product=product, r=r)
                stats["relationships_upserted"] += 1
    except ValueError as exc:
        # Bad payload (unknown type, missing field) — caller's fault. 400, no partial write.
        logger.warning("[entity-graph ingest] rejected %s payload: %s", product, exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("[entity-graph ingest] failed for product=%s", product)
        return jsonify({"error": "ingest_failed", "detail": str(exc)}), 500

    return jsonify({"ok": True, **stats})
