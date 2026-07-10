"""Tests for the Chronicle cross-source entity resolver (slice 08).

Pure unit tests for the normalization/canonical-name helpers, plus a self-cleaning
integration test against the real archie DB (mailbox_imports / mailbox_entities /
chronicle_entity / chronicle_entity_link are live tables). Sentinel owner_id=-777
plus two throwaway mailbox_imports keep this test data unambiguous and easy to
find/clean if a run is interrupted; cleanup runs in a `finally` block.
"""

import services.chronicle_entity_resolver as R


def test_clean_norm():
    assert R._clean("  John   Smith ") == "John Smith"
    assert R._norm("  John   SMITH ") == "john smith"
    assert R._norm(None) == ""


def test_pick_canonical_highest_mention_wins():
    assert (
        R._pick_canonical(
            [
                {"name": "jsmith", "mention_count": 1},
                {"name": "John Smith", "mention_count": 5},
            ]
        )
        == "John Smith"
    )


def test_pick_canonical_tie_breaks_alphabetically():
    assert (
        R._pick_canonical(
            [
                {"name": "Bob", "mention_count": 2},
                {"name": "Alice", "mention_count": 2},
            ]
        )
        == "Alice"
    )


def _insert_import(cur, owner_id, filename):
    cur.execute(
        "INSERT INTO mailbox_imports (owner_id, filename, stored_path, status, email_count, source_kind) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (owner_id, filename, f"/tmp/{filename}", "extracted", 0, "upload"),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def _insert_entity(cur, import_id, name, entity_type, mention_count):
    cur.execute(
        "INSERT INTO mailbox_entities (import_id, name, entity_type, normalized_name, mention_count) "
        "VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (import_id, name, entity_type, R._norm(name), mention_count),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def test_resolve_cross_import_unifies():
    from database import get_db_cursor

    OWNER = -777
    import_a = import_b = None
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            import_a = _insert_import(cur, OWNER, "throwaway-a.mbox")
            import_b = _insert_import(cur, OWNER, "throwaway-b.mbox")

            # import A: person "John Smith" (mc 3), org "Acme" (mc 1)
            _insert_entity(cur, import_a, "John Smith", "person", 3)
            _insert_entity(cur, import_a, "Acme", "org", 1)

            # import B: person "john  smith" (mc 5) [same person, different import + spacing/case],
            # person "Jane Doe" (mc 1)
            _insert_entity(cur, import_b, "john  smith", "person", 5)
            _insert_entity(cur, import_b, "Jane Doe", "person", 1)

        res = R.resolve_entities(OWNER)

        # 3 groups: person/john smith (2 members across A+B), org/acme, person/jane doe
        assert res["groups"] == 3
        assert res["entities_created"] == 3
        assert res["links_created"] == 4

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id, canonical_name, aliases FROM chronicle_entity "
                "WHERE owner_id=%s AND entity_type='person' AND lower(canonical_name)='john smith'",
                (OWNER,),
            )
            row = cur.fetchone()
            assert row is not None
            ent_id = row["id"] if isinstance(row, dict) else row[0]
            canonical_name = row["canonical_name"] if isinstance(row, dict) else row[1]
            aliases = row["aliases"] if isinstance(row, dict) else row[2]

            # canonical = highest mention_count member = import B "john  smith" (mc 5) -> cleaned
            assert canonical_name == "john smith"
            assert "John Smith" in aliases
            assert "john smith" in aliases

            cur.execute(
                "SELECT count(*) AS c FROM chronicle_entity_link WHERE chronicle_entity_id=%s",
                (ent_id,),
            )
            link_row = cur.fetchone()
            link_count = link_row["c"] if isinstance(link_row, dict) else link_row[0]
            assert link_count == 2

        # idempotency: re-running merges/re-links, never duplicates
        res2 = R.resolve_entities(OWNER)
        assert res2["entities_created"] == 0
        assert res2["links_created"] == 0
        assert res2["entities_matched"] == 3
    finally:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM chronicle_entity WHERE owner_id=%s", (OWNER,))
            import_ids = [i for i in (import_a, import_b) if i is not None]
            if import_ids:
                cur.execute(
                    "DELETE FROM mailbox_imports WHERE id = ANY(%s)",
                    (import_ids,),
                )
