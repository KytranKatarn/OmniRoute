from sqlalchemy import text


def test_entity_schema_seeds_mp(entity_schema, engine):
    """The entity_schema fixture builds shared_test/parliament_test and seeds an MP
    with two article mentions. Smoke-tests that the whole fixture applies cleanly."""
    with engine.connect() as c:
        n = c.execute(
            text(
                "SELECT count(*) FROM shared_test.entity_mentions "
                "WHERE entity_id=:e AND content_type='article'"
            ),
            {"e": entity_schema["mp_entity_id"]},
        ).scalar()
    assert n == 2


def test_entity_schema_links_mp_to_parliament(entity_schema, engine):
    """parliament_test.mps.entity_id back-link is populated (mirrors prod 343/343)."""
    with engine.connect() as c:
        eid = c.execute(
            text("SELECT entity_id FROM parliament_test.mps WHERE id=:m"),
            {"m": entity_schema["mp_id"]},
        ).scalar()
    assert eid == entity_schema["mp_entity_id"]
