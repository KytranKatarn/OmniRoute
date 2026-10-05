"""ingest/entity_graph_wtf_reconcile.py — WTF -> Shared Entity Graph reconcile.

Wave 1 of project #373 (Shared Entity Graph). WTF is the "Coverage" node of the
8-link accountability chain (...-> Coverage -> Public). Unlike the gov/civic/legal
adapters (which POST over the mesh from a different host), WTF OWNS the canonical
`wtf` DB, so this reconcile writes the shared graph DIRECTLY + SET-BASED (no mesh
round-trips, no contention with the HTTP ingest endpoint).

Already in the graph (Milestone A/B): 231 journalist entities + ~6.8k article
mentions, and 353 MP person entities (parliament.mps -> shared.entities).

This reconcile fills the two remaining WTF gaps:
  1. OUTLETS: wtf.sources (news outlets) -> shared.entities organization
     (role 'news_outlet', with bias_lean/owner metadata). Slug derived via the ONE
     shared algorithm (name_to_slug(normalize_name(name))) for cross-resolution.
  2. COVERAGE EDGES: MP --covered_by--> outlet (chain Link 7), set-based from
     wtf.article_mp_tags JOIN parliament.mps JOIN shared.entities(MP) JOIN
     wtf.articles JOIN wtf.sources JOIN shared.entities(outlet). source_id = the
     article id, so each article's coverage is one idempotent edge.

NOT done here: outlet->article mentions (high volume, low marginal value) and the
journalist byline pipeline (Milestone B already populates those).

Env:  WTF_DATABASE_URL
Run:  python -m ingest.entity_graph_wtf_reconcile --dry-run
      python -m ingest.entity_graph_wtf_reconcile
"""
import argparse
import logging
import os

from sqlalchemy import create_engine, text

from ingest.shared.entity_graph import _upsert_entity, normalize_name, name_to_slug

logger = logging.getLogger("wtf.entity_graph_reconcile")

# Both joins require status='active': a merged person/outlet keeps its slug/name, so matching it would
# attach new covered_by edges to a dead row instead of its survivor (2026-10-05, #3650).
_COVERED_BY_SQL = text("""
    INSERT INTO shared.entity_relationships
        (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
    SELECT DISTINCT emp.id, eo.id, 'covered_by', 'wtf', amt.article_id::text
    FROM wtf.article_mp_tags amt
    JOIN parliament.mps m       ON m.id = amt.mp_id
    JOIN shared.entities emp    ON emp.slug = m.slug AND emp.entity_type = 'person' AND emp.status = 'active'
    JOIN wtf.articles a         ON a.id = amt.article_id AND a.source_id IS NOT NULL
    JOIN wtf.sources s          ON s.id = a.source_id
    JOIN shared.entities eo     ON eo.canonical_name = s.name AND eo.entity_type = 'organization' AND eo.status = 'active'
    ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
    DO NOTHING
""")


def _engine():
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url, pool_pre_ping=True)


def run(dry_run=False):
    totals = {"outlets_created": 0, "outlets_updated": 0, "outlets_noop": 0, "covered_by_edges": 0}
    eng = _engine()
    with eng.begin() as conn:
        # 1) OUTLETS — wtf.sources -> organization entities (role news_outlet)
        sources = conn.execute(text("""
            SELECT id, name, url, country, language, bias_lean, owner_name, owner_type, owner_group
            FROM wtf.sources
        """)).mappings().fetchall()
        for s in sources:
            name = (s["name"] or "").strip()
            if not name:
                continue
            slug = name_to_slug(normalize_name(name))
            if not slug:
                continue
            role = {
                "type": "news_outlet",
                "source": "wtf",
                "bias_lean": s["bias_lean"],
                "owner_name": s["owner_name"],
                "owner_type": s["owner_type"],
                "country": s["country"],
                "url": s["url"],
            }
            if dry_run:
                totals["outlets_noop"] += 1
                continue
            _eid, action = _upsert_entity(
                conn, canonical_name=name, slug=slug, entity_type="organization",
                role=role, raw_name=name, dry_run=False,
            )
            totals["outlets_" + ("created" if action == "created" else "updated" if action == "updated" else "noop")] += 1

        # 2) COVERAGE EDGES — MP covered_by outlet (set-based). Needs outlets present,
        #    so it runs after the upsert above (same transaction).
        if dry_run:
            cnt = conn.execute(text("""
                SELECT count(*) FROM (
                  SELECT DISTINCT emp.id, eo.id, amt.article_id
                  FROM wtf.article_mp_tags amt
                  JOIN parliament.mps m    ON m.id = amt.mp_id
                  JOIN shared.entities emp ON emp.slug = m.slug AND emp.entity_type='person' AND emp.status = 'active'
                  JOIN wtf.articles a      ON a.id = amt.article_id AND a.source_id IS NOT NULL
                  JOIN wtf.sources s       ON s.id = a.source_id
                  JOIN shared.entities eo  ON eo.canonical_name = s.name AND eo.entity_type='organization' AND eo.status = 'active'
                ) x
            """)).scalar_one()
            totals["covered_by_edges"] = int(cnt)
        else:
            res = conn.execute(_COVERED_BY_SQL)
            totals["covered_by_edges"] = res.rowcount

    logger.info("wtf entity-graph reconcile done%s: %s", " [dry-run]" if dry_run else "", totals)
    return totals


def main():
    ap = argparse.ArgumentParser(description="WTF -> Shared Entity Graph reconcile (outlets + covered_by)")
    ap.add_argument("--dry-run", action="store_true", help="count only, no writes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
