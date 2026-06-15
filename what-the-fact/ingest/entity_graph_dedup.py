"""ingest/entity_graph_dedup.py — Shared Entity Graph dedup engine v1 (project #373, #3792).

Runs against the hub `wtf` DB `shared` schema (direct + set-based). v1 = DETERMINISTIC
exact normalized-name dedup (owner decision 2026-06-15, option B):

  1. BLOCKING — populate shared.entity_blocks (block_kind='norm_name') for person+org
     (foundation for phase-2 fuzzy/trigram candidate generation).
  2. ORGANIZATIONS with identical normalized names -> AUTO-MERGE (revertable). Orgs rarely
     share an exact official name, so this is high-confidence; it also resolves the
     slug-convention split (e.g. 'canada-revenue-agency' vs 'org-canada-revenue-agency').
  3. PERSONS with identical normalized names -> shared.merge_review_queue (pending). People
     DO share names (namesakes), so these are reviewed, never auto-merged. Restricted to
     pairs where one side is a CANONICAL (non-donor) person — i.e. the high-value
     "is this donor actually this MP/journalist?" question — and skips oversized name
     groups (dedup_config.max_block_size).

Phase 2 (NOT here): fuzzy/trigram candidate generation (dedup_config trigram_min/
review_threshold/auto_merge_threshold), fuzzy auto-merge at >=0.92, donor<->donor pairs,
and a revert helper (entity_merge_log already snapshots each merge for manual revert).

Excludes legislation (dedup_config.legislation_fuzzy_enabled=0) and merged/suppressed rows.
Normalized name = lower(unaccent(btrim(canonical_name))).

Env:  WTF_DATABASE_URL
Run:  python -m ingest.entity_graph_dedup --dry-run
      python -m ingest.entity_graph_dedup
"""
import argparse
import json
import logging
import os

from sqlalchemy import create_engine, text

logger = logging.getLogger("entity_graph_dedup")

# normalized-name SQL expression (matchable key)
_NORM = "lower(unaccent(btrim({col})))"


def _engine():
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url, pool_pre_ping=True)


def _merge(conn, survivor, merged, reason, by="dedup_engine"):
    """Merge `merged` entity into `survivor` — repoint edges/mentions, union aliases/roles,
    mark merged, and snapshot to entity_merge_log (revertable). Collision-safe against the
    entity_relationships + entity_mentions unique keys."""
    snap = conn.execute(text(
        "SELECT row_to_json(e) FROM shared.entities e WHERE id=:m"), {"m": merged}).scalar()

    # edges: drop merged-side edges that would duplicate a survivor edge post-repoint, then repoint
    conn.execute(text("""
        DELETE FROM shared.entity_relationships m
        WHERE (m.from_entity_id=:m OR m.to_entity_id=:m) AND EXISTS (
            SELECT 1 FROM shared.entity_relationships s
            WHERE s.id<>m.id
              AND s.relationship_type=m.relationship_type
              AND s.source_product=m.source_product
              AND coalesce(s.source_id,'')=coalesce(m.source_id,'')
              AND s.from_entity_id = CASE WHEN m.from_entity_id=:m THEN :s ELSE m.from_entity_id END
              AND s.to_entity_id   = CASE WHEN m.to_entity_id=:m   THEN :s ELSE m.to_entity_id END)
    """), {"m": merged, "s": survivor})
    conn.execute(text("UPDATE shared.entity_relationships SET from_entity_id=:s WHERE from_entity_id=:m"),
                 {"s": survivor, "m": merged})
    conn.execute(text("UPDATE shared.entity_relationships SET to_entity_id=:s WHERE to_entity_id=:m"),
                 {"s": survivor, "m": merged})

    # mentions: dedup-then-repoint on (entity_id, product, content_type, content_id)
    conn.execute(text("""
        DELETE FROM shared.entity_mentions m
        WHERE m.entity_id=:m AND EXISTS (
            SELECT 1 FROM shared.entity_mentions s
            WHERE s.entity_id=:s AND s.product=m.product
              AND s.content_type=m.content_type AND s.content_id=m.content_id)
    """), {"m": merged, "s": survivor})
    conn.execute(text("UPDATE shared.entity_mentions SET entity_id=:s WHERE entity_id=:m"),
                 {"s": survivor, "m": merged})

    # external ids (empty today, future-safe): repoint non-colliding
    conn.execute(text("""
        UPDATE shared.entity_external_ids x SET entity_id=:s
        WHERE x.entity_id=:m AND NOT EXISTS (
            SELECT 1 FROM shared.entity_external_ids y
            WHERE y.entity_id=:s AND y.key_type=x.key_type AND y.key_value=x.key_value)
    """), {"m": merged, "s": survivor})
    conn.execute(text("DELETE FROM shared.entity_external_ids WHERE entity_id=:m"), {"m": merged})

    # union aliases + roles onto survivor (dedup roles by type+external_id)
    s_row = conn.execute(text("SELECT aliases, roles FROM shared.entities WHERE id=:s"),
                         {"s": survivor}).mappings().one()
    m_row = conn.execute(text("SELECT aliases, roles FROM shared.entities WHERE id=:m"),
                         {"m": merged}).mappings().one()
    aliases = list(dict.fromkeys(list(s_row["aliases"] or []) + list(m_row["aliases"] or [])))
    seen, roles = set(), []
    for r in (list(s_row["roles"] or []) + list(m_row["roles"] or [])):
        k = (r.get("type"), r.get("external_id"))
        if k not in seen:
            seen.add(k)
            roles.append(r)
    conn.execute(text(
        "UPDATE shared.entities SET aliases=:a, roles=CAST(:r AS jsonb), updated_at=now() WHERE id=:s"),
        {"a": aliases, "r": json.dumps(roles), "s": survivor})

    # drop merged's blocks, mark merged, log (revertable)
    conn.execute(text("DELETE FROM shared.entity_blocks WHERE entity_id=:m"), {"m": merged})
    conn.execute(text("UPDATE shared.entities SET status='merged', merged_into=:s WHERE id=:m"),
                 {"s": survivor, "m": merged})
    conn.execute(text("""
        INSERT INTO shared.entity_merge_log (survivor_id, merged_id, merged_snapshot, reason, merged_by)
        VALUES (:s, :m, CAST(:snap AS jsonb), :r, :by)
    """), {"s": survivor, "m": merged, "snap": json.dumps(snap), "r": reason, "by": by})
    # dedup_pair_decisions: decision ∈ {'same','distinct'} + CHECK(entity_id_a < entity_id_b)
    pa, pb = (survivor, merged) if survivor < merged else (merged, survivor)
    conn.execute(text("""
        INSERT INTO shared.dedup_pair_decisions (entity_id_a, entity_id_b, decision, similarity, decided_by)
        VALUES (:a, :b, 'same', 1.0, :by)
    """), {"a": pa, "b": pb, "by": by + ":" + reason})


def run(dry_run=False):
    totals = {"blocks": 0, "org_groups": 0, "org_merges": 0, "person_review_queued": 0}
    eng = _engine()
    norm_c = _NORM.format(col="canonical_name")
    with eng.begin() as conn:
        maxblk = conn.execute(text(
            "SELECT value FROM shared.dedup_config WHERE key='max_block_size'")).scalar()
        maxblk = int(maxblk) if maxblk else 500

        # 1) blocking (foundation for phase-2 fuzzy)
        if not dry_run:
            conn.execute(text("DELETE FROM shared.entity_blocks WHERE block_kind='norm_name'"))
            totals["blocks"] = conn.execute(text(f"""
                INSERT INTO shared.entity_blocks (entity_id, block_key, block_kind)
                SELECT id, {norm_c}, 'norm_name'
                FROM shared.entities
                WHERE status='active' AND entity_type IN ('person','organization')
                  AND btrim(canonical_name) <> ''
            """)).rowcount

        # 2) organizations: exact normalized-name groups -> auto-merge (survivor = most-connected)
        groups = conn.execute(text(f"""
            SELECT {norm_c} AS norm, array_agg(e.id ORDER BY (
                       SELECT count(*) FROM shared.entity_relationships r
                       WHERE r.from_entity_id=e.id OR r.to_entity_id=e.id) DESC, e.id ASC) AS ids
            FROM shared.entities e
            WHERE e.status='active' AND e.entity_type='organization' AND btrim(e.canonical_name) <> ''
            GROUP BY 1 HAVING count(*) > 1
        """)).mappings().fetchall()
        totals["org_groups"] = len(groups)
        for g in groups:
            ids = g["ids"]
            survivor = ids[0]
            for merged in ids[1:]:
                if not dry_run:
                    _merge(conn, survivor, merged, "exact_name_org")
                totals["org_merges"] += 1

        # 3) persons: exact normalized-name -> review queue (canonical-anchored, capped)
        if not dry_run:
            totals["person_review_queued"] = conn.execute(text(f"""
                WITH big AS (
                    SELECT {norm_c} AS norm FROM shared.entities
                    WHERE entity_type='person' AND status='active' AND btrim(canonical_name) <> ''
                    GROUP BY 1 HAVING count(*) > :maxblk
                )
                INSERT INTO shared.merge_review_queue
                    (entity_id_a, entity_id_b, similarity, block_key, features, status)
                SELECT a.id, b.id, 1.0, {_NORM.format(col='a.canonical_name')},
                       jsonb_build_object('match','exact_name','entity_type','person',
                           'a_slug',a.slug,'b_slug',b.slug,'a_roles',a.roles,'b_roles',b.roles),
                       'pending'
                FROM shared.entities a
                JOIN shared.entities b
                  ON {_NORM.format(col='a.canonical_name')} = {_NORM.format(col='b.canonical_name')}
                WHERE a.entity_type='person' AND b.entity_type='person'
                  AND a.status='active' AND b.status='active'
                  AND a.id < b.id
                  AND a.slug NOT LIKE 'donor-%'
                  AND {_NORM.format(col='a.canonical_name')} NOT IN (SELECT norm FROM big)
                  AND btrim(a.canonical_name) <> ''
                  AND NOT EXISTS (SELECT 1 FROM shared.merge_review_queue q
                                  WHERE q.entity_id_a=a.id AND q.entity_id_b=b.id)
            """), {"maxblk": maxblk}).rowcount

    logger.info("entity_graph_dedup done%s: %s", " [dry-run]" if dry_run else "", totals)
    return totals


def main():
    ap = argparse.ArgumentParser(description="Shared Entity Graph dedup engine (exact-name v1)")
    ap.add_argument("--dry-run", action="store_true", help="count org groups only, no writes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
