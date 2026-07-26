"""Classify a database exception: skip ONLY when the database is unreachable.

WHY THIS EXISTS (task #5231)
----------------------------
On 2026-07-26 three fleet tests reported "3 skipped" and I read that as passing.
They were not passing — they were not running. The fixture did this::

    except Exception as exc:            # pragma: no cover - no reachable DB
        pytest.skip(f"no database connection: {type(exc).__name__}")

`archie_test` was a schema clone predating migration 463, so seeding a row with
the new `node_role` column raised ``psycopg2.errors.UndefinedColumn``. That is an
``Exception``, so it was caught and downgraded to a skip labelled "no database
connection" — a label that was actively WRONG about its own cause. The database
was perfectly reachable; the schema had drifted.

A skip reads as green. So the suite reported healthy while the code under test
was never exercised, which is the same "status misreports a healthy system"
failure class as the phantom ``backups`` table and the ``FROM backups`` integrity
check that threw every run and swallowed it.

THE DISTINCTION THAT MATTERS
----------------------------
*   **Unreachable database** — a genuinely environment-dependent condition. A
    developer on a laptop with no container running cannot be expected to run
    DB-backed tests. Skipping is honest.
*   **Everything else** — schema drift, a missing column, a missing table, a
    syntax error, a constraint violation. These mean the test found a REAL
    problem. Skipping them hides exactly the defect the test exists to catch.

``psycopg2.OperationalError`` is the connection-layer error class; the schema
errors (``UndefinedColumn``/``UndefinedTable``/``UndefinedFunction``) are all
``ProgrammingError``, a sibling. That makes the boundary crisp rather than a
string match on the message.

FAIL TOWARD LOUD. An exception we cannot classify is re-raised, never skipped.
Guessing "probably environmental" is precisely how the original bug read as green.
"""

from __future__ import annotations

import pytest


def db_or_skip(exc: BaseException) -> None:
    """Skip iff `exc` means the DB is unreachable; otherwise re-raise it.

    Never returns normally — it either raises ``Skipped`` or re-raises ``exc``.
    Call it from a bare ``except Exception as exc:`` around DB work::

        try:
            with get_db_connection() as conn:
                ...
        except pytest.skip.Exception:
            raise                       # an inner skip must pass through
        except Exception as exc:
            db_or_skip(exc)
    """
    # A skip raised deeper in the stack is a decision already made — honour it.
    if isinstance(exc, pytest.skip.Exception):
        raise exc

    try:
        import psycopg2
    except ImportError:  # pragma: no cover - psycopg2 absent entirely
        pytest.skip(f"psycopg2 unavailable: {exc}")
        return

    # OperationalError covers refused connections, auth failures, bad host, and
    # server shutdown — all "the database is not there for me right now".
    if isinstance(exc, psycopg2.OperationalError):
        pytest.skip(f"database unreachable: {type(exc).__name__}: {exc}")

    # ProgrammingError is the schema family. Name it explicitly so the failure
    # message tells the operator what to actually DO, rather than leaving them
    # to rediscover the archie_test drift story from first principles.
    if isinstance(exc, psycopg2.ProgrammingError):
        raise AssertionError(
            f"SCHEMA ERROR, NOT AN ENVIRONMENT PROBLEM: {type(exc).__name__}: {exc}\n"
            "The test database is reachable but its schema does not match the code "
            "under test — most likely archie_test has drifted from archie.\n"
            "conftest auto-reclones on a fingerprint mismatch; if you are seeing this, "
            "force it:  TEST_DB_REBUILD=1 pytest ...\n"
            "This is deliberately a FAILURE. It used to be a skip, which reads as "
            "passing and hid the untested code (task #5231)."
        ) from exc

    # Anything else: unclassified means loud, not silently green.
    raise exc


def import_or_skip(exc: BaseException, what: str) -> None:
    """Skip iff `exc` is a genuine ImportError; otherwise re-raise.

    Module-import guards were written as bare ``except Exception`` too, so a
    NameError or a broken module-level constant inside the imported module
    vanished as "unavailable" instead of failing. Only a real ImportError is
    environmental.
    """
    if isinstance(exc, pytest.skip.Exception):
        raise exc
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        pytest.skip(f"{what} unavailable: {exc}")
    raise exc
