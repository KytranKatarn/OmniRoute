"""entity_graph_routes.py — Shared Entity Graph INGEST endpoint (T-ING-1).

THE SINGLE WRITER for the canonical accountability graph.

  POST /api/internal/entity-graph/ingest   (auth: X-Internal-Key == INTERNAL_API_KEY)

Architecture (ADR-EG-001 §5 + must-fix I1):
  - This endpoint lives INSIDE the WTF consumer app because the consumer already
    holds WTF_DATABASE_URL and the resolver lives in this repo (ingest.shared.entity_graph).
  - gov-watch / civic-watch / legal-watch / market-watch adapters POST their
    entities/mentions/relationships HERE over the mesh. They do NOT open a
    cross-host DB connection. Only WTF's own hub-resident adapters write the DB
    directly. => single-writer; ONE slug algorithm (name_to_slug+normalize_name).

PERF — BULK INSERT (#4181): all writes are SET-BASED via psycopg2.extras.execute_values
  (3 statements per request: entities, mentions, relationships) instead of row-by-row
  upserts over the mesh. Row-by-row could not finish a dense batch within the gunicorn
  worker timeout (civic 50k lobby backfill: 103/103 batches timed out). Validation runs
  UP FRONT (still 400s cleanly with no partial write); the transaction only bulk-writes.

DUAL-SCHEMA BOUNDARY (ADR-EG-001 §3 — must-fix S6):
  The CANONICAL graph is the hub `wtf` DB `shared` schema (entity_type
  person|organization|journalist). The hub `archie` DB ALSO has a shared.entities
  table (migration 393) but that is a SEPARATE follow/alert SIGNAL BUS and is NEVER
  written or read here. This endpoint connects ONLY to WTF_DATABASE_URL.

Body (JSON):
  {
    "product": "gov-watch|civic-watch|legal-watch|market-watch|wtf",
    "entities":      [{"canonical_name","entity_type","role":{...},"raw_name"?}],
    "mentions":      [{"entity":<ref>,"content_type","content_id","mention_context"?,"confidence"?}],
    "relationships": [{"from":<ref>,"to":<ref>,"relationship_type","source_id"?,"valid_from"?,"valid_to"?,"metadata"?}]
  }
  <ref> = an inline entity object (slug DERIVED server-side) OR {"slug":"..."} pointing
  at an already-known node.

Idempotent: entities UPSERT on slug (roles/aliases merged in SQL); mentions UPSERT on
  UNIQUE (entity_id, product, content_type, content_id); relationships UPSERT on UNIQUE
  (from_entity_id, to_entity_id, relationship_type, source_product, source_id).
"""
import json
import logging
import os

from flask import Blueprint, jsonify, request
from sqlalchemy import create_engine
from psycopg2.extras import execute_values

# The ONE slug algorithm — derive slugs server-side so the same name from any of the
# 5 products resolves to one node (ADR-EG-001 §3).
from ingest.shared.entity_graph import normalize_name, name_to_slug, is_placeholder_name

logger = logging.getLogger("wtf-consumer.entity_graph_ingest")

entity_graph_bp = Blueprint("entity_graph", __name__)

# ── Frozen vocabulary (ADR-EG-001 §1 + §2.4). Import-verbatim; never hand-type. ──

VALID_NODE_TYPES = frozenset({"person", "organization", "journalist"})

VALID_EDGE_TYPES = frozenset({
    # SPINE
    "donated_to", "cast_vote", "enacted_as", "awarded_to", "contracts_with",
    "market_reaction_to", "covered_by",
    # ENRICHMENT
    "lobbied_by", "appointed_to", "employs",
})

VALID_PRODUCTS = frozenset({
    "wtf", "gov-watch", "civic-watch", "legal-watch", "market-watch",
})

_MAX_ENTITIES = 5000
_MAX_MENTIONS = 5000
_MAX_RELATIONSHIPS = 5000

# ── Bulk SQL (all hardcode the `shared` schema, ADR-EG-001 §3). ───────────────

# Roles merge by (type, external_id); aliases merge DISTINCT. (xmax=0) => freshly
# inserted. Validated on live data in a rolled-back txn before shipping (#4181).
_ENTITY_UPSERT = """
    INSERT INTO shared.entities (entity_type, canonical_name, slug, aliases, roles, metadata)
    VALUES %s
    ON CONFLICT (slug) DO UPDATE SET
        aliases = ARRAY(SELECT DISTINCT unnest(shared.entities.aliases || EXCLUDED.aliases)),
        roles = shared.entities.roles || COALESCE((
            SELECT jsonb_agg(er)
            FROM jsonb_array_elements(EXCLUDED.roles) er
            WHERE NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(shared.entities.roles) xr
                WHERE COALESCE(xr->>'type','') = COALESCE(er->>'type','')
                  AND COALESCE(xr->>'external_id','') = COALESCE(er->>'external_id','')
            )
        ), '[]'::jsonb),
        -- ADR-EG-001 amendment (2026-06-25): shallow-merge metadata so naics_* (or
        -- any product's keys) accrete without clobbering existing keys. NULL/absent
        -- incoming metadata is a no-op (backward-compatible).
        metadata = COALESCE(shared.entities.metadata, '{}'::jsonb)
                   || COALESCE(EXCLUDED.metadata, '{}'::jsonb),
        updated_at = NOW()
    RETURNING id, slug, (xmax = 0) AS created
"""
_ENTITY_TPL = "(%s, %s, %s, %s::text[], %s::jsonb, %s::jsonb)"


def _follow_merges(cur, slug_to_id):
    """Rewrite slug_to_id so every id points at the live (non-merged) entity.

    A merged entity keeps its slug, so an upsert/lookup by slug lands on the OLD row. Attaching
    edges, mentions or external ids to it strands them there: 20 merged entities (one with
    122,253 elections_canada edges) were still gaining edges every run on 2026-10-05. Chains are
    flattened by the dedup engine, but follow up to a few hops anyway.
    """
    for _ in range(5):
        ids = list(set(slug_to_id.values()))
        if not ids:
            return slug_to_id
        cur.execute("SELECT id, merged_into FROM shared.entities "
                    "WHERE id = ANY(%s) AND status = 'merged' AND merged_into IS NOT NULL", (ids,))
        moved = {eid: into for eid, into in cur.fetchall()}
        if not moved:
            return slug_to_id
        for slug, eid in list(slug_to_id.items()):
            if eid in moved:
                slug_to_id[slug] = moved[eid]
    return slug_to_id


def _apply_slug_remap(remap, inline, mention_rows, rel_rows):
    """Rename slugs in-place across the three collected structures (pure; no DB).

    ``remap`` maps old slug -> new slug. Pointer refs are deliberately NOT remapped: a pointer
    names an existing node explicitly, so it must keep meaning exactly that node.
    """
    if not remap:
        return
    for old, new in remap.items():
        if old in inline:
            inline[new] = inline.pop(old)
    for key in list(mention_rows):
        slug, ctype, cid = key
        if slug in remap:
            row = mention_rows.pop(key)
            mention_rows[(remap[slug], ctype, cid)] = (remap[slug],) + tuple(row[1:])
    for key in list(rel_rows):
        f, t, rtype, sid = key
        if f in remap or t in remap:
            row = rel_rows.pop(key)
            nf, nt = remap.get(f, f), remap.get(t, t)
            rel_rows[(nf, nt, rtype, sid)] = (nf, nt) + tuple(row[2:])


def _journalist_slug_clashes(cur, inline):
    """Slugs of non-journalist inline entities that would land on an existing JOURNALIST row.

    Slugs are one namespace across node types, and the upsert is ON CONFLICT (slug) which keeps
    the EXISTING type. A vendor or contracting contact who shares a name with a byline journalist
    therefore latched onto the journalist: 41 journalists (Nick Perry 50 awards, Susan O'Brien 44,
    University of Calgary 58, ...) carried gov-watch edges, and a data split would have been undone
    by the next nightly push. Such an entity gets its own node, slug "<slug>-<entity_type>".
    """
    cand = [s for s, e in inline.items() if e["etype"] != "journalist"]
    if not cand:
        return {}
    cur.execute("SELECT slug FROM shared.entities "
                "WHERE slug = ANY(%s) AND entity_type = 'journalist' AND status <> 'merged'", (cand,))
    return {slug: f"{slug}-{inline[slug]['etype']}" for (slug,) in cur.fetchall()}

_MENTION_UPSERT = """
    INSERT INTO shared.entity_mentions
        (entity_id, product, content_type, content_id, mention_context, confidence)
    VALUES %s
    ON CONFLICT (entity_id, product, content_type, content_id) DO UPDATE SET
        mention_context = COALESCE(EXCLUDED.mention_context, shared.entity_mentions.mention_context),
        confidence      = COALESCE(EXCLUDED.confidence, shared.entity_mentions.confidence)
"""
_MENTION_TPL = "(%s, %s, %s, %s, %s, %s)"

_REL_UPSERT = """
    INSERT INTO shared.entity_relationships
        (from_entity_id, to_entity_id, relationship_type, source_product,
         source_id, valid_from, valid_to, metadata)
    VALUES %s
    ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
    DO UPDATE SET
        valid_from = EXCLUDED.valid_from,
        valid_to   = EXCLUDED.valid_to,
        metadata   = EXCLUDED.metadata
"""
_REL_TPL = "(%s, %s, %s, %s, %s, %s, %s, %s::jsonb)"

# Stable cross-product identity keys (ADR-EG-001 amendment). UNIQUE is on
# (key_type, key_value) — one issuer number resolves to ONE entity — so a re-ingest
# re-points entity_id idempotently (e.g. key_type='sedar_issuer').
_EXTID_UPSERT = """
    INSERT INTO shared.entity_external_ids (entity_id, key_type, key_value, source_product)
    VALUES %s
    ON CONFLICT (key_type, key_value) DO UPDATE SET
        entity_id = EXCLUDED.entity_id,
        source_product = COALESCE(EXCLUDED.source_product, shared.entity_external_ids.source_product)
"""
_EXTID_TPL = "(%s, %s, %s, %s)"

_engine = None


def _eng():
    global _engine
    if _engine is None:
        url = os.environ.get("WTF_DATABASE_URL")
        if not url:
            raise RuntimeError("WTF_DATABASE_URL not set")
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


# ── Ref collection / validation (UP FRONT — raises ValueError -> 400, no write) ──

def _register_ref(ref, inline, pointers):
    """Register an <entity ref>; return its slug.

    Returns None for a PLACEHOLDER ("N/A", "unknown", ...): it must not become a node.

    Inline (has canonical_name) -> derive slug + collect for bulk upsert (dedup by
    slug, merging roles/aliases within the batch — a bulk statement can't touch the
    same conflict row twice). Pointer ({"slug": "..."}) -> collect slug for lookup.
    """
    if not isinstance(ref, dict):
        raise ValueError("entity reference must be an object")

    canonical_name = (ref.get("canonical_name") or "").strip()
    if canonical_name and is_placeholder_name(canonical_name):
        return None          # "N/A" is not an entity; the caller drops whatever referenced it
    if canonical_name:
        slug = name_to_slug(normalize_name(canonical_name))
        if not slug:
            raise ValueError(f"canonical_name {canonical_name!r} normalized to an empty slug")
        entity_type = (ref.get("entity_type") or "").strip().lower()
        if entity_type not in VALID_NODE_TYPES:
            raise ValueError(
                f"entity_type {entity_type!r} not in frozen node set "
                f"{sorted(VALID_NODE_TYPES)} (ADR-EG-001 §1)"
            )
        role = ref.get("role") or {}
        if not isinstance(role, dict):
            raise ValueError("entity.role must be an object")
        raw_name = (ref.get("raw_name") or canonical_name).strip()

        # ── ADR-EG-001 amendment (2026-06-25): optional sector/identity surface ──
        # metadata = freeform JSONB merged on upsert (e.g. naics_code/naics_sector);
        # external_ids = stable cross-product keys (e.g. {"key_type":"sedar_issuer",
        # "key_value":"000012345"}). Both additive — callers omitting them unaffected.
        metadata = ref.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("entity.metadata must be an object")
        ext_ids = []
        for x in (ref.get("external_ids") or []):
            if not isinstance(x, dict):
                raise ValueError("entity.external_ids items must be objects")
            kt = str(x.get("key_type") or "").strip()
            kv = str(x.get("key_value") if x.get("key_value") is not None else "").strip()
            if not kt or not kv:
                raise ValueError("external_id requires non-empty key_type and key_value")
            ext_ids.append((kt, kv))

        e = inline.get(slug)
        if e is None:
            inline[slug] = {"etype": entity_type, "cname": canonical_name,
                            "raws": [raw_name], "roles": [role] if role else [],
                            "meta": dict(metadata), "ext_ids": list(ext_ids)}
        else:
            if raw_name and raw_name not in e["raws"]:
                e["raws"].append(raw_name)
            if role:
                rk = (role.get("type"), role.get("external_id"))
                if not any((x.get("type"), x.get("external_id")) == rk for x in e["roles"]):
                    e["roles"].append(role)
            if metadata:
                e["meta"].update(metadata)        # later refs in the batch win
            for pair in ext_ids:
                if pair not in e["ext_ids"]:
                    e["ext_ids"].append(pair)
        return slug

    slug = (ref.get("slug") or "").strip()
    if not slug:
        raise ValueError("entity reference needs canonical_name or slug")
    if is_placeholder_name(slug.replace("-", " ")):
        return None
    pointers.add(slug)
    return slug


def _mention_conf(m):
    confidence = m.get("confidence")
    if confidence is None:
        return None
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise ValueError("mention.confidence must be a number")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError("mention.confidence must be between 0 and 1")
    return confidence


# ── The endpoint ──────────────────────────────────────────────────────────────

@entity_graph_bp.route("/api/internal/entity-graph/ingest", methods=["POST"])
def ingest_entity_graph():
    """Single-writer BULK ingest for the shared entity graph (T-ING-1).

    Writes go to the hub `wtf` DB `shared` schema ONLY (ADR-EG-001 §3).
    """
    expected = os.environ.get("INTERNAL_API_KEY", "")
    if not expected:
        return jsonify({"error": "internal key not configured"}), 503
    if request.headers.get("X-Internal-Key", "") != expected:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    product = (data.get("product") or "").strip().lower()
    if product not in VALID_PRODUCTS:
        return jsonify({"error": f"product {product!r} not in {sorted(VALID_PRODUCTS)}"}), 400

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

    stats = {"product": product, "entities_created": 0, "entities_updated": 0,
             "external_ids_upserted": 0,
             "mentions_upserted": 0, "relationships_upserted": 0,
             "skipped_placeholder": 0}

    try:
        # ── Phase 0: collect + validate everything UP FRONT (no DB writes yet) ──
        inline = {}        # slug -> {etype, cname, raws, roles}
        pointers = set()   # slugs referenced by pointer only (must pre-exist)

        for ent in entities:
            _register_ref(ent, inline, pointers)

        mention_rows = {}  # (slug, ctype, cid) -> (slug, ctype, cid, ctx, conf)  (dedup within batch)
        for m in mentions:
            slug = _register_ref(m.get("entity") or {}, inline, pointers)
            if slug is None:
                stats["skipped_placeholder"] += 1
                continue
            ctype = (m.get("content_type") or "").strip()
            cid = m.get("content_id")
            cid = str(cid).strip() if cid is not None else ""
            if not ctype or not cid:
                raise ValueError("mention requires content_type and content_id")
            mention_rows[(slug, ctype, cid)] = (slug, ctype, cid, m.get("mention_context"), _mention_conf(m))

        rel_rows = {}      # (f, t, rtype, sid) -> tuple  (dedup within batch)
        for r in relationships:
            rtype = (r.get("relationship_type") or "").strip()
            if rtype not in VALID_EDGE_TYPES:
                raise ValueError(
                    f"relationship_type {rtype!r} not in frozen edge vocabulary "
                    f"{sorted(VALID_EDGE_TYPES)} (ADR-EG-001 §2.4)."
                )
            fslug = _register_ref(r.get("from") or {}, inline, pointers)
            tslug = _register_ref(r.get("to") or {}, inline, pointers)
            if fslug is None or tslug is None:
                stats["skipped_placeholder"] += 1
                continue
            sid = str(r["source_id"]).strip() if r.get("source_id") is not None else None
            rel_rows[(fslug, tslug, rtype, sid)] = (
                fslug, tslug, rtype, sid, r.get("valid_from"), r.get("valid_to"),
                json.dumps(r.get("metadata") or {}),
            )
    except ValueError as exc:
        logger.warning("[entity-graph ingest] rejected %s payload: %s", product, exc)
        return jsonify({"error": str(exc)}), 400

    try:
        # ── ONE transaction; 3 bulk statements. ──
        with _eng().begin() as conn:
            cur = conn.connection.cursor()
            slug_to_id = {}

            # 0) A non-journalist must not latch onto a same-slug JOURNALIST (see helper).
            if inline:
                remap = _journalist_slug_clashes(cur, inline)
                if remap:
                    _apply_slug_remap(remap, inline, mention_rows, rel_rows)
                    stats["journalist_slug_remapped"] = len(remap)

            # 1) Entities — bulk upsert (roles/aliases merged in SQL).
            if inline:
                erows = [(e["etype"], e["cname"], slug, e["raws"], json.dumps(e["roles"]),
                          json.dumps(e.get("meta") or {}))
                         for slug, e in inline.items()]
                res = execute_values(cur, _ENTITY_UPSERT, erows, template=_ENTITY_TPL,
                                     page_size=1000, fetch=True)
                for eid, slug, created in res:
                    slug_to_id[slug] = eid
                    stats["entities_created" if created else "entities_updated"] += 1
                _follow_merges(cur, slug_to_id)

            # 1b) External ids — stable cross-product keys (ADR-EG-001 amendment).
            #     Only inline (this-batch) entities carry them; pointer refs do not.
            if inline:
                extid_rows = [(slug_to_id[slug], kt, kv, product)
                              for slug, e in inline.items()
                              for (kt, kv) in e.get("ext_ids", [])
                              if slug in slug_to_id]
                if extid_rows:
                    execute_values(cur, _EXTID_UPSERT, extid_rows, template=_EXTID_TPL,
                                   page_size=1000)
                    stats["external_ids_upserted"] = len(extid_rows)

            # 2) Pointer refs — bulk lookup any not already upserted this batch.
            missing = [s for s in pointers if s not in slug_to_id]
            if missing:
                cur.execute("SELECT id, slug FROM shared.entities WHERE slug = ANY(%s)", (missing,))
                for eid, slug in cur.fetchall():
                    slug_to_id[slug] = eid
                _follow_merges(cur, slug_to_id)
                still = [s for s in missing if s not in slug_to_id]
                if still:
                    raise ValueError(f"entity slug(s) not found: {still[:5]}")

            # 3) Mentions — bulk upsert.
            if mention_rows:
                mrows = [(slug_to_id[slug], product, ctype, cid, ctx, conf)
                         for (slug, ctype, cid, ctx, conf) in mention_rows.values()]
                execute_values(cur, _MENTION_UPSERT, mrows, template=_MENTION_TPL, page_size=1000)
                stats["mentions_upserted"] = len(mrows)

            # 4) Relationships — bulk upsert.
            if rel_rows:
                rrows = [(slug_to_id[f], slug_to_id[t], rtype, product, sid, vf, vt, meta)
                         for (f, t, rtype, sid, vf, vt, meta) in rel_rows.values()]
                execute_values(cur, _REL_UPSERT, rrows, template=_REL_TPL, page_size=1000)
                stats["relationships_upserted"] = len(rrows)

            cur.close()
    except ValueError as exc:
        logger.warning("[entity-graph ingest] rejected %s payload: %s", product, exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("[entity-graph ingest] failed for product=%s", product)
        return jsonify({"error": "ingest_failed", "detail": str(exc)}), 500

    return jsonify({"ok": True, **stats})


@entity_graph_bp.route("/api/internal/entity-graph/companies", methods=["GET"])
def list_companies():
    """Read-only: the TMX-derived listed-company set (slug + canonical_name).

    Product adapters (e.g. legal-watch #3059) fetch this to match free-text targets to
    EXISTING company nodes, then emit mentions via slug pointers (never creating nodes).
    Auth: X-Internal-Key == INTERNAL_API_KEY (same as the ingest endpoint).
    """
    expected = os.environ.get("INTERNAL_API_KEY", "")
    if not expected:
        return jsonify({"error": "internal key not configured"}), 503
    if request.headers.get("X-Internal-Key", "") != expected:
        return jsonify({"error": "unauthorized"}), 401

    with _eng().connect() as conn:
        cur = conn.connection.cursor()
        cur.execute(
            "SELECT slug, canonical_name FROM shared.entities "
            "WHERE entity_type = 'organization' "
            "AND metadata->>'naics_source' IS NOT NULL "
            "ORDER BY slug"
        )
        rows = cur.fetchall()
        cur.close()
    return jsonify({"companies": [{"slug": s, "canonical_name": n} for s, n in rows]})
