"""A schema error must FAIL the suite; only an unreachable DB may skip (#5231).

THE BUG THIS PINS
On 2026-07-26 three fleet tests reported "3 skipped" and that read as passing.
archie_test was a schema clone predating migration 463, so seeding `node_role`
raised UndefinedColumn — an Exception — which a bare `except Exception` turned
into `pytest.skip("no database connection")`. The label was wrong about its own
cause (the DB was reachable) and the skip made untested code look green.

These tests drive the REAL dbguard helpers rather than restating the rule, so
they fail if someone widens the except clause back out.
"""

import psycopg2
import pytest

from tests.dbguard import db_or_skip, import_or_skip


# --------------------------------------------------------------- skip path ---
def test_operational_error_skips():
    """Connection refused / no server: genuinely environmental."""
    with pytest.raises(pytest.skip.Exception) as ei:
        db_or_skip(psycopg2.OperationalError("could not connect to server"))
    assert "unreachable" in str(ei.value).lower()


def test_skip_message_does_not_claim_a_cause_it_did_not_check():
    """The original message asserted 'no database connection' for a schema
    error. Whatever we say must name the real exception type."""
    with pytest.raises(pytest.skip.Exception) as ei:
        db_or_skip(psycopg2.OperationalError("boom"))
    assert "OperationalError" in str(ei.value)


# --------------------------------------------------------------- fail path ---
def test_undefined_column_FAILS_not_skips():
    """THE REGRESSION. This is literally what happened on 2026-07-26."""
    exc = psycopg2.errors.UndefinedColumn('column "node_role" does not exist')
    with pytest.raises(AssertionError) as ei:
        db_or_skip(exc)
    msg = str(ei.value)
    assert "SCHEMA ERROR" in msg
    assert "TEST_DB_REBUILD=1" in msg, "must tell the operator how to fix it"
    assert "5231" in msg


def test_undefined_table_FAILS_not_skips():
    with pytest.raises(AssertionError):
        db_or_skip(psycopg2.errors.UndefinedTable('relation "backups" does not exist'))


def test_undefined_column_is_never_a_skip():
    """Belt and braces: assert the NEGATIVE, since a skip is the silent outcome."""
    try:
        db_or_skip(psycopg2.errors.UndefinedColumn("x"))
    except pytest.skip.Exception:  # pragma: no cover - the bug, if reintroduced
        pytest.fail("schema error was downgraded to a skip — #5231 has regressed")
    except AssertionError:
        pass


def test_unclassified_exception_is_reraised_not_skipped():
    """Fail toward loud: 'probably environmental' is how the bug read green."""
    sentinel = ValueError("something unexpected")
    with pytest.raises(ValueError) as ei:
        db_or_skip(sentinel)
    assert ei.value is sentinel


def test_integrity_error_is_reraised():
    """A constraint violation is a real finding, not an environment problem."""
    with pytest.raises(psycopg2.IntegrityError):
        db_or_skip(psycopg2.IntegrityError("duplicate key"))


# ------------------------------------------------------------- passthrough ---
def test_inner_skip_passes_through_unchanged():
    inner = pytest.skip.Exception("deliberate")
    with pytest.raises(pytest.skip.Exception) as ei:
        db_or_skip(inner)
    assert ei.value is inner


# ----------------------------------------------------------- import guards ---
def test_import_error_skips():
    with pytest.raises(pytest.skip.Exception) as ei:
        import_or_skip(ImportError("no module named x"), "database module")
    assert "database module" in str(ei.value)


def test_non_import_error_in_module_is_reraised():
    """A NameError inside the imported module is a BUG in that module; it used
    to vanish as 'unavailable'."""
    with pytest.raises(NameError):
        import_or_skip(NameError("undefined_constant"), "agent_loop")
