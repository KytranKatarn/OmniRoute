"""entity_mentions_sync.py — Populate shared.entity_mentions from article tagging tables.

Task #3024 — Shared Entity Graph: wire article-entity links so cross-watch matching works.

Sources (in priority order):
  1. wtf.article_mp_tags  → parliament.mps.entity_id  → shared.entity_mentions
  2. (future) article_senator_tags when senator tagging is added

Also seeds political parties as shared.entities (organization) and wires MP → member_of → Party
relationships.

Run:  python -m ingest.shared.entity_mentions_sync   (from what-the-fact/ root)
Env:  WTF_DATABASE_URL
"""

import json
import logging
import os
from typing import Optional

from sqlalchemy import create_engine, text

logger = logging.getLogger("wtf-ingest.entity_mentions_sync")

# ── Political parties ──────────────────────────────────────────────────────────

PARTIES = [
    {
        "canonical_name": "Liberal Party of Canada",
        "slug": "org-liberal-party-of-canada",
        "aliases": ["Liberal", "LPC", "Liberals"],
        "metadata": {"short_name": "Liberal", "colour": "#D71920"},
    },
    {
        "canonical_name": "Conservative Party of Canada",
        "slug": "org-conservative-party-of-canada",
        "aliases": ["Conservative", "CPC", "Conservatives", "Tories"],
        "metadata": {"short_name": "Conservative", "colour": "#1A4782"},
    },
    {
        "canonical_name": "New Democratic Party",
        "slug": "org-new-democratic-party",
        "aliases": ["NDP", "New Democrats"],
        "metadata": {"short_name": "NDP", "colour": "#F37021"},
    },
    {
        "canonical_name": "Bloc Québécois",
        "slug": "org-bloc-quebecois",
        "aliases": ["Bloc", "BQ", "Bloc Québécois"],
        "metadata": {"short_name": "Bloc", "colour": "#00ADEF"},
    },
    {
        "canonical_name": "Green Party of Canada",
        "slug": "org-green-party-of-canada",
        "aliases": ["Green", "GPC", "Greens"],
        "metadata": {"short_name": "Green", "colour": "#3D9B35"},
    },
]

# Maps parliament.mps.party strings → party slug (org- prefix matches entity_graph.py convention)
_PARTY_SLUG_MAP = {
    "Liberal": "org-liberal-party-of-canada",
    "Conservative": "org-conservative-party-of-canada",
    "NDP": "org-new-democratic-party",
    "Bloc": "org-bloc-quebecois",
    "Green": "org-green-party-of-canada",
}


def _get_engine():
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url, pool_pre_ping=True)


# ── Seed political parties ─────────────────────────────────────────────────────

def seed_parties(engine, dry_run: bool = False) -> dict:
    """Upsert political parties into shared.entities (type='organization').

    Returns stats dict with created/updated/noop counts.
    """
    stats = {"created": 0, "updated": 0, "noop": 0}

    with engine.begin() as conn:
        for party in PARTIES:
            row = conn.execute(
                text("SELECT id, aliases FROM shared.entities WHERE slug = :slug"),
                {"slug": party["slug"]},
            ).mappings().fetchone()

            if row is None:
                if dry_run:
                    logger.info("DRY RUN: would create party %s", party["canonical_name"])
                    stats["created"] += 1
                    continue
                conn.execute(
                    text("""
                        INSERT INTO shared.entities
                            (entity_type, canonical_name, slug, aliases, roles, metadata)
                        VALUES
                            ('organization', :cname, :slug,
                             CAST(:aliases AS text[]),
                             CAST(:roles AS JSONB),
                             CAST(:meta AS JSONB))
                    """),
                    {
                        "cname": party["canonical_name"],
                        "slug": party["slug"],
                        "aliases": party["aliases"],
                        "roles": json.dumps([{"type": "political_party"}]),
                        "meta": json.dumps(party["metadata"]),
                    },
                )
                logger.info("Created party entity: %s", party["canonical_name"])
                stats["created"] += 1
            else:
                # Merge any missing aliases
                existing = set(row["aliases"] or [])
                new_aliases = set(party["aliases"])
                if new_aliases - existing:
                    if not dry_run:
                        conn.execute(
                            text("""
                                UPDATE shared.entities
                                SET aliases = CAST(:aliases AS text[]), updated_at = NOW()
                                WHERE slug = :slug
                            """),
                            {
                                "aliases": list(existing | new_aliases),
                                "slug": party["slug"],
                            },
                        )
                    stats["updated"] += 1
                else:
                    stats["noop"] += 1

    logger.info("Parties: created=%d updated=%d noop=%d", stats["created"], stats["updated"], stats["noop"])
    return stats


# ── Seed MP → member_of → Party relationships ─────────────────────────────────

def seed_mp_party_relationships(engine, dry_run: bool = False) -> dict:
    """Wire parliament.mps → shared.entity_relationships (member_of party).

    Each MP with a known party gets a member_of edge to the party entity.
    ON CONFLICT DO UPDATE to refresh the metadata.
    """
    stats = {"created": 0, "noop": 0, "skipped_no_party": 0, "skipped_no_entity": 0}

    with engine.begin() as conn:
        # Build party slug → entity_id lookup
        party_rows = conn.execute(
            text("SELECT id, slug FROM shared.entities WHERE entity_type='organization'")
        ).mappings().all()
        party_id_by_slug = {r["slug"]: r["id"] for r in party_rows}

        mps = conn.execute(
            text("SELECT id, entity_id, party, name FROM parliament.mps WHERE entity_id IS NOT NULL")
        ).mappings().all()

        for mp in mps:
            party_slug = _PARTY_SLUG_MAP.get(mp["party"])
            if not party_slug:
                stats["skipped_no_party"] += 1
                continue
            party_entity_id = party_id_by_slug.get(party_slug)
            if not party_entity_id:
                logger.warning("Party entity not found for slug %s (MP: %s)", party_slug, mp["name"])
                stats["skipped_no_entity"] += 1
                continue

            if dry_run:
                stats["created"] += 1
                continue

            result = conn.execute(
                text("""
                    INSERT INTO shared.entity_relationships
                        (from_entity_id, to_entity_id, relationship_type,
                         source_product, source_id, metadata)
                    VALUES
                        (:from_id, :to_id, 'member_of',
                         'parliament', :source_id, CAST(:meta AS JSONB))
                    ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
                    DO UPDATE SET metadata = EXCLUDED.metadata
                """),
                {
                    "from_id": mp["entity_id"],
                    "to_id": party_entity_id,
                    "source_id": f"mp_{mp['id']}",
                    "meta": json.dumps({"party": mp["party"], "mp_name": mp["name"]}),
                },
            )
            if result.rowcount:
                stats["created"] += 1
            else:
                stats["noop"] += 1

    logger.info(
        "MP→Party edges: created=%d noop=%d skipped_no_party=%d skipped_no_entity=%d",
        stats["created"], stats["noop"], stats["skipped_no_party"], stats["skipped_no_entity"],
    )
    return stats


# ── Sync article_mp_tags → entity_mentions ────────────────────────────────────

def sync_mp_article_mentions(engine, days_back: Optional[int] = None) -> dict:
    """Copy wtf.article_mp_tags rows into shared.entity_mentions.

    Joins article_mp_tags → parliament.mps.entity_id to get the shared entity.
    Uses ON CONFLICT DO NOTHING (unique: entity_id + product + content_type + content_id).

    Args:
        days_back: if set, only process tags created in the last N days.
                   None = full backfill (safe due to ON CONFLICT DO NOTHING).

    Returns stats dict.
    """
    stats = {"synced": 0, "skipped_no_entity": 0}

    date_filter = ""
    params: dict = {}
    if days_back is not None:
        date_filter = "AND a.created_at > NOW() - (:days * INTERVAL '1 day')"
        params["days"] = days_back

    with engine.begin() as conn:
        # Use INSERT ... SELECT for efficiency — avoid Python round-trip on 3k+ rows
        result = conn.execute(
            text(f"""
                INSERT INTO shared.entity_mentions
                    (entity_id, product, content_type, content_id, confidence)
                SELECT
                    m.entity_id,
                    'wtf',
                    'article',
                    a.article_id::text,
                    0.95
                FROM wtf.article_mp_tags a
                JOIN parliament.mps m ON a.mp_id = m.id
                WHERE m.entity_id IS NOT NULL
                {date_filter}
                ON CONFLICT (entity_id, product, content_type, content_id)
                DO NOTHING
            """),
            params,
        )
        stats["synced"] = result.rowcount

        # Count skipped (tags with no entity_id on the MP)
        no_entity = conn.execute(
            text("""
                SELECT count(*) FROM wtf.article_mp_tags a
                JOIN parliament.mps m ON a.mp_id = m.id
                WHERE m.entity_id IS NULL
            """)
        ).scalar()
        stats["skipped_no_entity"] = no_entity or 0

    logger.info(
        "entity_mentions sync: inserted=%d skipped_no_entity=%d",
        stats["synced"], stats["skipped_no_entity"],
    )
    return stats


# ── Entry point ────────────────────────────────────────────────────────────────

def run_entity_mentions_sync(engine=None, days_back: Optional[int] = None) -> dict:
    """Full pipeline: seed parties + wire MP→Party + sync article mentions.

    Designed to be called from run.py or standalone.
    Party seeding is idempotent — safe to call every cycle (fast no-ops after first run).
    """
    if engine is None:
        engine = _get_engine()

    results = {}

    # 1. Ensure party org entities exist
    results["parties"] = seed_parties(engine)

    # 2. Wire MP → member_of → Party relationships
    results["mp_party_edges"] = seed_mp_party_relationships(engine)

    # 3. Sync article MP tags to entity_mentions
    results["article_mentions"] = sync_mp_article_mentions(engine, days_back=days_back)

    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dry_run = "--dry-run" in sys.argv
    days_back = None
    for arg in sys.argv[1:]:
        if arg.startswith("--days="):
            days_back = int(arg.split("=")[1])

    engine = _get_engine()

    print("=== Entity Mentions Sync ===")
    if dry_run:
        print("DRY RUN mode — parties only")
        r = seed_parties(engine, dry_run=True)
        print(f"Parties: {r}")
    else:
        r = run_entity_mentions_sync(engine, days_back=days_back)
        print(f"\nParties:       created={r['parties']['created']} updated={r['parties']['updated']} noop={r['parties']['noop']}")
        print(f"MP→Party edges: created={r['mp_party_edges']['created']} noop={r['mp_party_edges']['noop']}")
        print(f"Article mentions: synced={r['article_mentions']['synced']} skipped_no_entity={r['article_mentions']['skipped_no_entity']}")
