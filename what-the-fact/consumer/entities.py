"""Entity search & grouped-data API (Milestone A — MP search over the shared entity graph).

Read-only endpoints over data that already exists in the `wtf` DB:
  GET /api/entities/search?q=&type=mp|journalist&limit=
  GET /api/entities/<id>/coverage?from=&to=
  GET /api/entities/<id>/accountability   (mp only)

`shared.entity_mentions` is the uniform entity->article link (MPs today, journalists in
Milestone B). Schema names are read at call time so tests can point the app at isolated
*_test schemas without import-order fragility.
"""
import os

from flask import Blueprint, jsonify, request
from sqlalchemy import create_engine, text

from .access import require_product_access

entities_bp = Blueprint("entities", __name__)

_engine = None


def _eng():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _wtf():
    return os.environ.get("WTF_SCHEMA", "wtf")


def _shared():
    return os.environ.get("WTF_SHARED_SCHEMA", "shared")


def _parl():
    return os.environ.get("WTF_PARLIAMENT_SCHEMA", "parliament")


def _coverage_pct(conn):
    """Share of the WTF corpus with any entity attribution (honesty marker so consumers
    never mistake partial data for complete). Milestone B grows the numerator.

    Both halves of the ratio must describe the same population — a suppressed
    article (duplicate refetch, non-article stream, publisher-suffix title) is
    excluded from `total`, so `attributed` must join through to articles and
    exclude it too, or a mention on a suppressed article would inflate the
    numerator against a denominator that no longer counts it.
    """
    total = conn.execute(
        text(f"SELECT count(*) FROM {_wtf()}.articles WHERE suppressed_reason IS NULL")
    ).scalar() or 0
    attributed = conn.execute(
        text(
            f"SELECT count(DISTINCT em.content_id) FROM {_shared()}.entity_mentions em "
            f"JOIN {_wtf()}.articles a ON a.id::text = em.content_id "
            f"WHERE em.product='wtf' AND em.content_type='article' "
            f"AND a.suppressed_reason IS NULL"
        )
    ).scalar() or 0
    return round(100.0 * attributed / total, 1) if total else 0.0


def _envelope(conn, results):
    return {"results": results, "coverage_pct": _coverage_pct(conn)}


@entities_bp.get("/api/entities/search")
def search_entities():
    q = (request.args.get("q") or "").strip()
    etype = (request.args.get("type") or "").strip().lower()
    if etype not in ("mp", "journalist"):
        return jsonify({"error": "type must be 'mp' or 'journalist'"}), 400
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
    except (ValueError, TypeError):
        limit = 20

    s, p = _shared(), _parl()
    if etype == "mp":
        type_clause = (
            f"e.entity_type='person' AND EXISTS "
            f"(SELECT 1 FROM {p}.mps m WHERE m.entity_id=e.id)"
        )
    else:
        type_clause = "e.entity_type='journalist'"
    like = f"%{q.lower()}%"
    # ⚠️ A per-row correlated subquery joining entity_mentions (2.15M rows) to
    # articles here — evaluated once per candidate entity — measured >30s and
    # hung under load (#6244 follow-up). A first fix (bulk CTE over ALL
    # entities, no candidate pre-filter) fixed type=journalist but NOT
    # type=mp: entity_type='person' is a much larger population than
    # 'journalist', and the planner built the LEFT JOIN across all of it
    # before applying the EXISTS(mps) filter — still measured >20s. This
    # version filters to the SMALL candidate set FIRST (343 MPs / ~4,677
    # journalists), then bounds the entity_mentions scan to just those ids —
    # 1.3s (mp) / 1.9s (journalist) measured via EXPLAIN ANALYZE, both paths,
    # same query shape.
    sql = text(
        f"""
        WITH candidates AS (
            SELECT e.id, e.canonical_name, e.slug, e.aliases
              FROM {s}.entities e
             WHERE {type_clause}
        ),
        visible_counts AS (
            SELECT em.entity_id, count(DISTINCT em.content_id) AS article_count
            FROM {s}.entity_mentions em
            JOIN {_wtf()}.articles art ON art.id::text = em.content_id
            WHERE em.product='wtf' AND em.content_type='article'
              AND art.suppressed_reason IS NULL
              AND em.entity_id IN (SELECT id FROM candidates)
            GROUP BY em.entity_id
        )
        SELECT c.id, c.canonical_name, c.slug,
               COALESCE(vc.article_count, 0) AS article_count
          FROM candidates c
          LEFT JOIN visible_counts vc ON vc.entity_id = c.id
         WHERE (:q='' OR lower(c.canonical_name) LIKE :like
                OR EXISTS (SELECT 1 FROM unnest(c.aliases) a WHERE lower(a) LIKE :like))
         ORDER BY article_count DESC, c.canonical_name ASC
         LIMIT :lim
    """
    )
    with _eng().connect() as c:
        rows = c.execute(sql, {"q": q.lower(), "like": like, "lim": limit}).mappings().all()
        results = [
            {
                "id": r["id"],
                "type": etype,
                "canonical_name": r["canonical_name"],
                "slug": r["slug"],
                "article_count": int(r["article_count"]),
            }
            for r in rows
        ]
        return jsonify(_envelope(c, results))


@entities_bp.get("/api/entities/<int:entity_id>/coverage")
@require_product_access("wtf-premium")
def entity_coverage(entity_id):
    frm = request.args.get("from")
    to = request.args.get("to")
    s, w = _shared(), _wtf()
    date_clause = ""
    params = {"eid": entity_id}
    if frm:
        date_clause += " AND a.published_at >= :frm"
        params["frm"] = frm
    if to:
        date_clause += " AND a.published_at <= :to"
        params["to"] = to
    # Compare as text (a.id::text = content_id) rather than casting content_id::integer,
    # so a stray non-numeric content_id can never raise and 500 the request.
    join = (
        f"FROM {s}.entity_mentions em JOIN {w}.articles a ON a.id::text = em.content_id "
        f"WHERE em.entity_id=:eid AND em.product='wtf' AND em.content_type='article' "
        f"AND a.suppressed_reason IS NULL{date_clause}"
    )
    with _eng().connect() as c:
        ent = c.execute(
            text(f"SELECT id, entity_type, canonical_name, slug FROM {s}.entities WHERE id=:eid"),
            {"eid": entity_id},
        ).mappings().first()
        if not ent:
            return jsonify({"error": "entity not found"}), 404
        count = c.execute(text(f"SELECT count(DISTINCT a.id) {join}"), params).scalar()
        bias_rows = c.execute(
            text(
                f"SELECT COALESCE(a.bias_ensemble_band,'unknown') band, count(DISTINCT a.id) n "
                f"{join} GROUP BY 1"
            ),
            params,
        ).mappings().all()
        trend_rows = c.execute(
            text(
                f"SELECT to_char(date_trunc('month', a.published_at),'YYYY-MM') bucket, "
                f"count(DISTINCT a.id) n {join} GROUP BY 1 ORDER BY 1"
            ),
            params,
        ).mappings().all()
        outlet_rows = c.execute(
            text(
                f"SELECT src.slug, src.name, count(DISTINCT a.id) n "
                f"FROM {s}.entity_mentions em JOIN {w}.articles a ON a.id::text=em.content_id "
                f"JOIN {w}.sources src ON src.id=a.source_id "
                f"WHERE em.entity_id=:eid AND em.product='wtf' AND em.content_type='article' "
                f"AND a.suppressed_reason IS NULL"
                f"{date_clause} GROUP BY src.slug, src.name ORDER BY n DESC LIMIT 10"
            ),
            params,
        ).mappings().all()
        return jsonify(
            {
                "entity": {
                    "id": ent["id"],
                    "type": ("mp" if ent["entity_type"] == "person" else ent["entity_type"]),
                    "canonical_name": ent["canonical_name"],
                    "slug": ent["slug"],
                },
                "article_count": int(count or 0),
                "bias_distribution": {r["band"]: int(r["n"]) for r in bias_rows},
                "trend": [{"month": r["bucket"], "count": int(r["n"])} for r in trend_rows],
                "top_outlets": [
                    {"slug": r["slug"], "name": r["name"], "count": int(r["n"])} for r in outlet_rows
                ],
                "coverage_pct": _coverage_pct(c),
            }
        )


@entities_bp.get("/api/entities/<int:entity_id>/accountability")
@require_product_access("wtf-premium")
def entity_accountability(entity_id):
    s, p = _shared(), _parl()
    with _eng().connect() as c:
        mp = c.execute(
            text(
                f"SELECT m.id, m.name, m.party, m.riding FROM {p}.mps m "
                f"JOIN {s}.entities e ON e.id=m.entity_id WHERE e.id=:eid"
            ),
            {"eid": entity_id},
        ).mappings().first()
        if not mp:
            return jsonify({"error": "entity is not a mapped MP"}), 404
        mp_id = mp["id"]
        votes = c.execute(
            text(
                f"SELECT bill_number, description, vote, voted_at::text AS voted_at "
                f"FROM {p}.mp_votes WHERE mp_id=:m ORDER BY voted_at DESC NULLS LAST LIMIT 20"
            ),
            {"m": mp_id},
        ).mappings().all()
        exp = c.execute(
            text(f"SELECT total_cents, period FROM {p}.mp_expense_summary WHERE mp_id=:m"),
            {"m": mp_id},
        ).mappings().first()
        promises = c.execute(
            text(f"SELECT text, status FROM {p}.mp_promises WHERE mp_id=:m LIMIT 50"),
            {"m": mp_id},
        ).mappings().all()
        return jsonify(
            {
                "mp": {"id": mp["id"], "name": mp["name"], "party": mp["party"], "riding": mp["riding"]},
                "recent_votes": [dict(v) for v in votes],
                "expense_summary": (dict(exp) if exp else None),
                "promises": [dict(pr) for pr in promises],
            }
        )


@entities_bp.get("/api/entities/<int:entity_id>/profile")
@require_product_access("wtf-premium")
def entity_profile(entity_id):
    s, w = _shared(), _wtf()
    with _eng().connect() as c:
        ent = c.execute(
            text(
                f"SELECT id, entity_type, canonical_name, slug, metadata FROM {s}.entities "
                f"WHERE id=:e AND entity_type='journalist'"
            ),
            {"e": entity_id},
        ).mappings().first()
        if not ent:
            return jsonify({"error": "journalist not found"}), 404
        join = (
            f"FROM {s}.entity_mentions em JOIN {w}.articles a ON a.id::text = em.content_id "
            f"WHERE em.entity_id=:e AND em.product='wtf' AND em.content_type='article' "
            f"AND a.suppressed_reason IS NULL"
        )
        count = c.execute(text(f"SELECT count(DISTINCT a.id) {join}"), {"e": entity_id}).scalar()
        bias = c.execute(
            text(
                f"SELECT COALESCE(a.bias_ensemble_band,'unknown') band, count(DISTINCT a.id) n "
                f"{join} GROUP BY 1"
            ),
            {"e": entity_id},
        ).mappings().all()
        trend = c.execute(
            text(
                f"SELECT to_char(date_trunc('month', a.published_at),'YYYY-MM') m, "
                f"count(DISTINCT a.id) n {join} GROUP BY 1 ORDER BY 1"
            ),
            {"e": entity_id},
        ).mappings().all()
        outlets = c.execute(
            text(
                f"SELECT src.slug, src.name, count(DISTINCT a.id) n "
                f"FROM {s}.entity_mentions em JOIN {w}.articles a ON a.id::text=em.content_id "
                f"JOIN {w}.sources src ON src.id=a.source_id "
                f"WHERE em.entity_id=:e AND em.product='wtf' AND em.content_type='article' "
                f"AND a.suppressed_reason IS NULL "
                f"GROUP BY src.slug, src.name ORDER BY n DESC LIMIT 10"
            ),
            {"e": entity_id},
        ).mappings().all()
        # journalists/entities co-mentioned on this writer's articles (e.g. the MPs they cover)
        co = c.execute(
            text(
                f"SELECT e2.id, e2.canonical_name, e2.entity_type, count(DISTINCT em2.content_id) n "
                f"FROM {s}.entity_mentions em1 "
                f"JOIN {w}.articles a ON a.id::text = em1.content_id AND a.suppressed_reason IS NULL "
                f"JOIN {s}.entity_mentions em2 ON em2.content_id=em1.content_id "
                f"  AND em2.product='wtf' AND em2.content_type='article' AND em2.entity_id<>em1.entity_id "
                f"JOIN {s}.entities e2 ON e2.id=em2.entity_id "
                f"WHERE em1.entity_id=:e AND em1.product='wtf' AND em1.content_type='article' "
                f"GROUP BY e2.id, e2.canonical_name, e2.entity_type ORDER BY n DESC LIMIT 10"
            ),
            {"e": entity_id},
        ).mappings().all()
        return jsonify(
            {
                "entity": {
                    "id": ent["id"],
                    "type": "journalist",
                    "canonical_name": ent["canonical_name"],
                    "slug": ent["slug"],
                },
                "outlets_declared": (ent["metadata"] or {}).get("outlets", []),
                "article_count": int(count or 0),
                "bias_lean": {r["band"]: int(r["n"]) for r in bias},
                "volume_trend": [{"month": r["m"], "count": int(r["n"])} for r in trend],
                "top_outlets": [
                    {"slug": r["slug"], "name": r["name"], "count": int(r["n"])} for r in outlets
                ],
                "top_co_mentioned": [
                    {"id": r["id"], "name": r["canonical_name"], "type": r["entity_type"],
                     "count": int(r["n"])}
                    for r in co
                ],
                "coverage_pct": _coverage_pct(c),
            }
        )


@entities_bp.get("/api/entities/<int:entity_id>/footprint")
@require_product_access("wtf-premium")
def entity_footprint(entity_id):
    """Cross-product accountability footprint for ANY entity (#3331 Cross-Watch).

    Generalizes the journalist `/profile`: which Watch products mention this
    entity (grouped by `product`) + the chain-link relationships it sits on
    (grouped by relationship_type, labelled via shared.chain_link_types) +
    its WTF news footprint. Read-only over the live shared graph.
    """
    s, w = _shared(), _wtf()
    with _eng().connect() as c:
        ent = c.execute(
            text(
                f"SELECT id, entity_type, canonical_name, slug, aliases "
                f"FROM {s}.entities WHERE id=:e AND status='active'"
            ),
            {"e": entity_id},
        ).mappings().first()
        if not ent:
            return jsonify({"error": "entity not found"}), 404
        # Mentions grouped by product (the cross-product link).
        products = c.execute(
            text(
                f"SELECT product, count(*) AS mentions, count(DISTINCT content_type) AS kinds "
                f"FROM {s}.entity_mentions WHERE entity_id=:e "
                f"GROUP BY product ORDER BY mentions DESC"
            ),
            {"e": entity_id},
        ).mappings().all()
        # Chain-link relationships this entity sits on (single-entity → bounded).
        links = c.execute(
            text(
                f"SELECT r.relationship_type, clt.label, clt.is_spine, "
                f"count(*) FILTER (WHERE r.from_entity_id=:e) AS out_n, "
                f"count(*) FILTER (WHERE r.to_entity_id=:e) AS in_n "
                f"FROM {s}.entity_relationships r "
                f"JOIN {s}.chain_link_types clt ON clt.relationship_type=r.relationship_type "
                f"WHERE r.from_entity_id=:e OR r.to_entity_id=:e "
                f"GROUP BY r.relationship_type, clt.label, clt.is_spine "
                f"ORDER BY count(*) DESC"
            ),
            {"e": entity_id},
        ).mappings().all()
        # WTF news footprint (a.id::text = content_id — never cast content_id->int).
        wtf_articles = c.execute(
            text(
                f"SELECT count(DISTINCT a.id) FROM {s}.entity_mentions em "
                f"JOIN {w}.articles a ON a.id::text=em.content_id "
                f"WHERE em.entity_id=:e AND em.product='wtf' AND em.content_type='article'"
            ),
            {"e": entity_id},
        ).scalar() or 0
        return jsonify(
            {
                "entity": {
                    "id": ent["id"],
                    "type": ent["entity_type"],
                    "canonical_name": ent["canonical_name"],
                    "slug": ent["slug"],
                    "aliases": list(ent["aliases"] or []),
                },
                "products": [
                    {"product": p["product"], "mentions": int(p["mentions"]),
                     "content_types": int(p["kinds"])}
                    for p in products
                ],
                "chain_links": [
                    {"relationship_type": l["relationship_type"], "label": l["label"],
                     "is_spine": l["is_spine"], "as_subject": int(l["out_n"]),
                     "as_object": int(l["in_n"])}
                    for l in links
                ],
                "wtf_article_count": int(wtf_articles),
                "products_count": len(products),
                "total_mentions": sum(int(p["mentions"]) for p in products),
                "coverage_pct": _coverage_pct(c),
            }
        )
