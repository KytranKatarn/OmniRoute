"""Regression (post-#3905): the internal handover board must index rows by COLUMN NAME.

`get_db_cursor` defaults to `cursor_factory=RealDictCursor`, so `cur.fetchall()`
yields DICTS. `api_internal_handover_list` indexed them positionally (`r[0]`..`r[9]`),
which raises `KeyError: 0` and 500s BOTH internal handover routes:

  * `GET  /api/internal/handover` — directly, and
  * `POST /api/internal/handover` — through its trailing
    `return api_internal_handover_list()`.

Observed live after #3905 was deployed (2026-10-16):

    File "/app/app.py", line 6640, in <listcomp>
      "lane": r[0],
    KeyError: 0

This file pins the column-name contract, so the mistake cannot come back silently.
Against the pre-fix `app.py` every test below that calls the board fails with that
same `KeyError: 0` (500), which is the property that makes it worth having.

The lane rows are created by the tests themselves: the harness clones only the prod
SCHEMA into archie_test, so migration 024's seed rows are not present here.

Runs in-container:
    docker exec -i archie_platform python3 -m pytest tests/test_internal_handover.py -q
or against a worktree via scripts/run_tests.sh.
"""

import pytest

from services import internal_auth as ia

CALLER_KEYS = {caller: f"key-for-{caller}" for caller in ia.CALLER_ENV}

BOARD_FIELDS = frozenset(
    {
        "lane",
        "status",
        "headline",
        "working_on",
        "blockers",
        "next_step",
        "branch",
        "pr_url",
        "updated_by",
        "updated_at",
    }
)


@pytest.fixture
def keys(monkeypatch):
    for caller, env in ia.CALLER_ENV.items():
        monkeypatch.setenv(env, CALLER_KEYS[caller])
    monkeypatch.delenv(ia.LEGACY_ENV, raising=False)
    monkeypatch.delenv(ia.LEGACY_ACCEPT_ENV, raising=False)
    return CALLER_KEYS


@pytest.fixture
def lanes_cleanup(app):
    """archie_test is persistent — remove the rows this module writes."""
    yield
    with app.app_context():
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM lane_handover WHERE updated_by = 'pytest'")


def _h(caller):
    return {"Authorization": f"Bearer {CALLER_KEYS[caller]}"}


def test_no_key_is_401_and_out_of_scope_is_403(client, keys):
    assert client.get("/api/internal/handover").status_code == 401

    # archie_engine holds tasks/repair scopes but must NOT reach the handover family.
    r = client.get("/api/internal/handover", headers=_h("archie_engine"))
    assert r.status_code == 403
    body = r.get_json()
    assert body["error"] == "scope_denied"
    assert body["caller"] == "archie_engine"
    assert body["required"] == "handover:read"


def test_board_lists_rows_by_column_name(client, keys, lanes_cleanup):
    for lane in ("opencode", "codex"):
        post = client.post(
            "/api/internal/handover",
            headers=_h("coder_lanes"),
            json={
                "lane": lane,
                "status": "working",
                "headline": "pytest %s" % lane,
                "working_on": "regression coverage for the internal handover board",
                "updated_by": "pytest",
            },
        )
        # Pre-fix this is a 500: the trailing list() call raises KeyError: 0.
        assert post.status_code == 200, post.get_data(as_text=True)

    r = client.get("/api/internal/handover", headers=_h("coder_lanes"))
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["success"] is True
    assert isinstance(body["lanes"], list)

    rows = {row["lane"]: row for row in body["lanes"]}
    assert {"opencode", "codex"} <= set(rows)
    for row in rows.values():
        # the ten columns are addressed BY NAME — a positional row cannot satisfy this
        assert BOARD_FIELDS <= set(row), sorted(set(row))
        assert isinstance(row["updated_at"], str) or row["updated_at"] is None

    assert rows["opencode"]["headline"] == "pytest opencode"
    assert rows["opencode"]["status"] == "working"
    assert rows["opencode"]["updated_at"] is not None  # .isoformat() ran


def test_update_then_get_round_trip(client, keys, lanes_cleanup):
    payload = {
        "lane": "opencode",
        "status": "reviewing",
        "headline": "pytest round-trip",
        "working_on": "verifying the handover board end to end",
        "branch": "opencode/lane-handover-fix",
        "updated_by": "pytest",
    }
    post = client.post("/api/internal/handover", headers=_h("coder_lanes"), json=payload)
    assert post.status_code == 200, post.get_data(as_text=True)
    returned = post.get_json()
    assert returned["success"] is True
    row = next(r for r in returned["lanes"] if r["lane"] == "opencode")
    assert row["status"] == "reviewing"
    assert row["headline"] == "pytest round-trip"
    assert isinstance(row["updated_at"], str)

    # a second, independent GET must observe the same state
    get = client.get("/api/internal/handover", headers=_h("coder_lanes"))
    assert get.status_code == 200
    row = next(r for r in get.get_json()["lanes"] if r["lane"] == "opencode")
    assert row["headline"] == "pytest round-trip"
    assert row["branch"] == "opencode/lane-handover-fix"


def test_update_rejects_unknown_lane_and_state(client, keys):
    bad_lane = client.post(
        "/api/internal/handover",
        headers=_h("coder_lanes"),
        json={"lane": "nope", "status": "working"},
    )
    assert bad_lane.status_code == 400
    assert "lane must be one of" in bad_lane.get_json()["error"]

    bad_state = client.post(
        "/api/internal/handover",
        headers=_h("coder_lanes"),
        json={"lane": "opencode", "status": "naps"},
    )
    assert bad_state.status_code == 400
    assert "status must be one of" in bad_state.get_json()["error"]
