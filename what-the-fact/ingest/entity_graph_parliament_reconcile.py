"""ingest/entity_graph_parliament_reconcile.py — Parliament -> Shared Entity Graph (Link 3: Vote).

Project #373 (Shared Entity Graph). Parliament data lives in the hub `wtf` DB
(`parliament` schema), the SAME DB as the shared graph, so this reconcile writes
DIRECTLY + SET-BASED (like ingest.entity_graph_wtf_reconcile) — no mesh round-trips,
no contention with the HTTP ingest endpoint.

Fills chain Link 3 (cast_vote, MP -> Vote) AND Link 4 (enacted_as, Vote -> Policy):
  3. BILL/POLICY NODES: one shared.entities row per distinct (session, bill_number),
     entity_type='legislation', slug 'bill-<session>-<billnumber>'. The chain "Policy" node.
  4. ENACTED_AS EDGES: division(Vote) --enacted_as--> bill(Policy), the vote `result`
     (Passed/Failed/Tie) carried in metadata — the data is vote-divisions, NOT royal-assent
     enactment status. Flips chain_link_types.has_data=true for enacted_as.

Original Link-3 model:

  1. LEGISLATION NODES: parliament.bills (House divisions — each a recorded vote,
     optionally tied to a bill number) -> shared.entities entity_type='legislation'.
     Deterministic, collision-proof slug 'parl-division-<bills.id>' — we do NOT derive
     the slug from the description (descriptions repeat, e.g. many "Time allocation"
     motions). Requires migration 035 (the 'legislation' entity_type).

  2. CAST_VOTE EDGES: MP --cast_vote--> legislation, set-based from parliament.mp_votes
     JOIN parliament.mps (entity_id, already 343/343 mapped) JOIN the legislation entity
     (by slug). source_id = the mp_votes row id (idempotent); ballot (Yes/No/Paired)
     carried in the edge metadata.

Legislation entities are exact-slug only and MUST never fuzzy-merge (see migration 035 /
dedup_config legislation_fuzzy_enabled=0).

Env:  WTF_DATABASE_URL
Run:  python -m ingest.entity_graph_parliament_reconcile --dry-run
      python -m ingest.entity_graph_parliament_reconcile
"""
import argparse
import logging
import os

from sqlalchemy import create_engine, text

from ingest.shared.entity_graph import _upsert_entity

logger = logging.getLogger("parliament.entity_graph_reconcile")

_LEG_SLUG_PREFIX = "parl-division-"   # + parliament.bills.id  (stable, unique)

# MP --cast_vote--> legislation, set-based. source_id = mp_votes.id => idempotent.
_CAST_VOTE_SQL = text(f"""
    INSERT INTO shared.entity_relationships
        (from_entity_id, to_entity_id, relationship_type, source_product, source_id, metadata)
    SELECT m.entity_id, el.id, 'cast_vote', 'parliament', v.id::text,
           jsonb_build_object('ballot', v.ballot)
    FROM parliament.mp_votes v
    JOIN parliament.mps m    ON m.id = v.mp_id AND m.entity_id IS NOT NULL
    JOIN shared.entities el  ON el.slug = '{_LEG_SLUG_PREFIX}' || v.bill_id::text
                            AND el.entity_type = 'legislation'
    ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
    DO NOTHING
""")

_CAST_VOTE_COUNT_SQL = text(f"""
    SELECT count(*) FROM (
        SELECT m.entity_id, el.id, v.id
        FROM parliament.mp_votes v
        JOIN parliament.mps m    ON m.id = v.mp_id AND m.entity_id IS NOT NULL
        JOIN shared.entities el  ON el.slug = '{_LEG_SLUG_PREFIX}' || v.bill_id::text
                                AND el.entity_type = 'legislation'
    ) x
""")


def _engine():
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url, pool_pre_ping=True)


def _slugify(expr):
    """SQL slugify: unaccent -> lower -> non-alnum runs to '-' -> trim '-'."""
    return f"btrim(regexp_replace(lower(unaccent({expr})), '[^a-z0-9]+', '-', 'g'), '-')"


def _bill_slug(p=""):
    """Stable bill/policy slug 'bill-<session>-<billnumber>'. MUST be byte-identical in
    the node-create (step 3) and the enacted_as edge-join (step 4); pass the column-alias
    prefix (e.g. 'b.') so it works in both contexts."""
    return "'bill-' || " + _slugify(f"{p}session") + " || '-' || " + _slugify(f"{p}bill_number")


def _canonical_name(bill_number, vote_number, session, desc):
    """Human-readable division label. The slug (not the name) is the unique key."""
    desc = (desc or "").strip()
    if desc:
        short = desc if len(desc) <= 140 else desc[:137].rstrip() + "..."
        return f"{bill_number}: {short}" if bill_number else short
    if bill_number:
        return f"{bill_number} (division {vote_number}, {session})"
    return f"Division {vote_number} ({session})"


def run(dry_run=False):
    totals = {"legislation_created": 0, "legislation_updated": 0,
              "legislation_noop": 0, "cast_vote_edges": 0,
              "bills_created": 0, "enacted_as_edges": 0}
    eng = _engine()
    with eng.begin() as conn:
        # 1) LEGISLATION NODES — parliament.bills -> shared.entities (entity_type=legislation)
        bills = conn.execute(text("""
            SELECT id, session, vote_number, bill_number, description_en,
                   vote_date, result, yea_total, nay_total, openparl_url
            FROM parliament.bills
        """)).mappings().fetchall()
        for b in bills:
            slug = f"{_LEG_SLUG_PREFIX}{b['id']}"
            name = _canonical_name(b["bill_number"], b["vote_number"], b["session"], b["description_en"])
            role = {
                "type": "legislation",
                "source": "parliament",
                "session": b["session"],
                "vote_number": b["vote_number"],
                "bill_number": b["bill_number"],
                "vote_date": b["vote_date"].isoformat() if b["vote_date"] else None,
                "result": b["result"],
                "yea_total": b["yea_total"],
                "nay_total": b["nay_total"],
                "openparl_url": b["openparl_url"],
            }
            if dry_run:
                totals["legislation_noop"] += 1
                continue
            _eid, action = _upsert_entity(
                conn, canonical_name=name, slug=slug, entity_type="legislation",
                role=role, raw_name=name, dry_run=False,
            )
            key = ("legislation_created" if action == "created"
                   else "legislation_updated" if action == "updated" else "legislation_noop")
            totals[key] += 1

        # 2) CAST_VOTE EDGES — MP cast_vote legislation (set-based). Needs the nodes above
        #    present, so it runs after the upsert in the SAME transaction.
        if dry_run:
            totals["cast_vote_edges"] = int(conn.execute(_CAST_VOTE_COUNT_SQL).scalar_one())
        else:
            totals["cast_vote_edges"] = conn.execute(_CAST_VOTE_SQL).rowcount

        # 3) BILL / POLICY NODES — one entity per distinct (session, bill_number).
        #    entity_type='legislation' (reuses migration 035; never fuzzy-merges). These are
        #    the chain "Policy" nodes; the parl-division-* legislation nodes are the "Vote"s.
        bill_node_sql = f"""
            INSERT INTO shared.entities (entity_type, canonical_name, slug, aliases, roles)
            SELECT 'legislation',
                   'Bill ' || bill_number || ' (' || session || ')',
                   {_bill_slug("")},
                   ARRAY['Bill ' || bill_number],
                   jsonb_build_array(jsonb_build_object('type', 'bill', 'source', 'parliament',
                                                        'session', session, 'bill_number', bill_number))
            FROM (SELECT DISTINCT session, bill_number FROM parliament.bills
                  WHERE bill_number IS NOT NULL AND btrim(bill_number) <> '') x
            ON CONFLICT (slug) DO NOTHING
        """
        # 4) ENACTED_AS EDGES — division(Vote) -> bill(Policy), chain Link 4 (Vote -> Policy).
        #    source_id = division id (one edge per division => idempotent). The vote `result`
        #    is carried so the explorer can distinguish "voted on" from "passed" — the data is
        #    vote-divisions, NOT enactment status (negatived bills were never actually enacted).
        enacted_sql = f"""
            INSERT INTO shared.entity_relationships
                (from_entity_id, to_entity_id, relationship_type, source_product, source_id, metadata)
            SELECT dv.id, bl.id, 'enacted_as', 'parliament', b.id::text,
                   jsonb_build_object('result', b.result, 'vote_date', b.vote_date,
                                      'bill_number', b.bill_number, 'vote_number', b.vote_number,
                                      'yea_total', b.yea_total, 'nay_total', b.nay_total)
            FROM parliament.bills b
            JOIN shared.entities dv ON dv.slug = '{_LEG_SLUG_PREFIX}' || b.id::text
                                   AND dv.entity_type = 'legislation'
            JOIN shared.entities bl ON bl.slug = {_bill_slug("b.")}
                                   AND bl.entity_type = 'legislation'
            WHERE b.bill_number IS NOT NULL AND btrim(b.bill_number) <> ''
            ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
            DO NOTHING
        """
        if dry_run:
            totals["bills_created"] = int(conn.execute(text("""
                SELECT count(*) FROM (SELECT DISTINCT session, bill_number FROM parliament.bills
                       WHERE bill_number IS NOT NULL AND btrim(bill_number) <> '') x
            """)).scalar_one())
            totals["enacted_as_edges"] = int(conn.execute(text(f"""
                SELECT count(*) FROM parliament.bills b
                JOIN shared.entities dv ON dv.slug = '{_LEG_SLUG_PREFIX}' || b.id::text
                                       AND dv.entity_type = 'legislation'
                WHERE b.bill_number IS NOT NULL AND btrim(b.bill_number) <> ''
            """)).scalar_one())
        else:
            totals["bills_created"] = conn.execute(text(bill_node_sql)).rowcount
            totals["enacted_as_edges"] = conn.execute(text(enacted_sql)).rowcount
            # Flip the spine link's has_data flag now that enacted_as edges exist.
            conn.execute(text(
                "UPDATE shared.chain_link_types SET has_data = true "
                "WHERE relationship_type = 'enacted_as'"))

    logger.info("parliament entity-graph reconcile done%s: %s",
                " [dry-run]" if dry_run else "", totals)
    return totals


def main():
    ap = argparse.ArgumentParser(
        description="Parliament -> Shared Entity Graph reconcile (legislation nodes + cast_vote edges)")
    ap.add_argument("--dry-run", action="store_true", help="count only, no writes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
