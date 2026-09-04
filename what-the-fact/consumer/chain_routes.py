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

_PER_TYPE_LIMIT = int(os.environ.get("CHAIN_PER_TYPE_LIMIT", "25"))  # sample cap / type / direction
_CACHE_TTL = int(os.environ.get("CHAIN_CACHE_TTL", "60"))            # seconds — guards the workers
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


_SEARCH_LIMIT = int(os.environ.get("CHAIN_SEARCH_LIMIT", "20"))  # bounded explorer name search


@chain_bp.get("/api/public/chain/search")
def chain_search():
    """Bounded name search over the whole entity graph (all types, not just MPs).

    Powers the explorer's search box. LIMIT-capped + TTL-cached so it can never
    become a heavy read (post 2026-06-15 worker-starvation incident, mistake #273424).
    """
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify({"query": q, "results": []})
    key = f"chain:search:{q}"
    cached = _cache_get(key)
    if cached is not None:
        return jsonify(cached)
    s = _shared()
    with _eng().connect() as conn:
        rows = conn.execute(text(
            f"SELECT slug, canonical_name, entity_type, roles "
            f"FROM {s}.entities "
            f"WHERE status = 'active' AND canonical_name IS NOT NULL AND lower(canonical_name) LIKE :like "
            f"ORDER BY (lower(canonical_name) = :q) DESC, length(canonical_name) ASC, "
            f"canonical_name ASC LIMIT :lim"
        ), {"like": f"%{q}%", "q": q, "lim": _SEARCH_LIMIT}).mappings().fetchall()
    results = [{"slug": r["slug"], "canonical_name": r["canonical_name"],
                "entity_type": r["entity_type"], "roles": r["roles"]} for r in rows]
    return jsonify(_cache_set(key, {"query": q, "results": results}))


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
        _ent_cols = "id, slug, canonical_name, entity_type, roles, status, merged_into"
        ent = conn.execute(text(
            f"SELECT {_ent_cols} FROM {s}.entities WHERE slug = :slug"
        ), {"slug": slug}).mappings().fetchone()
        if ent is None:
            return jsonify({"error": "entity not found", "slug": slug}), 404
        # follow a dedup merge (one hop) so an old/merged slug resolves to the survivor
        if ent["status"] == "merged" and ent["merged_into"]:
            ent = conn.execute(text(
                f"SELECT {_ent_cols} FROM {s}.entities WHERE id = :id"
            ), {"id": ent["merged_into"]}).mappings().fetchone()
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

        # bounded sample per (direction, type) — one indexed lookup per type via the
        # composite index (to/from_entity_id, relationship_type, id) from migration 036.
        # A high-degree node (e.g. a party with 200k+ donors) reads only _PER_TYPE_LIMIT
        # rows per type via a backward index scan, instead of windowing EVERY edge
        # (the old row_number() OVER (...) was ~1.7s on a 226k-edge node — 2026-06-15 fix).
        samples = {}
        for direction, counts, anchor, other in (
            ("out", out_counts, "from_entity_id", "to_entity_id"),
            ("in", in_counts, "to_entity_id", "from_entity_id"),
        ):
            for c in counts:
                rt = c["relationship_type"]
                rows = conn.execute(text(
                    f"SELECT e2.slug, e2.canonical_name, e2.entity_type, r.source_product "
                    f"FROM {s}.entity_relationships r "
                    f"JOIN {s}.entities e2 ON e2.id = r.{other} "
                    f"WHERE r.{anchor} = :id AND r.relationship_type = :rt "
                    f"ORDER BY r.id DESC LIMIT :lim"
                ), {"id": eid, "rt": rt, "lim": _PER_TYPE_LIMIT}).mappings().fetchall()
                samples[(direction, rt)] = [{
                    "slug": x["slug"], "canonical_name": x["canonical_name"],
                    "entity_type": x["entity_type"], "source_product": x["source_product"],
                } for x in rows]

    # assemble grouped chain blocks

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
            "id": ent["id"], "slug": ent["slug"], "canonical_name": ent["canonical_name"],
            "entity_type": ent["entity_type"], "roles": ent["roles"],
            "status": ent["status"],
        },
        "edge_count": sum(b["total"] for b in blocks),
        "chain": blocks,
        "note": "Chain shape + connected/gap status is public; deep per-link records are gated.",
    }
    return jsonify(_cache_set(key, payload))
