"""Tests for services/omniroute_telemetry.

Unlike test_dispatch_queue_reaper, these are FUNCTIONAL: the OmniRoute side is a
real temporary sqlite database (so the schema walk, the cursor query and the
watermark are genuinely exercised), and the Postgres side is a recording fake, so
nothing depends on the empty `archie_test` DB that makes content assertions
vacuous in this repo.

What is pinned here is what a future edit is most likely to break silently:

  * dry_run defaults True — an exploratory import must not mutate the token ledger
  * worker_type='contract' — the ONLY thing keeping carbon n/a for cloud rows
  * created_at comes from the CALL's timestamp, never now() — otherwise a backfill
    lands as one fake spike instead of in its real historical buckets
  * the watermark advances and a re-run imports NOTHING (no double-counting)
  * a changed third-party schema fails LOUD and writes nothing
  * per-interface attribution is never inferred from requested_model
"""

import importlib
import json
import os
import sqlite3
import tempfile

import pytest

MOD = "services.omniroute_telemetry"


# ---------------------------------------------------------------- fake postgres


class FakeCursor:
    """Records executed statements; answers the watermark SELECT from a dict.

    Also models the advisory lock: `store['lock_taken']` makes the probe return
    False, which is how the contention path is exercised without two real DB
    sessions.
    """

    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        self._sql, self._params = sql, params
        s = " ".join(sql.split())
        if "pg_try_advisory_xact_lock" in s:
            self.store.setdefault("lock_probes", []).append(params)
            self._row = {"got": not self.store.get("lock_taken")}
        elif s.startswith("SELECT value FROM platform_settings"):
            self._row = {"value": self.store.get("watermark")}
        elif "INSERT INTO task_execution_log" in s:
            # Record the RAW sql, not the flattened `s`: the statement carries a
            # `--` comment, and flattening it to one line makes per-line comment
            # stripping eat the whole statement.
            self.store.setdefault("inserts", []).append((sql, params))
            self._row = None
        elif "INSERT INTO platform_settings" in s:
            self.store["watermark"] = params[1]
            self._row = None
        else:
            self._row = None

    def fetchone(self):
        return self._row


class FakeCtx:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return (None, FakeCursor(self.store))

    def __exit__(self, *a):
        return False


@pytest.fixture()
def tel():
    return importlib.import_module(MOD)


@pytest.fixture()
def omni_db():
    """A real sqlite file shaped like OmniRoute's call_logs."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE call_logs (id TEXT, timestamp TEXT, model TEXT, provider TEXT, "
        "status INTEGER, tokens_in INTEGER, tokens_out INTEGER, duration INTEGER, "
        "requested_model TEXT, api_key_name TEXT, tokens_cache_read INTEGER, "
        "tokens_reasoning INTEGER)"
    )
    rows = [
        # a real call
        (
            "1789423348494-aaa",
            "2026-09-14T22:02:30.763Z",
            "big-pickle",
            "opencode",
            200,
            47176,
            90,
            2367,
            "opencode/big-pickle",
            "archie-platform",
            100,
            0,
        ),
        # a 0-token refusal — must be skipped, it is not inference
        (
            "1789423350000-bbb",
            "2026-09-14T22:02:33.000Z",
            "big-pickle",
            "opencode",
            429,
            0,
            0,
            12,
            "opencode/big-pickle",
            "archie-platform",
            0,
            0,
        ),
        # an errored call that still burned prompt tokens — must be kept, success=False
        (
            "1789423352735-ccc",
            "2026-09-14T22:02:35.120Z",
            "coder-large",
            "horde",
            500,
            1200,
            0,
            900,
            "horde/coder-large",
            "archie-platform",
            0,
            0,
        ),
    ]
    con.executemany("INSERT INTO call_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    yield path
    os.unlink(path)


def _run(tel, monkeypatch, db, store, **kw):
    monkeypatch.setattr(tel, "OMNIROUTE_DB", db)
    monkeypatch.setattr("database.get_db_cursor", lambda *a, **k: FakeCtx(store), raising=False)
    return tel.collect(**kw)


# ------------------------------------------------------------------ the guards


def test_dry_run_defaults_to_true(tel):
    """An accidental call must COUNT, never write. The signature is the guard."""
    import inspect

    assert inspect.signature(tel.collect).parameters["dry_run"].default is True


def test_dry_run_writes_nothing(tel, monkeypatch, omni_db):
    store = {}
    res = _run(tel, monkeypatch, omni_db, store)
    assert res["ok"] and res["scanned"] == 3
    assert store.get("inserts") is None, "dry run must not INSERT"
    assert store.get("watermark") is None, "dry run must not advance the watermark"


def test_zero_token_rows_are_skipped(tel, monkeypatch, omni_db):
    """A 0-token row is a refusal, not inference — counting it measures the gate."""
    store = {}
    res = _run(tel, monkeypatch, omni_db, store, dry_run=False)
    assert res["written"] == 2
    assert res["skipped_zero"] == 1


def test_worker_type_contract_keeps_carbon_n_a(tel, monkeypatch, omni_db):
    """The load-bearing invariant: contract => carbon NULL.

    Carbon is watts-for-the-model x duration x the CANADA grid factor — a
    LOCAL-cluster methodology. These calls ran on someone else's GPU in an unknown
    country. If worker_type ever stops being 'contract', the carbon path starts
    emitting a confident number about hardware we do not own.

    Asserted against the real co2_g_sql(), not a copy of the rule.
    """
    from services.carbon_footprint_service import co2_g_sql

    assert "WHEN worker_type = 'contract' THEN NULL" in " ".join(co2_g_sql().split())

    store = {}
    _run(tel, monkeypatch, omni_db, store, dry_run=False)
    for sql, _ in store["inserts"]:
        # ⚠️ Strip SQL comments FIRST. The INSERT carries a comment that contains
        # the words worker_type='contract', so a bare `"'contract'" in sql` matches
        # the COMMENT and passes even when the VALUES clause says 'ai'. That exact
        # vacuity was caught by mutation-checking this test at authoring time.
        body = " ".join(line.split("--")[0] for line in sql.splitlines())
        body = " ".join(body.split())
        assert "VALUES (%s, 'contract', 'code'" in body, (
            "the INSERT's VALUES clause must hard-code worker_type='contract' — "
            "it is what keeps carbon n/a for cloud rows"
        )


def test_created_at_is_the_call_timestamp_not_now(tel, monkeypatch, omni_db):
    """A backfill must land in its real historical buckets, not spike at import.

    If created_at were now(), every imported call would pile into the current hour
    on the Token Economy panel — which is precisely the distortion that would make
    a backfill unsafe and force us to throw the history away.
    """
    store = {}
    _run(tel, monkeypatch, omni_db, store, dry_run=False)
    sql, params = store["inserts"][0]
    assert "now()" not in sql.lower(), "created_at must be bound, never now()"
    assert params[-1] == "2026-09-14 22:02:30.763"


def test_tokens_and_success_are_carried_faithfully(tel, monkeypatch, omni_db):
    store = {}
    _run(tel, monkeypatch, omni_db, store, dry_run=False)
    first = store["inserts"][0][1]
    assert first[3] == 47176 and first[4] == 90  # prompt / completion
    assert first[5] == 47176 + 90  # tokens_used is the sum, not re-derived
    assert first[7] is True  # status 200
    # the 500 row is kept (it burned tokens) but is NOT a success
    assert store["inserts"][1][1][7] is False


def test_watermark_advances_and_a_rerun_imports_nothing(tel, monkeypatch, omni_db):
    """Idempotency is the whole defence against double-counting the ledger."""
    store = {}
    first = _run(tel, monkeypatch, omni_db, store, dry_run=False)
    assert first["written"] == 2
    assert store["watermark"] == "2026-09-14T22:02:35.120Z|1789423352735-ccc"

    second = _run(tel, monkeypatch, omni_db, store, dry_run=False)
    assert second["ok"] and second["scanned"] == 0 and second["written"] == 0
    assert len(store["inserts"]) == 2, "a re-run must not re-import anything"


def test_max_batch_bounds_a_pass_and_the_next_pass_continues(tel, monkeypatch, omni_db):
    store = {}
    r1 = _run(tel, monkeypatch, omni_db, store, dry_run=False, max_batch=1)
    assert r1["scanned"] == 1 and r1["written"] == 1
    r2 = _run(tel, monkeypatch, omni_db, store, dry_run=False, max_batch=1)
    assert r2["scanned"] == 1  # the 0-token row
    r3 = _run(tel, monkeypatch, omni_db, store, dry_run=False, max_batch=1)
    assert r3["scanned"] == 1 and r3["written"] == 1
    assert len(store["inserts"]) == 2


def test_watermark_read_and_write_share_one_locked_transaction(tel, monkeypatch, omni_db):
    """The race F.O.R.G.E. flagged on PR #3339.

    Reading the watermark in one transaction and writing it in another leaves a
    window where two collectors read the same mark and import the same calls twice.
    A double-counted token ledger is the one outcome this service must never
    produce, so the lock is taken BEFORE the watermark is read, in the same
    transaction that later writes it.
    """
    store = {}
    _run(tel, monkeypatch, omni_db, store, dry_run=False)
    probes = store.get("lock_probes") or []
    assert probes, "the advisory lock must be taken before any watermark work"
    assert probes[0][0] == tel.ADVISORY_LOCK_KEY

    import inspect

    src = inspect.getsource(tel.collect)
    lock_at = src.index("pg_try_advisory_xact_lock")
    read_at = src.index("_read_watermark")
    write_at = src.index("INSERT INTO platform_settings")
    assert lock_at < read_at < write_at, (
        "order is load-bearing: lock, then read the watermark, then write it — "
        "all inside the one `with get_db_cursor(commit=True)` block"
    )
    # exactly one transaction opened
    assert src.count("get_db_cursor(") == 1, "a second transaction reintroduces the race the lock exists to close"


def test_a_second_collector_skips_instead_of_double_importing(tel, monkeypatch, omni_db):
    """Contention is not an error — it is a free skip, because of the watermark."""
    store = {"lock_taken": True}
    res = _run(tel, monkeypatch, omni_db, store, dry_run=False)
    assert res["ok"] is True, "losing the lock race is normal, not a failure"
    assert res["skipped_locked"] is True
    assert res["written"] == 0
    assert store.get("inserts") is None, "the loser must import nothing"
    assert store.get("watermark") is None, "and must not move the watermark"


def test_meta_is_a_bound_parameter_never_interpolated(tel, monkeypatch, omni_db):
    """Disproves the 'SQL injection via json.dumps(meta)' finding on PR #3339.

    request_metadata is passed as a bound parameter, so psycopg2 adapts it
    server-side and its content cannot alter the statement. The check that matters
    is structural: the SQL text contains no interpolation of the payload, and the
    JSON travels in the params tuple.
    """
    store = {}
    _run(tel, monkeypatch, omni_db, store, dry_run=False)
    sql, params = store["inserts"][0]
    assert "%s" in sql
    for bad in (
        "json.dumps",
        "format(",
        ".join(",
        "+ meta",
        'f"',
        "%(",
    ):
        assert bad not in sql, f"payload must never be interpolated into SQL ({bad})"
    meta_raw = params[8]
    assert isinstance(meta_raw, str) and meta_raw.startswith("{")
    assert json.loads(meta_raw)["source"] == "omniroute_call_logs"


def test_schema_change_fails_loud_and_writes_nothing(tel, monkeypatch, omni_db):
    """A third-party schema CAN change under an image bump.

    The failure mode to avoid is logging zeros forever while looking healthy.
    """
    con = sqlite3.connect(omni_db)
    con.execute("ALTER TABLE call_logs RENAME COLUMN tokens_in TO input_tokens")
    con.commit()
    con.close()

    store = {}
    res = _run(tel, monkeypatch, omni_db, store, dry_run=False)
    assert res["ok"] is False
    assert "schema changed" in res["error"] and "tokens_in" in res["error"]
    assert store.get("inserts") is None


def test_missing_db_is_handled_not_raised(tel, monkeypatch):
    store = {}
    res = _run(tel, monkeypatch, "/nonexistent/storage.sqlite", store)
    assert res["ok"] is False and "not readable" in res["error"]


def test_db_failure_is_fail_safe(tel, monkeypatch, omni_db):
    monkeypatch.setattr(tel, "OMNIROUTE_DB", omni_db)

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("database.get_db_cursor", _boom, raising=False)
    res = tel.collect(dry_run=False)
    assert res["ok"] is False and res["written"] == 0 and "db down" in res["error"]


# ------------------------------------------------- the attribution discipline


def test_interface_is_unknown_for_the_shared_key(tel):
    """Every live row carries 'archie-platform'. Claiming a lane would be a lie."""
    assert tel._interface_from("archie-platform") == "unknown"
    assert tel._interface_from(None) == "unknown"
    assert tel._interface_from("") == "unknown"


def test_per_lane_keys_resolve_once_they_exist(tel):
    assert tel._interface_from("codex-lane") == "codex"
    assert tel._interface_from("opencode-lane") == "opencode"
    assert tel._interface_from("host-cli") == "host-cli"


def test_interface_is_never_inferred_from_requested_model(tel):
    """requested_model's prefix is the UPSTREAM PROVIDER, not the caller.

    'opencode/big-pickle' means OmniRoute routed to opencode.ai's gateway — the
    same list holds horde/, cloudflare-playground/ and uncloseai/. Reading it as
    the lane would produce confident, wrong per-interface numbers. Pinned by
    signature: the function cannot even see requested_model.
    """
    import inspect

    params = list(inspect.signature(tel._interface_from).parameters)
    assert params == ["api_key_name"], (
        "_interface_from must not take requested_model — it is the upstream "
        "provider, and taking it invites inferring the lane from it"
    )


def test_metadata_labels_requested_model_as_upstream(tel, monkeypatch, omni_db):
    store = {}
    _run(tel, monkeypatch, omni_db, store, dry_run=False)
    meta = json.loads(store["inserts"][0][1][8])
    assert meta["upstream_provider"] == "opencode"
    assert meta["requested_model"] == "opencode/big-pickle"
    assert meta["interface"] == "unknown"
    assert meta["omniroute_id"] == "1789423348494-aaa"


def test_bad_timestamp_is_skipped_not_inserted(tel, monkeypatch, omni_db):
    con = sqlite3.connect(omni_db)
    con.execute(
        "INSERT INTO call_logs VALUES ('1789423399999-ddd', NULL, 'm', 'p', 200, 5, 5, 1, 'p/m', 'archie-platform', 0, 0)"
    )
    con.commit()
    con.close()
    store = {}
    res = _run(tel, monkeypatch, omni_db, store, dry_run=False)
    assert res["skipped_bad_ts"] == 1
    assert res["written"] == 2


def test_pg_timestamp_conversion(tel):
    assert tel._pg_timestamp("2026-09-14T22:02:35.120Z") == "2026-09-14 22:02:35.120"
    for bad in (None, "", "x", 12345):
        assert tel._pg_timestamp(bad) is None
