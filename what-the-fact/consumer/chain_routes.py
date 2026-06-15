"""chain_routes.py — 8-link Accountability-Chain query API (project #373, task #3793).

Read-only traversal over the Shared Entity Graph (hub `wtf` DB `shared` schema) that
turns the typed edges into the public accountability chain
(Money -> MP -> Vote -> Policy -> Contract -> Market -> Coverage -> Public).

  GET /api/public/chain/links              -> the 8-link catalog (which links have data)
  GET /api/public/chain/entity/<slug>      -> an entity's chain neighborhood (bounded)

DESIGN (owner decision 2026-06-14): the chain SHAPE + connected/gap status is PUBLIC
(free, no-auth, cached); deep per-link records are a later gated endpoint.

SAFETY (post 2026-06-15 worker-starvation incident, mistake #273424): every query is
INDEX-bounded (idx_relationships_from/to) with a per-type LIMIT + a short TTL cache, so a
high-degree node (e.g. an MP covered by 1,600+ articles) NEVER dumps all rows or hogs a
gunicorn worker. We return a per-type total COUNT + a bounded SAMPLE.

Honesty: links with no ingest pipeline (Policy=enacted_as, Market=market_reaction_to)
carry has_data=false in shared.chain_link_types and are surfaced as gaps, never faked.
"""
import os
import time

from flask import Blueprint, jsonify, request
from sqlalchemy import create_engine, text

chain_bp = Blueprint("chain", __name__)

_PER_TYPE_LIMIT = 25       # bounded sample per relationship_type per direction
_CACHE_TTL = 60            # seconds — protects the workers from repeated heavy reads
_cache = {}               # path -> (expiry_epoch, payload)

_engine = None


def _eng():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _shared():
    return os.environ.get("WTF_SHARED_SCHEMA", "shared")


def _cache_get(key):
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _cache_set(key, payload):
    _cache[key] = (time.time() + _CACHE_TTL, payload)
    return payload


def _links_catalog(conn):
    """The 8-link chain catalog: position -> relationship types + has_data."""
    s = _shared()
    rows = conn.execute(text(
        f"SELECT link_position, relationship_type, has_data, label "
        f"FROM {s}.chain_link_types ORDER BY link_position, relationship_type"
    )).mappings().fetchall()
    return [dict(r) for r in rows]


@chain_bp.get("/api/public/chain/links")
def chain_links():
    """Public catalog of the 8-link chain — which links currently have data."""
    cached = _cache_get("chain:links")
    if cached is not None:
        return jsonify(cached)
    with _eng().connect() as conn:
        links = _links_catalog(conn)
    have = sorted({l["link_position"] for l in links if l["has_data"]})
    gaps = sorted({l["link_position"] for l in links if not l["has_data"]})
    return jsonify(_cache_set("chain:links", {
        "chain": "Money -> MP -> Vote -> Policy -> Contract -> Market -> Coverage -> Public",
        "links": links,
        "links_with_data": have,
        "links_without_data": gaps,
    }))


@chain_bp.get("/api/public/chain/entity/<slug>")
def chain_entity(slug):
    """An entity's accountability-chain neighborhood (1 hop, bounded + cached).

    Returns the entity + its edges grouped by (relationship_type, direction) with a
    per-group total count and a bounded sample of connected entities, each annotated
    with its chain position + has_data.
    """
    slug = (slug or "").strip().lower()
    if not slug:
        return jsonify({"error": "slug required"}), 400
    key = f"chain:entity:{slug}"
    cached = _cache_get(key)
    if cached is not None:
        return jsonify(cached)

    s = _shared()
    with _eng().connect() as conn:
        ent = conn.execute(text(
            f"SELECT id, slug, canonical_name, entity_type, roles, status "
            f"FROM {s}.entities WHERE slug = :slug"
        ), {"slug": slug}).mappings().fetchone()
        if ent is None:
            return jsonify({"error": "entity not found", "slug": slug}), 404
        eid = ent["id"]

        # chain position + has_data per relationship_type (from the frozen catalog)
        link_meta = {
            r["relationship_type"]: {"chain_position": r["link_position"],
                                     "has_data": r["has_data"], "label": r["label"]}
            for r in conn.execute(text(
                f"SELECT relationship_type, link_position, has_data, label FROM {s}.chain_link_types"
            )).mappings().fetchall()
        }

        # per (direction, relationship_type) totals — index-only, fast even at high degree
        out_counts = conn.execute(text(
            f"SELECT relationship_type, count(*) c FROM {s}.entity_relationships "
            f"WHERE from_entity_id = :id GROUP BY 1"
        ), {"id": eid}).mappings().fetchall()
        in_counts = conn.execute(text(
            f"SELECT relationship_type, count(*) c FROM {s}.entity_relationships "
            f"WHERE to_entity_id = :id GROUP BY 1"
        ), {"id": eid}).mappings().fetchall()

        # bounded sample of connected entities per (direction, type) — windowed, capped
        sample_rows = conn.execute(text(f"""
            SELECT direction, relationship_type, slug, canonical_name, entity_type, source_product
            FROM (
                SELECT 'out' AS direction, r.relationship_type, e2.slug, e2.canonical_name,
                       e2.entity_type, r.source_product,
                       row_number() OVER (PARTITION BY r.relationship_type ORDER BY r.id DESC) rn
                FROM {s}.entity_relationships r JOIN {s}.entities e2 ON e2.id = r.to_entity_id
                WHERE r.from_entity_id = :id
                UNION ALL
                SELECT 'in', r.relationship_type, e2.slug, e2.canonical_name,
                       e2.entity_type, r.source_product,
                       row_number() OVER (PARTITION BY r.relationship_type ORDER BY r.id DESC)
                FROM {s}.entity_relationships r JOIN {s}.entities e2 ON e2.id = r.from_entity_id
                WHERE r.to_entity_id = :id
            ) x
            WHERE rn <= :lim
        """), {"id": eid, "lim": _PER_TYPE_LIMIT}).mappings().fetchall()

    # assemble grouped chain blocks
    samples = {}
    for r in sample_rows:
        samples.setdefault((r["direction"], r["relationship_type"]), []).append({
            "slug": r["slug"], "canonical_name": r["canonical_name"],
            "entity_type": r["entity_type"], "source_product": r["source_product"],
        })

    def _blocks(counts, direction):
        out = []
        for c in counts:
            rt = c["relationship_type"]
            meta = link_meta.get(rt, {})
            out.append({
                "relationship_type": rt,
                "direction": direction,
                "chain_position": meta.get("chain_position"),
                "label": meta.get("label"),
                "has_data": meta.get("has_data", True),
                "total": c["c"],
                "sample": samples.get((direction, rt), []),
                "truncated": c["c"] > _PER_TYPE_LIMIT,
            })
        return out

    blocks = _blocks(out_counts, "out") + _blocks(in_counts, "in")
    blocks.sort(key=lambda b: (b["chain_position"] or 99, b["relationship_type"]))

    payload = {
        "entity": {
            "slug": ent["slug"], "canonical_name": ent["canonical_name"],
            "entity_type": ent["entity_type"], "roles": ent["roles"],
            "status": ent["status"],
        },
        "edge_count": sum(b["total"] for b in blocks),
        "chain": blocks,
        "note": "Chain shape + connected/gap status is public; deep per-link records are gated.",
    }
    return jsonify(_cache_set(key, payload))
