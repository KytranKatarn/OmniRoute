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
    # snapshot the merged entity + its edges/mentions BEFORE repointing, so revert() can
    # fully restore it (v1 snapshotted only the entity row — edges were unrecoverable).
    snap = {
        "entity": conn.execute(text(
            "SELECT row_to_json(e) FROM shared.entities e WHERE id=:m"), {"m": merged}).scalar(),
        "relationships": conn.execute(text(
            "SELECT coalesce(json_agg(row_to_json(r)), '[]'::json) "
            "FROM shared.entity_relationships r WHERE r.from_entity_id=:m OR r.to_entity_id=:m"),
            {"m": merged}).scalar(),
        "mentions": conn.execute(text(
            "SELECT coalesce(json_agg(row_to_json(em)), '[]'::json) "
            "FROM shared.entity_mentions em WHERE em.entity_id=:m"), {"m": merged}).scalar(),
        # entities previously merged INTO `merged`: they are about to be repointed (below) and
        # revert() must be able to point them back.
        "repointed_children": conn.execute(text(
            "SELECT coalesce(json_agg(id), '[]'::json) FROM shared.entities "
            "WHERE merged_into=:m AND status='merged'"), {"m": merged}).scalar(),
    }

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

    # Entities that were already merged INTO `merged` must follow it to the survivor. The site
    # resolves a merged slug exactly ONE hop (chain_routes), so leaving them pointing at an
    # entity that is itself now merged resolves to an empty page. Without this every re-merge of
    # a survivor silently strands its earlier merge children.
    conn.execute(text("UPDATE shared.entities SET merged_into=:s WHERE merged_into=:m AND status='merged'"),
                 {"s": survivor, "m": merged})

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
        ON CONFLICT (entity_id_a, entity_id_b)
        DO UPDATE SET decision='same', similarity=1.0, decided_by=EXCLUDED.decided_by, decided_at=now()
    """), {"a": pa, "b": pb, "by": by + ":" + reason})


def revert(merge_log_id, by="dedup_revert"):
    """Undo a merge from its entity_merge_log snapshot: restore the merged entity, move its
    edges/mentions back off the survivor (re-inserting any that were collision-deleted), mark
    the log reverted, and record a 'distinct' decision so the engine won't re-merge the pair.
    Merges from dedup v1 (entity-only snapshot, no relationships/mentions) restore the entity
    only — edges stay on the survivor (logged in the result as unrecoverable)."""
    eng = _engine()
    with eng.begin() as conn:
        log = conn.execute(text(
            "SELECT survivor_id, merged_id, merged_snapshot, reverted_at "
            "FROM shared.entity_merge_log WHERE id=:id"), {"id": merge_log_id}).mappings().fetchone()
        if log is None:
            raise RuntimeError(f"entity_merge_log {merge_log_id} not found")
        if log["reverted_at"] is not None:
            logger.info("merge_log %s already reverted", merge_log_id)
            return {"reverted": False, "reason": "already_reverted"}

        survivor, merged = log["survivor_id"], log["merged_id"]
        snap = log["merged_snapshot"] or {}
        if isinstance(snap, str):
            snap = json.loads(snap)
        ent = snap.get("entity") or {}
        rels = snap.get("relationships") or []
        mentions = snap.get("mentions") or []

        # 1) restore the merged entity row (still present, status='merged')
        conn.execute(text("""
            UPDATE shared.entities SET status='active', merged_into=NULL,
                   canonical_name=COALESCE(:cn, canonical_name),
                   aliases=CAST(:al AS text[]), roles=CAST(:roles AS jsonb), updated_at=now()
            WHERE id=:m
        """), {"m": merged, "cn": ent.get("canonical_name"),
               "al": ent.get("aliases") or [], "roles": json.dumps(ent.get("roles") or [])})

        # point the merge children that followed `merged` to `survivor` back at `merged`
        children = snap.get("repointed_children") or []
        restored_children = 0
        if children:
            restored_children = conn.execute(text(
                "UPDATE shared.entities SET merged_into=:m "
                "WHERE id = ANY(:ids) AND merged_into=:s AND status='merged'"),
                {"m": merged, "s": survivor, "ids": list(children)}).rowcount

        restored_edges, reinserted_edges = 0, 0
        for r in rels:
            on_from = (r.get("from_entity_id") == merged)
            other = r.get("to_entity_id") if on_from else r.get("from_entity_id")
            col = "from_entity_id" if on_from else "to_entity_id"
            opp = "to_entity_id" if on_from else "from_entity_id"
            res = conn.execute(text(f"""
                UPDATE shared.entity_relationships SET {col}=:m
                WHERE {col}=:s AND {opp}=:other
                  AND relationship_type=:rt AND source_product=:sp
                  AND coalesce(source_id,'')=coalesce(:sid,'')
            """), {"m": merged, "s": survivor, "other": other,
                   "rt": r.get("relationship_type"), "sp": r.get("source_product"),
                   "sid": r.get("source_id")})
            if res.rowcount:
                restored_edges += 1
            else:  # was collision-deleted during merge — re-insert from snapshot
                conn.execute(text("""
                    INSERT INTO shared.entity_relationships
                        (from_entity_id, to_entity_id, relationship_type, source_product, source_id, metadata)
                    VALUES (:fr, :to, :rt, :sp, :sid, CAST(:md AS jsonb))
                    ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
                    DO NOTHING
                """), {"fr": r.get("from_entity_id"), "to": r.get("to_entity_id"),
                       "rt": r.get("relationship_type"), "sp": r.get("source_product"),
                       "sid": r.get("source_id"),
                       "md": json.dumps(r["metadata"]) if r.get("metadata") is not None else None})
                reinserted_edges += 1

        restored_mentions = 0
        for em in mentions:
            res = conn.execute(text("""
                UPDATE shared.entity_mentions SET entity_id=:m
                WHERE entity_id=:s AND product=:p AND content_type=:ct AND content_id=:cid
            """), {"m": merged, "s": survivor, "p": em.get("product"),
                   "ct": em.get("content_type"), "cid": em.get("content_id")})
            if res.rowcount == 0:
                conn.execute(text("""
                    INSERT INTO shared.entity_mentions
                        (entity_id, product, content_type, content_id, mention_context, confidence)
                    VALUES (:m, :p, :ct, :cid, :mc, :cf)
                    ON CONFLICT (entity_id, product, content_type, content_id) DO NOTHING
                """), {"m": merged, "p": em.get("product"), "ct": em.get("content_type"),
                       "cid": em.get("content_id"), "mc": em.get("mention_context"),
                       "cf": em.get("confidence")})
            restored_mentions += 1

        # 2) mark reverted + flip the pair decision to 'distinct' so it won't re-merge
        conn.execute(text(
            "UPDATE shared.entity_merge_log SET reverted_at=now(), reverted_by=:by WHERE id=:id"),
            {"by": by, "id": merge_log_id})
        pa, pb = (survivor, merged) if survivor < merged else (merged, survivor)
        conn.execute(text("""
            INSERT INTO shared.dedup_pair_decisions (entity_id_a, entity_id_b, decision, similarity, decided_by)
            VALUES (:a, :b, 'distinct', 1.0, :by)
            ON CONFLICT (entity_id_a, entity_id_b)
            DO UPDATE SET decision='distinct', decided_by=EXCLUDED.decided_by, decided_at=now()
        """), {"a": pa, "b": pb, "by": by})

    result = {"reverted": True, "merge_log_id": merge_log_id, "survivor": survivor,
              "merged": merged, "restored_edges": restored_edges,
              "reinserted_edges": reinserted_edges, "restored_mentions": restored_mentions,
              "restored_children": restored_children}
    logger.info("revert done: %s", result)
    return result


def list_pending(limit=20):
    """Pending merge_review_queue pairs with names + roles, for a human/agent to decide."""
    eng = _engine()
    with eng.connect() as conn:
        rows = conn.execute(text("""
            SELECT q.id, q.entity_id_a, q.entity_id_b, q.similarity, q.features,
                   a.canonical_name AS a_name, a.slug AS a_slug, a.entity_type AS a_type,
                   b.canonical_name AS b_name, b.slug AS b_slug, b.entity_type AS b_type
            FROM shared.merge_review_queue q
            JOIN shared.entities a ON a.id = q.entity_id_a
            JOIN shared.entities b ON b.id = q.entity_id_b
            WHERE q.status='pending'
            ORDER BY q.similarity DESC, q.id
            LIMIT :lim
        """), {"lim": limit}).mappings().fetchall()
    return [dict(r) for r in rows]


def pending_count():
    """Total pending pairs in the review queue — backlog indicator for the admin UI (#4207)."""
    eng = _engine()
    with eng.connect() as conn:
        return int(conn.execute(text(
            "SELECT count(*) FROM shared.merge_review_queue WHERE status='pending'")).scalar() or 0)


def decide(queue_id, decision, by="manual_review"):
    """Resolve a merge_review_queue pair: 'same' (merge), 'distinct' (reject), or 'defer'.
    On 'same' the most-connected entity survives; the merge reuses _merge (revertable)."""
    if decision not in ("same", "distinct", "defer"):
        raise ValueError("decision must be one of same|distinct|defer")
    eng = _engine()
    with eng.begin() as conn:
        q = conn.execute(text(
            "SELECT entity_id_a, entity_id_b, status FROM shared.merge_review_queue WHERE id=:id"),
            {"id": queue_id}).mappings().fetchone()
        if q is None:
            raise RuntimeError(f"merge_review_queue {queue_id} not found")
        if q["status"] != "pending":
            return {"decided": False, "reason": f"already {q['status']}"}
        a, b = q["entity_id_a"], q["entity_id_b"]

        if decision == "defer":
            conn.execute(text("UPDATE shared.merge_review_queue SET status='deferred', "
                              "decided_at=now(), decided_by=:by WHERE id=:id"),
                         {"by": by, "id": queue_id})
            return {"decided": True, "decision": "defer", "queue_id": queue_id}

        if decision == "distinct":
            pa, pb = (a, b) if a < b else (b, a)
            conn.execute(text("""
                INSERT INTO shared.dedup_pair_decisions (entity_id_a, entity_id_b, decision, similarity, decided_by)
                VALUES (:a, :b, 'distinct', 1.0, :by)
                ON CONFLICT (entity_id_a, entity_id_b)
                DO UPDATE SET decision='distinct', decided_by=EXCLUDED.decided_by, decided_at=now()
            """), {"a": pa, "b": pb, "by": by})
            conn.execute(text("UPDATE shared.merge_review_queue SET status='rejected', "
                              "decided_at=now(), decided_by=:by WHERE id=:id"),
                         {"by": by, "id": queue_id})
            return {"decided": True, "decision": "distinct", "queue_id": queue_id}

        # decision == 'same' -> merge; survivor = most-connected (tie -> lower id)
        st = {eid: conn.execute(text("SELECT status FROM shared.entities WHERE id=:e"),
                                {"e": eid}).scalar() for eid in (a, b)}
        if st.get(a) != "active" or st.get(b) != "active":
            return {"decided": False, "reason": f"entity not active (a={st.get(a)}, b={st.get(b)})"}
        deg = {eid: conn.execute(text(
            "SELECT count(*) FROM shared.entity_relationships WHERE from_entity_id=:e OR to_entity_id=:e"),
            {"e": eid}).scalar() for eid in (a, b)}
        survivor, merged = (a, b) if (deg[a] > deg[b] or (deg[a] == deg[b] and a < b)) else (b, a)
        _merge(conn, survivor, merged, "review_approved", by=by)
        conn.execute(text("UPDATE shared.merge_review_queue SET status='merged', "
                          "decided_at=now(), decided_by=:by WHERE id=:id"),
                     {"by": by, "id": queue_id})
        return {"decided": True, "decision": "same", "survivor": survivor,
                "merged": merged, "queue_id": queue_id}


def fuzzy_candidates(dry_run=False):
    """Trigram-similar ORGANIZATION pairs (similarity in [review_threshold, 1.0)) ->
    merge_review_queue. Non-destructive (review-only, never auto-merged) and deduped vs the
    existing queue + decisions. Uses the idx_entities_name_trgm GIN index via the % operator
    (set_limit tightens the index scan; an explicit similarity filter guarantees the floor).
    Org-only for v1 — person-fuzzy is deferred (cost over ~400k persons + namesake risk).

    Impl note: the trigram operator is a single ``%`` (pg_trgm); SQLAlchemy ``text()``
    auto-escapes it for psycopg2, so writing ``%%`` reaches Postgres literally and errors.
    The candidate predicate (``cand``) is shared verbatim by the dry-run COUNT and the live
    INSERT so the two can never diverge."""
    eng = _engine()
    with eng.begin() as conn:
        rt = float(conn.execute(text(
            "SELECT value FROM shared.dedup_config WHERE key='review_threshold'")).scalar() or 0.78)
        conn.execute(text("SELECT set_limit(:t)"), {"t": rt})
        cand = """
            FROM shared.entities a
            JOIN shared.entities b
              ON a.canonical_name % b.canonical_name AND a.id < b.id
            WHERE a.entity_type='organization' AND b.entity_type='organization'
              AND a.status='active' AND b.status='active'
              AND similarity(a.canonical_name, b.canonical_name) >= :rt
              AND similarity(a.canonical_name, b.canonical_name) < 1.0
              AND NOT EXISTS (SELECT 1 FROM shared.merge_review_queue q
                              WHERE q.entity_id_a=a.id AND q.entity_id_b=b.id)
              AND NOT EXISTS (SELECT 1 FROM shared.dedup_pair_decisions d
                              WHERE d.entity_id_a=a.id AND d.entity_id_b=b.id)
        """
        if dry_run:
            n = conn.execute(text("SELECT count(*) " + cand), {"rt": rt}).scalar()
            logger.info("fuzzy_candidates [dry-run]: %d org candidates (>= %.2f)", n, rt)
            return {"fuzzy_org_candidates": int(n), "threshold": rt, "dry_run": True}
        n = conn.execute(text(
            "INSERT INTO shared.merge_review_queue "
            "(entity_id_a, entity_id_b, similarity, block_key, features, status) "
            "SELECT a.id, b.id, round(similarity(a.canonical_name, b.canonical_name)::numeric, 3), "
            "'fuzzy_org', jsonb_build_object('match','fuzzy_trgm','a_slug',a.slug,'b_slug',b.slug,"
            "'a_name',a.canonical_name,'b_name',b.canonical_name), 'pending' "
            + cand +
            " ON CONFLICT (entity_id_a, entity_id_b) DO NOTHING"), {"rt": rt}).rowcount
    result = {"fuzzy_org_queued": n, "threshold": rt}
    logger.info("fuzzy_candidates done: %s", result)
    return result


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
        # respect prior 'distinct' decisions (e.g. a reverted merge) — never re-merge them
        distinct_pairs = {
            (r[0], r[1]) for r in conn.execute(text(
                "SELECT entity_id_a, entity_id_b FROM shared.dedup_pair_decisions "
                "WHERE decision='distinct'")).fetchall()
        }
        for g in groups:
            ids = g["ids"]
            survivor = ids[0]
            for merged in ids[1:]:
                pair = (survivor, merged) if survivor < merged else (merged, survivor)
                if pair in distinct_pairs:
                    totals["org_skipped_distinct"] = totals.get("org_skipped_distinct", 0) + 1
                    continue
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
    ap.add_argument("--revert", type=int, metavar="MERGE_LOG_ID",
                    help="undo a merge by its entity_merge_log id")
    ap.add_argument("--review-list", type=int, nargs="?", const=20, metavar="N",
                    help="list N pending review pairs (default 20)")
    ap.add_argument("--review-decide", nargs=2, metavar=("QUEUE_ID", "DECISION"),
                    help="resolve a review pair: <queue_id> <same|distinct|defer>")
    ap.add_argument("--fuzzy", action="store_true",
                    help="generate fuzzy/trigram ORG candidates -> review queue (honors --dry-run)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.fuzzy:
        print(fuzzy_candidates(dry_run=args.dry_run))
    elif args.revert:
        revert(args.revert)
    elif args.review_list is not None:
        import json as _json
        print(_json.dumps(list_pending(args.review_list), default=str, indent=2))
    elif args.review_decide:
        print(decide(int(args.review_decide[0]), args.review_decide[1]))
    else:
        run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
