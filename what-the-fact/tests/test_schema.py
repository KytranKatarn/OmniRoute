"""Schema migration creates all expected tables with expected columns."""
from sqlalchemy import inspect


def test_all_tables_created(clean_schema, engine):
    insp = inspect(engine)
    tables = set(insp.get_table_names(schema="wtf_test"))
    assert tables == {
        "sources", "articles", "bias_scores",
        "fact_checks", "audit_trail", "failed_ingest",
    }


def test_articles_unique_external_id_per_source(clean_schema, engine):
    """Same external_id allowed across sources, duplicate within source rejected."""
    insp = inspect(engine)
    uqs = insp.get_unique_constraints("articles", schema="wtf_test")
    cols_sets = [tuple(sorted(u["column_names"])) for u in uqs]
    assert ("external_id", "source_id") in cols_sets
