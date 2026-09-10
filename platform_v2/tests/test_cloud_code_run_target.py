"""#6680 Phase 4b — target file up front on the cloud-code run route + the apply route.

Seeds bridge_jobs rows on a RAW autocommit connection (the routes open their own
connections, so uncommitted fixture rows would be invisible — and a pooled
database.get_db() connection returned with autocommit set poisons the next borrower).
GitHub and the approval queue are faked; nothing here talks to GitHub or enqueues a
real approval. In-container:
    docker exec -i archie_platform python3 -m pytest /app/tests/test_cloud_code_run_target.py -q
"""

import json
import uuid

import pytest

from services import cloud_code_apply as ap
from services import cloud_code_lane as lane
from services import internal_auth as ia
from tools.repair_bay.services import github_service as gh

CALLER_KEYS = {caller: f"key-for-{caller}" for caller in ia.CALLER_ENV}


@pytest.fixture
def keys(monkeypatch):
    for caller, env in ia.CALLER_ENV.items():
        monkeypatch.setenv(env, CALLER_KEYS[caller])
    # The flat legacy key is accepted as FULL scope unless INTERNAL_KEY_LEGACY_ACCEPT=0,
    # so drop both spellings: a scope assertion must bind the per-caller table, not a
    # container-provided fallback that happens to be set.
    monkeypatch.delenv(ia.LEGACY_ENV, raising=False)
    monkeypatch.delenv(ia.LEGACY_ENV_ALT, raising=False)
    return CALLER_KEYS


@pytest.fixture
def db():
    import os

    import psycopg2
    import psycopg2.extras

    import database

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        port=os.environ.get("DB_PORT", "5432"),
        user=os.environ.get("DB_USER", "archie"),
        password=database._get_db_password(),
        dbname=os.environ.get("TEST_DB_NAME", "archie_test"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        # Ask the CONNECTION which database it is on, not the environment: DB_NAME can be
        # unset and still resolve to prod through a module-level default (#6016).
        cur.execute("SELECT current_database() AS db")
        if cur.fetchone()["db"] == database.PROD_DB_NAME:
            conn.close()
            raise RuntimeError("refusing to seed cloud-code test rows into production")
    yield conn
    conn.close()


def _h():
    return {"Authorization": f"Bearer {CALLER_KEYS['archie_comms']}"}


@pytest.fixture
def lane_ok(monkeypatch):
    monkeypatch.setattr(lane, "code_allowed", lambda: True)
    monkeypatch.setattr(lane, "active_provider", lambda k: {"is_active": True, "default_model": "oc/big-pickle"})
    monkeypatch.setattr(lane, "request_tier2_approval", lambda **kw: 777)


def _meta(db, job_id):
    with db.cursor() as cur:
        cur.execute("SELECT metadata FROM bridge_jobs WHERE id=%s", (job_id,))
        return cur.fetchone()["metadata"]


def _cleanup(db, job_id):
    with db.cursor() as cur:
        cur.execute("DELETE FROM bridge_jobs WHERE id=%s", (job_id,))


def test_run_without_target_is_byte_identical_to_today(client, keys, lane_ok, db):
    r = client.post("/api/internal/cloud-code/run", headers=_h(), json={"prompt": "hi"})
    assert r.status_code == 202
    job_id = r.get_json()["job_id"]
    try:
        assert set(_meta(db, job_id)) == {
            "lane",
            "provider",
            "model",
            "capability",
            "prompt",
            "system_prompt",
            "requested_by",
            "approval_id",
        }
    finally:
        _cleanup(db, job_id)


def test_run_with_target_reads_main_and_assembles_the_prompt(client, keys, lane_ok, db, monkeypatch):
    seen = {}

    def fake_get(path, ref="main"):
        seen.update(path=path, ref=ref)
        return {"sha": "abc1234def", "content": "old = 1\n", "size": 8}

    monkeypatch.setattr(gh, "get_file_at_ref", fake_get)
    r = client.post(
        "/api/internal/cloud-code/run", headers=_h(), json={"prompt": "Add two", "target_path": "./docs/a.md"}
    )
    assert r.status_code == 202, r.get_json()
    job_id = r.get_json()["job_id"]
    try:
        m = _meta(db, job_id)
        assert seen == {"path": "docs/a.md", "ref": "main"}
        assert m["target_path"] == "docs/a.md" and m["base_sha"] == "abc1234def" and m["base_size"] == 8
        # The WORKER dispatches metadata.prompt, so `prompt` must be the assembled text
        # (what is actually sent) and `prompt_original` the owner's own words.
        assert m["prompt_original"] == "Add two"
        assert (
            m["prompt"].startswith("You are editing the file docs/a.md")
            and "old = 1" in m["prompt"]
            and "Task: Add two" in m["prompt"]
        )
    finally:
        _cleanup(db, job_id)


def test_run_with_missing_target_is_a_new_file(client, keys, lane_ok, db, monkeypatch):
    monkeypatch.setattr(gh, "get_file_at_ref", lambda path, ref="main": None)
    r = client.post(
        "/api/internal/cloud-code/run", headers=_h(), json={"prompt": "Create", "target_path": "docs/new.md"}
    )
    job_id = r.get_json()["job_id"]
    try:
        m = _meta(db, job_id)
        assert m["base_sha"] is None and "does not exist yet" in m["prompt"]
    finally:
        _cleanup(db, job_id)


def test_run_with_blocked_target_is_400_and_creates_no_job(client, keys, lane_ok, db, monkeypatch):
    monkeypatch.setattr(gh, "get_file_at_ref", lambda *a, **k: pytest.fail("must not read a blocked path"))
    r = client.post(
        "/api/internal/cloud-code/run", headers=_h(), json={"prompt": "x", "target_path": "platform_v2/.env"}
    )
    assert r.status_code == 400 and "blocked by policy" in r.get_json()["error"]


def test_run_when_github_is_down_is_503(client, keys, lane_ok, monkeypatch):
    def boom(path, ref="main"):
        raise RuntimeError("github contents read failed: HTTP 502")

    monkeypatch.setattr(gh, "get_file_at_ref", boom)
    r = client.post("/api/internal/cloud-code/run", headers=_h(), json={"prompt": "x", "target_path": "docs/a.md"})
    assert r.status_code == 503 and "could not read docs/a.md" in r.get_json()["error"]


def test_target_is_not_read_before_the_sovereignty_gate(client, keys, monkeypatch):
    """The gate sits at the choke point, ahead of the work it governs.

    With the lane closed, the caller must get the TRUTHFUL 409 about the allowlist — not a
    GitHub error from a read that should never have happened. Asserting the status alone is
    not enough: a 409 would also be returned if the read ran first and happened to succeed,
    so the fake read fails the test outright if it is ever called.
    """
    monkeypatch.setattr(lane, "code_allowed", lambda: False)
    monkeypatch.setattr(lane, "active_provider", lambda k: {"is_active": True, "default_model": "oc/big-pickle"})
    monkeypatch.setattr(
        gh,
        "get_file_at_ref",
        lambda *a, **k: pytest.fail("must not read the target before the sovereignty gate"),
    )
    r = client.post("/api/internal/cloud-code/run", headers=_h(), json={"prompt": "x", "target_path": "docs/a.md"})
    assert r.status_code == 409 and "not on the cloud allowlist" in r.get_json()["error"]


def _seed_job(db, status="completed", meta=None):
    tag = uuid.uuid4().hex[:6]
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO bridge_jobs (job_type, module_source, description, status, agent_name, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (lane.JOB_TYPE, lane.MODULE_ID, f"p4b {tag}", status, "CONTRACTOR→cloud", json.dumps(meta or {})),
        )
        return cur.fetchone()["id"]


COMPLETED_META = {
    "provider": "omniroute",
    "model": "oc/big-pickle",
    "target_path": "docs/a.md",
    "base_sha": "abc1234def",
    "prompt_original": "Write a note",
    "prompt": "…",
    "result": {"response": "```markdown\n# note\n```", "model_used": "big-pickle"},
}


def test_apply_raises_tier2_and_stamps_the_job(client, keys, db, monkeypatch):
    seen = {}

    def fake_req(*, job_id, meta, content, requested_by):
        seen.update(job_id=job_id, content=content, requested_by=requested_by, target=meta.get("target_path"))
        return 888

    monkeypatch.setattr(ap, "request_tier2_approval", fake_req)
    job_id = _seed_job(db, meta=COMPLETED_META)
    try:
        r = client.post(f"/api/internal/cloud-code/run/{job_id}/apply", headers=_h())
        assert r.status_code == 202 and r.get_json() == {
            "success": True,
            "job_id": job_id,
            "approval_id": 888,
            "status": "pending_approval",
        }
        assert seen == {
            "job_id": job_id,
            "content": "# note\n",
            "requested_by": "cockpit:archie_comms",
            "target": "docs/a.md",
        }
        m = _meta(db, job_id)
        assert m["apply_approval_id"] == 888 and m["apply_requested_at"]
        s = client.get(f"/api/internal/cloud-code/run/{job_id}", headers=_h()).get_json()
        assert (
            s["target_path"] == "docs/a.md"
            and s["apply_approval_id"] == 888
            and s["prompt_original"] == "Write a note"
            and s["pr_number"] is None
        )
        runs = client.get("/api/internal/cloud-code/runs?limit=5", headers=_h()).get_json()["runs"]
        mine = [x for x in runs if x["job_id"] == job_id][0]
        assert mine["target_path"] == "docs/a.md" and mine["pr_number"] is None and mine["apply_error"] is None
        assert "prompt" not in mine
    finally:
        _cleanup(db, job_id)


@pytest.mark.parametrize(
    "status,meta,needle",
    [
        ("running", COMPLETED_META, "not completed"),
        ("completed", dict(COMPLETED_META, result={"response": ""}), "no answer"),
        ("completed", {k: v for k, v in COMPLETED_META.items() if k != "target_path"}, "without a target file"),
        ("completed", dict(COMPLETED_META, pr_number=12), "already applied"),
    ],
)
def test_apply_preconditions_are_409(client, keys, db, monkeypatch, status, meta, needle):
    monkeypatch.setattr(ap, "request_tier2_approval", lambda **kw: pytest.fail("must not request"))
    job_id = _seed_job(db, status=status, meta=meta)
    try:
        r = client.post(f"/api/internal/cloud-code/run/{job_id}/apply", headers=_h())
        assert r.status_code == 409 and needle in r.get_json()["error"]
    finally:
        _cleanup(db, job_id)


def test_apply_409s_when_the_answer_is_only_an_empty_fence(client, keys, db, monkeypatch):
    """The route's OWN empty check, not apply_precondition's.

    `apply_precondition` only sees the raw response, which here is non-empty, so it passes.
    Emptiness appears one step later: strip_fences('```python\\n\\n```') yields '\\n'. Without
    the route's own check, a branch + commit of an empty file would be raised for approval.
    """
    monkeypatch.setattr(ap, "request_tier2_approval", lambda **kw: pytest.fail("must not request"))
    empty_fence = "```python\n\n```"
    assert ap.apply_precondition("completed", dict(COMPLETED_META, result={"response": empty_fence})) is None
    assert ap.strip_fences(empty_fence).strip() == ""
    job_id = _seed_job(db, meta=dict(COMPLETED_META, result={"response": empty_fence}))
    try:
        r = client.post(f"/api/internal/cloud-code/run/{job_id}/apply", headers=_h())
        assert r.status_code == 409 and "the answer is empty" in r.get_json()["error"]
    finally:
        _cleanup(db, job_id)


def test_apply_dedup_is_409(client, keys, db, monkeypatch):
    monkeypatch.setattr(ap, "request_tier2_approval", lambda **kw: None)
    job_id = _seed_job(db, meta=COMPLETED_META)
    try:
        r = client.post(f"/api/internal/cloud-code/run/{job_id}/apply", headers=_h())
        assert r.status_code == 409 and "already waiting" in r.get_json()["error"]
    finally:
        _cleanup(db, job_id)


def test_apply_404_and_scope(client, keys):
    assert client.post("/api/internal/cloud-code/run/0/apply", headers=_h()).status_code == 404
    assert client.post("/api/internal/cloud-code/run/0/apply").status_code == 401


def test_get_file_at_ref_shapes(monkeypatch):
    import base64

    monkeypatch.setattr(
        gh,
        "_api_get",
        lambda path, params=None, timeout=15: (
            True,
            {"type": "file", "sha": "s1", "size": 4, "content": base64.b64encode(b"abc\n").decode()},
        ),
    )
    assert gh.get_file_at_ref("docs/a.md") == {"sha": "s1", "content": "abc\n", "size": 4}
    monkeypatch.setattr(
        gh, "_api_get", lambda path, params=None, timeout=15: (False, {"error": "HTTP 404", "detail": ""})
    )
    assert gh.get_file_at_ref("docs/none.md") is None
    monkeypatch.setattr(gh, "_api_get", lambda path, params=None, timeout=15: (True, {"type": "dir"}))
    with pytest.raises(ValueError):
        gh.get_file_at_ref("docs")
    monkeypatch.setattr(
        gh,
        "_api_get",
        lambda path, params=None, timeout=15: (True, {"type": "file", "sha": "s", "size": 300 * 1024, "content": ""}),
    )
    with pytest.raises(ValueError):
        gh.get_file_at_ref("docs/big.md")
    monkeypatch.setattr(gh, "_api_get", lambda path, params=None, timeout=15: (False, {"error": "HTTP 502"}))
    with pytest.raises(RuntimeError):
        gh.get_file_at_ref("docs/a.md")


def test_get_file_at_ref_percent_encodes_the_path(monkeypatch):
    """The path is interpolated into a URL, so it must be quoted before it gets there.

    validate_target already refuses these characters, but this is the I/O layer's own
    defence: a caller that skips the policy helper still cannot smuggle a query or a
    fragment into the contents URL and rebind `ref` away from main.
    """
    seen = {}

    def fake_api_get(path, params=None, timeout=15):
        seen.update(path=path, params=params)
        return True, {"type": "file", "sha": "s", "size": 0, "content": ""}

    monkeypatch.setattr(gh, "_api_get", fake_api_get)

    gh.get_file_at_ref("docs/a b+c.md")
    # Slashes survive (they are path structure); the space and the plus do not.
    assert seen["path"].endswith("/contents/docs/a%20b%2Bc.md"), seen["path"]
    assert seen["params"] == {"ref": "main"}

    gh.get_file_at_ref("docs/a.md?ref=dev#frag")
    assert "?" not in seen["path"] and "#" not in seen["path"], seen["path"]
    assert seen["path"].endswith("/contents/docs/a.md%3Fref%3Ddev%23frag"), seen["path"]
    assert seen["params"] == {"ref": "main"}


def _seed_approval(db, status, action_type="cloud_code_apply"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO autonomy_approval_queue (action_type, action_data, tier, status) "
            "VALUES (%s, %s, 2, %s) RETURNING id",
            (action_type, json.dumps({"probe": True}), status),
        )
        return cur.fetchone()["id"]


def _drop_approval(db, approval_id):
    with db.cursor() as cur:
        cur.execute("DELETE FROM autonomy_approval_queue WHERE id=%s", (approval_id,))


@pytest.mark.parametrize("queue_status", ["pending", "rejected", "executed", "expired"])
def test_status_route_reports_the_live_apply_approval_status(client, keys, db, queue_status):
    """A Deny must be visible in the run status (#6680 M3).

    The spec named an ``apply_denied_at`` field for this and nothing ever writes one
    (``grep -rn apply_denied_at platform_v2 ai_bridge`` is empty): a Deny updates
    autonomy_approval_queue and never touches the bridge_jobs row, so
    ``apply_approval_id`` alone cannot separate "still waiting" from "settled" and the
    cockpit would read "apply waits for approval #N" forever. The status route reads
    the queue row instead — no new writer, and it cannot go stale.
    """
    approval_id = _seed_approval(db, queue_status)
    job_id = _seed_job(db, meta=dict(COMPLETED_META, apply_approval_id=approval_id))
    try:
        s = client.get(f"/api/internal/cloud-code/run/{job_id}", headers=_h()).get_json()
        assert s["apply_approval_id"] == approval_id
        assert s["apply_approval_status"] == queue_status
    finally:
        _cleanup(db, job_id)
        _drop_approval(db, approval_id)


def test_status_route_reports_none_when_no_apply_was_requested(client, keys, db):
    """Non-vacuity: the field is not just echoing whatever the last query returned."""
    job_id = _seed_job(db, meta=COMPLETED_META)
    try:
        s = client.get(f"/api/internal/cloud-code/run/{job_id}", headers=_h()).get_json()
        assert s["apply_approval_id"] is None
        assert s["apply_approval_status"] is None
    finally:
        _cleanup(db, job_id)


def test_a_purged_approval_row_does_not_break_the_status_payload(client, keys, db):
    """A stamped id whose queue row is gone reports None, not a 500 — the run view depends on this."""
    job_id = _seed_job(db, meta=dict(COMPLETED_META, apply_approval_id=2147483000))
    try:
        r = client.get(f"/api/internal/cloud-code/run/{job_id}", headers=_h())
        assert r.status_code == 200
        s = r.get_json()
        assert s["apply_approval_id"] == 2147483000
        assert s["apply_approval_status"] is None
    finally:
        _cleanup(db, job_id)


@pytest.mark.parametrize("queue_status", ["pending", "rejected", "executed", "expired"])
def test_runs_list_reports_the_live_apply_approval_status(client, keys, db, queue_status):
    """The LIST payload must carry the same live status the single-job GET does (#6680 fix wave).

    The status route already resolved this and the list did not, so the cockpit — which renders
    its job cards from the LIST — could only see ``apply_approval_id``. That id is set for a
    pending apply AND for a rejected or expired one, so a denied apply rendered
    "apply waits for approval #N" forever, with the Apply button suppressed and no retry path,
    even though the hub's own dedup only blocks a *pending* apply and would accept the retry.
    """
    approval_id = _seed_approval(db, queue_status)
    job_id = _seed_job(db, meta=dict(COMPLETED_META, apply_approval_id=approval_id))
    try:
        runs = client.get("/api/internal/cloud-code/runs?limit=100", headers=_h()).get_json()["runs"]
        mine = [x for x in runs if x["job_id"] == job_id][0]
        assert mine["apply_approval_id"] == approval_id
        assert mine["apply_approval_status"] == queue_status
    finally:
        _cleanup(db, job_id)
        _drop_approval(db, approval_id)


def test_runs_list_apply_status_is_none_without_an_apply_and_for_a_purged_row(client, keys, db):
    """Non-vacuity: the key is resolved per row, not stamped with whatever the last query saw."""
    plain = _seed_job(db, meta=COMPLETED_META)
    purged = _seed_job(db, meta=dict(COMPLETED_META, apply_approval_id=2147483000))
    approval_id = _seed_approval(db, "rejected")
    real = _seed_job(db, meta=dict(COMPLETED_META, apply_approval_id=approval_id))
    try:
        r = client.get("/api/internal/cloud-code/runs?limit=100", headers=_h())
        assert r.status_code == 200
        by_id = {x["job_id"]: x for x in r.get_json()["runs"]}
        assert by_id[plain]["apply_approval_id"] is None and by_id[plain]["apply_approval_status"] is None
        assert by_id[purged]["apply_approval_id"] == 2147483000
        assert by_id[purged]["apply_approval_status"] is None
        # …and a real one on the SAME page still resolves, so "None everywhere" cannot pass.
        assert by_id[real]["apply_approval_status"] == "rejected"
    finally:
        for j in (plain, purged, real):
            _cleanup(db, j)
        _drop_approval(db, approval_id)


def test_runs_list_resolves_every_apply_status_in_one_batched_query(client, keys, db, monkeypatch):
    """No N+1: the cockpit re-polls this list every 5 s while a job is active.

    Counts get_db_cursor() opens for a page holding ONE apply job, then for the same page
    holding THREE. A per-row lookup makes the second count two higher; a single ANY(%s)
    lookup makes them equal. The route imports get_db_cursor inside the function body, so
    patching the module attribute is what it actually resolves at call time.
    """
    import database

    calls = {"n": 0}
    real = database.get_db_cursor

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(database, "get_db_cursor", counting)

    ids, approvals = [], []
    try:
        for _ in range(3):
            aid = _seed_approval(db, "pending")
            approvals.append(aid)
            ids.append(_seed_job(db, meta=dict(COMPLETED_META, apply_approval_id=aid)))

        # Warm any lazily-cached auth/scope state first so it cannot skew the comparison.
        client.get("/api/internal/cloud-code/runs?limit=1", headers=_h())

        calls["n"] = 0
        one = client.get("/api/internal/cloud-code/runs?limit=1", headers=_h())
        with_one = calls["n"]

        calls["n"] = 0
        many = client.get("/api/internal/cloud-code/runs?limit=100", headers=_h())
        with_many = calls["n"]

        # The comparison is only meaningful if the wide page really did carry more apply rows.
        wide = [x for x in many.get_json()["runs"] if x["job_id"] in ids]
        assert len(wide) == 3 and all(x["apply_approval_status"] == "pending" for x in wide)
        assert len(one.get_json()["runs"]) == 1
        assert with_many == with_one, f"N+1: {with_one} cursor(s) for 1 apply row, {with_many} for 3"
    finally:
        for j in ids:
            _cleanup(db, j)
        for a in approvals:
            _drop_approval(db, a)


def test_apply_status_lookup_is_scoped_to_this_lanes_action_type(client, keys, db):
    """The ids come from the job's own metadata, so a stale or reused one would otherwise report
    a FOREIGN approval's status as this lane's. Not exploitable today — the hub writes the ids —
    but the query should match what its docstring promises."""
    foreign = _seed_approval(db, "rejected", action_type="linkedin_post")
    job_id = _seed_job(db, meta=dict(COMPLETED_META, apply_approval_id=foreign))
    try:
        st = client.get(f"/api/internal/cloud-code/run/{job_id}", headers=_h()).get_json()
        assert st["apply_approval_id"] == foreign
        assert st["apply_approval_status"] is None, "a non-cloud_code_apply row must not resolve"
        runs = client.get("/api/internal/cloud-code/runs?limit=100", headers=_h()).get_json()["runs"]
        assert [x for x in runs if x["job_id"] == job_id][0]["apply_approval_status"] is None
    finally:
        _cleanup(db, job_id)
        _drop_approval(db, foreign)


def test_the_deny_paths_write_rejected_not_denied():
    """Pins the vocabulary this lane's consumer depends on, at the SOURCE rather than in prose.

    The cockpit's APPLY_SETTLED omitted 'rejected' because two docstrings in app.py said the
    deny status was 'denied' — so every Deny rendered "apply waits for approval #N" forever with
    the Apply button suppressed, verbatim the failure the field exists to prevent. 'denied' is
    `contractor_approval_requests`' word, a DIFFERENT table. If a deny path is ever reworded this
    goes red, and the consumer gets updated with it instead of silently diverging again.
    """
    import os
    from pathlib import Path

    import ai_bridge  # the package init only — resolves ai_bridge wherever it is mounted

    # In-container tests/ lives under /app (== platform_v2), so parents[2] is "/". Resolve each
    # file from something that is true in BOTH layouts, and FAIL (never skip) if one is missing:
    # a guard that quietly stops looking is how the wrong vocabulary survived in the first place.
    routes_p = Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "approvals_routes.py"
    gateway_p = Path(os.path.dirname(ai_bridge.__file__)) / "telegram_gateway.py"
    assert routes_p.is_file(), routes_p
    assert gateway_p.is_file(), gateway_p
    routes = routes_p.read_text()
    gateway = gateway_p.read_text()

    assert "UPDATE autonomy_approval_queue" in routes and "SET status = 'rejected'" in routes
    assert gateway.count("SET status = 'rejected'") >= 2, "Telegram deny paths changed spelling"
    # …and nothing writes 'denied' to THIS table (the contractor table is a separate vocabulary)
    for name, chunk in (("approvals_routes", routes), ("telegram_gateway", gateway)):
        lines = chunk.splitlines()
        for i, line in enumerate(lines):
            if "status = 'denied'" in line or "status='denied'" in line:
                window = "\n".join(lines[max(0, i - 6) : i + 2])
                assert "autonomy_approval_queue" not in window, f"{name}:{i + 1}\n{window}"
