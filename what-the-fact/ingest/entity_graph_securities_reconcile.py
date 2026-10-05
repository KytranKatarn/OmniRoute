"""ingest/entity_graph_securities_reconcile.py — Market chain Link 6 (market_reaction_to).

Project #373. The TSX issuer directory (securities.issuers, built by
securities_issuer_ingest) and the corporate contract vendors (shared graph awarded_to
edges, source_id 'awn:%', from gov award_notices) both live in the hub `wtf` DB, so this
reconcile writes DIRECTLY + SET-BASED — no mesh hop.

Fills chain Link 6 (market_reaction_to, Contract -> Market):

  1. SECURITY NODES: one shared.entities organization per MATCHED issuer, slug
     'security-<ticker>', canonical_name '<issuer> (<ticker>)', role 'securities_issuer'
     (ticker + exchange in metadata). A node distinct from the vendor company so the edge
     is Contract(company) -> Market(security), not a self-loop.

  2. MARKET_REACTION_TO EDGES: the contract vendor (a company that won a federal award)
     --market_reaction_to--> its security. STRUCTURAL link (metadata reaction='structural')
     — it asserts "this public company is a federal contractor", NOT a measured price move
     (that's a future Phase-2 enrichment). Match = normalized-exact company name
     (strip Inc/Ltd/Corp...), the 26 verified issuers (BlackBerry/Bombardier/CAE/Telus/...).

  3. Flips shared.chain_link_types.has_data=true for market_reaction_to -> chain 8/8.

Env:  WTF_DATABASE_URL
Run:  python -m ingest.entity_graph_securities_reconcile --dry-run
      python -m ingest.entity_graph_securities_reconcile
"""
import argparse
import logging
import os

from sqlalchemy import create_engine, text

logger = logging.getLogger("securities.entity_graph_reconcile")


def _engine():
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url, pool_pre_ping=True)


def _norm(col):
    """Normalized company name: unaccent -> lower -> drop punctuation -> strip trailing
    corporate suffixes (Inc/Ltd/Corp/...). Identical on both sides of the match."""
    return ("btrim(regexp_replace(regexp_replace(lower(unaccent(" + col + ")), '[^a-z0-9 ]', ' ', 'g'),"
            " '( (incorporated|inc|ltd|limited|limitee|ltee|corporation|corp|company|co|lp|llp|ulc|plc|the))+ *$', ''))")


def _tslug(col):
    """Ticker -> slug fragment: 'RCI.B' -> 'rci-b', 'BB' -> 'bb'."""
    return "btrim(regexp_replace(lower(unaccent(" + col + ")), '[^a-z0-9]+', '-', 'g'), '-')"


def run(dry_run=False):
    totals = {}
    eng = _engine()
    with eng.begin() as conn:
        # Matched (vendor company, issuer) pairs by normalized-exact name.
        conn.execute(text(f"""
            CREATE TEMP TABLE _matched ON COMMIT DROP AS
            WITH vend AS (
                SELECT e.id AS vendor_id, e.canonical_name AS vendor_name, {_norm("e.canonical_name")} AS nm
                FROM shared.entities e
                -- active only: a merged entity keeps its slug/name but its edges moved to the
                -- survivor, so matching it would strand new edges on a dead row (2026-10-05, #3650)
                WHERE e.entity_type = 'organization' AND e.status = 'active'
                  AND EXISTS (SELECT 1 FROM shared.entity_relationships r
                              WHERE r.to_entity_id = e.id
                                AND r.relationship_type = 'awarded_to'
                                AND r.source_id LIKE 'awn:%')
            ),
            iss AS (SELECT ticker, name, exchange, {_norm("name")} AS nm FROM securities.issuers)
            SELECT v.vendor_id, v.vendor_name, i.ticker, i.name AS issuer_name, i.exchange
            FROM vend v JOIN iss i ON i.nm = v.nm AND length(i.nm) >= 3
        """))
        totals["securities"] = int(conn.execute(text(
            "SELECT count(DISTINCT ticker) FROM _matched")).scalar_one())
        totals["edge_candidates"] = int(conn.execute(text(
            "SELECT count(*) FROM _matched")).scalar_one())

        if dry_run:
            logger.info("securities entity-graph reconcile [dry-run]: %s", totals)
            return totals

        # 1) SECURITY NODES — one per matched ticker (the chain "Market" node).
        totals["security_nodes_created"] = conn.execute(text(f"""
            INSERT INTO shared.entities (entity_type, canonical_name, slug, aliases, roles)
            SELECT 'organization', issuer_name || ' (' || ticker || ')',
                   'security-' || {_tslug("ticker")},
                   ARRAY[issuer_name, ticker],
                   jsonb_build_array(jsonb_build_object('type', 'securities_issuer', 'source', 'tsx',
                                                        'ticker', ticker, 'exchange', exchange))
            FROM (SELECT DISTINCT ticker, issuer_name, exchange FROM _matched) m
            ON CONFLICT (slug) DO NOTHING
        """)).rowcount

        # 2) MARKET_REACTION_TO EDGES — vendor(company) -> security. Structural link.
        totals["market_reaction_edges"] = conn.execute(text(f"""
            INSERT INTO shared.entity_relationships
                (from_entity_id, to_entity_id, relationship_type, source_product, source_id, metadata)
            SELECT m.vendor_id, se.id, 'market_reaction_to', 'market-watch',
                   m.vendor_id::text || '|mrt|' || m.ticker,
                   jsonb_build_object('ticker', m.ticker, 'exchange', m.exchange,
                                      'reaction', 'structural', 'match', 'exact_norm')
            FROM _matched m
            JOIN shared.entities se ON se.id = (
                    SELECT coalesce(s0.merged_into, s0.id) FROM shared.entities s0
                    WHERE s0.slug = 'security-' || {_tslug("m.ticker")}
                      AND s0.entity_type = 'organization')
            ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
            DO NOTHING
        """)).rowcount

        # 3) Flip the spine link's has_data flag now that edges exist.
        conn.execute(text(
            "UPDATE shared.chain_link_types SET has_data = true "
            "WHERE relationship_type = 'market_reaction_to'"))

    logger.info("securities entity-graph reconcile done: %s", totals)
    return totals


def main():
    ap = argparse.ArgumentParser(
        description="Securities -> Shared Entity Graph reconcile (Market chain Link 6)")
    ap.add_argument("--dry-run", action="store_true", help="count only, no writes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
