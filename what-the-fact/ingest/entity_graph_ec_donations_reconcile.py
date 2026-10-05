"""ingest/entity_graph_ec_donations_reconcile.py — Elections Canada -> Shared Entity Graph (Link 1: Money).

Project #373. EC contribution data lives in the hub `wtf` DB (parliament.ec_contributions),
the SAME DB as the shared graph -> direct + set-based reconcile (no mesh hop). The hub
Postgres (128GB) does the heavy 4.8M-row aggregation; this module just issues the SQL.

Fills chain Link 1 (donated_to, Money -> MP). Owner decisions (2026-06-15):
  - Recipients = PARTIES: donor(person) --donated_to--> party(organization). 78% of EC
    money goes to parties, and MPs already link to parties via member_of, so
    Money -> Party -> MP is traversable. (Direct donor->candidate edges deferred — only
    0.7% of rows, and free-text candidate->MP matching is fuzzy.)
  - Donors materialize only at >= $200 aggregate CAD (shared.dedup_config.donor_min_aggregate).
    All EC contributors are 'Individuals' -> entity_type='person'.

Model (all set-based):
  1. donor person entities, slug 'donor-<slugify(name)>' — EC-namespaced so they never
     collide/merge with canonical persons (cross-linking is the dedup engine's job, #3792).
  2. party org entities — matched to existing by canonical_name; long-tail parties created.
  3. donated_to edges donor->party, aggregated per (donor, party): total CAD + contribution
     count + date range in metadata; source_id = '<donor_slug>|<party_slug>' (idempotent).

Requires the `unaccent` extension (installed). No migration (person/organization types and
the donated_to catalog row already exist).

Env:  WTF_DATABASE_URL
Run:  python -m ingest.entity_graph_ec_donations_reconcile --dry-run
      python -m ingest.entity_graph_ec_donations_reconcile
"""
import argparse
import logging
import os

from sqlalchemy import create_engine, text

logger = logging.getLogger("ec.entity_graph_reconcile")

_DEFAULT_MIN_AGG = 200  # CAD; the live value comes from dedup_config.donor_min_aggregate

# Reorder EC "Last, First" -> "First Last" for a human display name.
_DISPLAY = (
    "CASE WHEN position(',' in contributor_name) > 0 "
    "THEN btrim(split_part(contributor_name, ',', 2)) || ' ' || btrim(split_part(contributor_name, ',', 1)) "
    "ELSE contributor_name END"
)


def _slugify(expr):
    """SQL slugify: unaccent -> lower -> non-alnum runs to '-' -> trim '-'."""
    return f"btrim(regexp_replace(lower(unaccent({expr})), '[^a-z0-9]+', '-', 'g'), '-')"


def _engine():
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url, pool_pre_ping=True)


def run(dry_run=False):
    totals = {}
    eng = _engine()
    disp = _DISPLAY
    donor_slug = "'donor-' || " + _slugify(disp)
    # recipient "Family, Given" -> "Given Family" -> slug, matched to parliament.mps.slug
    recip = ("CASE WHEN position(',' in recipient_name) > 0 "
             "THEN btrim(split_part(recipient_name, ',', 2)) || ' ' || "
             "btrim(split_part(recipient_name, ',', 1)) ELSE recipient_name END")
    mp_slug = _slugify(recip)
    with eng.begin() as conn:
        row = conn.execute(text(
            "SELECT value FROM shared.dedup_config WHERE key='donor_min_aggregate'")).fetchone()
        min_agg = float(row[0]) if row else _DEFAULT_MIN_AGG
        totals["min_aggregate_cad"] = min_agg

        # 1) per-(donor, party) aggregate (the heavy 4.8M-row scan, done once)
        conn.execute(text(f"""
            CREATE TEMP TABLE _dp ON COMMIT DROP AS
            SELECT {donor_slug} AS donor_slug,
                   max({disp})  AS display,
                   party,
                   sum(monetary_amount + coalesce(non_monetary_amount, 0)) AS total,
                   count(*)     AS n,
                   min(contribution_date) AS first_d,
                   max(contribution_date) AS last_d
            FROM parliament.ec_contributions
            WHERE party IS NOT NULL
            GROUP BY 1, party
        """))
        conn.execute(text("DELETE FROM _dp WHERE donor_slug = 'donor-' OR donor_slug IS NULL"))

        # 2) donors clearing the aggregate threshold (grand total across all parties)
        conn.execute(text("""
            CREATE TEMP TABLE _donor ON COMMIT DROP AS
            SELECT donor_slug, max(display) AS display, sum(total) AS grand
            FROM _dp GROUP BY donor_slug HAVING sum(total) >= :min_agg
        """), {"min_agg": min_agg})

        totals["donors_ge_threshold"] = int(
            conn.execute(text("SELECT count(*) FROM _donor")).scalar_one())
        totals["edge_candidates"] = int(conn.execute(text(
            "SELECT count(*) FROM _dp d JOIN _donor x ON x.donor_slug = d.donor_slug")).scalar_one())

        # 2b) direct donor -> candidate(MP) edge candidates (Link 1 direct attribution):
        # 'Candidates' contributions whose recipient slug matches an MP and whose donor is
        # already materialized (>= $200, status active).
        totals["donor_mp_candidates"] = int(conn.execute(text(f"""
            SELECT count(*) FROM (
                SELECT {donor_slug} AS donor_slug, {mp_slug} AS mp_slug
                FROM parliament.ec_contributions WHERE political_entity = 'Candidates'
                GROUP BY 1, 2
            ) a
            JOIN parliament.mps m ON m.slug = a.mp_slug AND m.entity_id IS NOT NULL
            JOIN shared.entities de ON de.slug = a.donor_slug AND de.status = 'active'
        """)).scalar_one())

        # 2c) fuzzy+riding donor -> MP recall recovery (#373): 'Candidates' recipients that
        # did NOT exact-match an MP slug but DO match the MP of the SAME riding at
        # name-similarity >= 0.60. One current MP per riding makes this safe — it recovers
        # name variations (middle initials, nicknames, added surnames) without the namesake
        # false-positives that name-only fuzzy would create against ~3k defeated candidates.
        totals["donor_mp_fuzzy_candidates"] = int(conn.execute(text(f"""
            SELECT count(DISTINCT m.entity_id) FROM (
                SELECT DISTINCT {mp_slug} AS recip_slug, {recip} AS recip_name,
                       {_slugify('electoral_district')} AS ed_slug
                FROM parliament.ec_contributions WHERE political_entity = 'Candidates'
            ) a
            JOIN parliament.mps m ON m.entity_id IS NOT NULL
             AND {_slugify('m.riding_name')} = a.ed_slug
             AND similarity(lower(unaccent(a.recip_name)), lower(unaccent(m.name))) >= 0.60
            WHERE NOT EXISTS (SELECT 1 FROM parliament.mps me
                              WHERE me.slug = a.recip_slug AND me.entity_id IS NOT NULL)
        """)).scalar_one())

        if dry_run:
            logger.info("EC donations reconcile [dry-run]: %s", totals)
            return totals

        # 3) donor person entities
        totals["donor_entities_created"] = conn.execute(text("""
            INSERT INTO shared.entities (entity_type, canonical_name, slug, aliases, roles)
            SELECT 'person', display, donor_slug, ARRAY[display],
                   jsonb_build_array(jsonb_build_object('type', 'donor', 'source', 'elections_canada'))
            FROM _donor
            ON CONFLICT (slug) DO NOTHING
        """)).rowcount

        # 4) party org entities — create any EC party missing an entity (match by name)
        totals["party_entities_created"] = conn.execute(text(f"""
            INSERT INTO shared.entities (entity_type, canonical_name, slug, aliases, roles)
            SELECT 'organization', p.party, 'party-' || {_slugify('p.party')}, ARRAY[p.party],
                   jsonb_build_array(jsonb_build_object('type', 'political_party', 'source', 'elections_canada'))
            FROM (SELECT DISTINCT party FROM _dp) p
            WHERE NOT EXISTS (
                SELECT 1 FROM shared.entities e
                WHERE lower(e.canonical_name) = lower(p.party) AND e.entity_type = 'organization')
            ON CONFLICT (slug) DO NOTHING
        """)).rowcount

        # 5) donated_to edges donor -> party (aggregated, idempotent)
        totals["donated_to_edges"] = conn.execute(text(f"""
            INSERT INTO shared.entity_relationships
                (from_entity_id, to_entity_id, relationship_type, source_product, source_id, metadata)
            SELECT de.id, pe.id, 'donated_to', 'elections_canada',
                   d.donor_slug || '|' || {_slugify('d.party')},
                   jsonb_build_object('total_cad', round(d.total, 2), 'contributions', d.n,
                                      'first', d.first_d, 'last', d.last_d)
            FROM _dp d
            JOIN _donor x          ON x.donor_slug = d.donor_slug
            JOIN shared.entities de ON de.slug = d.donor_slug AND de.status = 'active'
            JOIN shared.entities pe ON lower(pe.canonical_name) = lower(d.party)
                                   AND pe.entity_type = 'organization'
                                   AND pe.status = 'active'
            ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
            DO NOTHING
        """)).rowcount

        # 6) direct donor -> candidate(MP) edges (Link 1 direct attribution). Recipient slug
        # matched to parliament.mps.slug; source_id namespaced 'mp-' so it never collides with
        # the donor->party edges above. Only materialized (>= $200, active) donors attach.
        totals["donor_mp_edges"] = conn.execute(text(f"""
            INSERT INTO shared.entity_relationships
                (from_entity_id, to_entity_id, relationship_type, source_product, source_id, metadata)
            SELECT de.id, m.entity_id, 'donated_to', 'elections_canada',
                   a.donor_slug || '|mp-' || a.mp_slug,
                   jsonb_build_object('total_cad', round(a.total, 2), 'contributions', a.n,
                                      'recipient', 'candidate', 'first', a.first_d, 'last', a.last_d)
            FROM (
                SELECT {donor_slug} AS donor_slug, {mp_slug} AS mp_slug,
                       sum(monetary_amount + coalesce(non_monetary_amount, 0)) AS total,
                       count(*) AS n, min(contribution_date) AS first_d, max(contribution_date) AS last_d
                FROM parliament.ec_contributions WHERE political_entity = 'Candidates'
                GROUP BY 1, 2
            ) a
            JOIN parliament.mps m ON m.slug = a.mp_slug AND m.entity_id IS NOT NULL
            JOIN shared.entities de ON de.slug = a.donor_slug AND de.status = 'active'
            ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
            DO NOTHING
        """)).rowcount

        # 7) fuzzy+riding donor -> MP edges (#373 recall recovery). 'Candidates' recipients
        # that did NOT exact-match an MP slug, matched to the MP of the SAME riding at
        # name-similarity >= 0.60 (one current MP per riding -> safe; recovers middle
        # initials, nicknames, added surnames). source_id namespaced '|mpf-' so it never
        # collides with the exact '|mp-' edges; metadata tags match='fuzzy_riding' + the
        # similarity score (audit + revertable). Materialized (>= $200, active) donors only.
        totals["donor_mp_fuzzy_edges"] = conn.execute(text(f"""
            INSERT INTO shared.entity_relationships
                (from_entity_id, to_entity_id, relationship_type, source_product, source_id, metadata)
            SELECT de.id, agg.m_entity_id, 'donated_to', 'elections_canada',
                   agg.donor_slug || '|mpf-' || agg.m_slug,
                   jsonb_build_object('total_cad', round(agg.total, 2), 'contributions', agg.n,
                                      'recipient', 'candidate', 'match', 'fuzzy_riding',
                                      'similarity', round(agg.max_sim::numeric, 3),
                                      'first', agg.first_d, 'last', agg.last_d)
            FROM (
                SELECT z.donor_slug, z.m_entity_id, z.m_slug,
                       sum(z.total) AS total, sum(z.n) AS n, max(z.sim) AS max_sim,
                       min(z.first_d) AS first_d, max(z.last_d) AS last_d
                FROM (
                    SELECT a.donor_slug, a.total, a.n, a.first_d, a.last_d,
                           res.entity_id AS m_entity_id, res.slug AS m_slug, res.sim
                    FROM (
                        SELECT {donor_slug} AS donor_slug, {mp_slug} AS recip_slug,
                               {recip} AS recip_name, {_slugify('electoral_district')} AS ed_slug,
                               sum(monetary_amount + coalesce(non_monetary_amount, 0)) AS total,
                               count(*) AS n, min(contribution_date) AS first_d,
                               max(contribution_date) AS last_d
                        FROM parliament.ec_contributions WHERE political_entity = 'Candidates'
                        GROUP BY 1, 2, 3, 4
                    ) a
                    JOIN LATERAL (
                        SELECT m.entity_id, m.slug,
                               similarity(lower(unaccent(a.recip_name)), lower(unaccent(m.name))) AS sim
                        FROM parliament.mps m
                        WHERE m.entity_id IS NOT NULL
                          AND {_slugify('m.riding_name')} = a.ed_slug
                          AND similarity(lower(unaccent(a.recip_name)), lower(unaccent(m.name))) >= 0.60
                        ORDER BY sim DESC LIMIT 1
                    ) res ON true
                    WHERE NOT EXISTS (SELECT 1 FROM parliament.mps me
                                      WHERE me.slug = a.recip_slug AND me.entity_id IS NOT NULL)
                ) z
                GROUP BY z.donor_slug, z.m_entity_id, z.m_slug
            ) agg
            JOIN shared.entities de ON de.slug = agg.donor_slug AND de.status = 'active'
            ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
            DO NOTHING
        """)).rowcount

    logger.info("EC donations reconcile done: %s", totals)
    return totals


def main():
    ap = argparse.ArgumentParser(
        description="Elections Canada -> Shared Entity Graph reconcile (donor->party donated_to edges)")
    ap.add_argument("--dry-run", action="store_true", help="aggregate + count only, no writes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
