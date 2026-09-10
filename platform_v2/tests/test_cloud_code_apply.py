"""#6680 Phase 4b — Apply a cloud coding result: pure policy helpers (no DB, no network)."""

import os

import pytest

from services import cloud_code_apply as ap


@pytest.mark.parametrize(
    "path",
    [
        "platform_v2/services/x.py",
        "ai_bridge/y.py",
        "scripts/z.sh",
        "docs/notes.md",
        "archie-comms/app_comms.py",
        "./platform_v2/a.py",
    ],
)
def test_validate_target_accepts_allowed(path):
    assert ap.validate_target(path).startswith(("platform_v2/", "ai_bridge/", "scripts/", "docs/", "archie-comms/"))


@pytest.mark.parametrize(
    "path",
    [
        "",
        "   ",
        "/etc/passwd",
        "../platform_v2/x.py",
        "platform_v2/../../etc/passwd",
        "platform_v2\\x.py",
        "platform_v2/.env",
        "platform_v2/.env.local",
        "secrets/k.pem",
        "platform_v2/id.key",
        "docker-compose.yml",
        "Dockerfile",
        "scripts/dr/failover.sh",
        ".github/workflows/ci.yml",
        "platform_v2/.git/config",
        "platform_v2/services/agent_service.py",
        "platform_v2/tools/department_hq/services/department_dispatcher.py",
        "platform_v2/tools/repair_bay/services/github_service.py",
        "platform_v2/tools/repair_bay/services/pr_review_service.py",
        "scripts/check_agent_single_writer.py",
        "scripts/agents/run.sh",
        "scripts/backup/x.sh",
        "platform_v2/services/internal_auth.py",
        "platform_v2/services/cloud_code_apply.py",
        "platform_v2/services/cloud_code_lane.py",
        "database/migrations/483_x.sql",
        "what-the-fact/consumer/routes.py",
        "platform_v2/" + "a" * 240 + ".py",
        "platform_v2/x\x00.py",
        "platform_v2/.Env",
        "platform_v2/services/Agent_Service.py",
        "platform_v2/services/internal_auth.PY",
        "scripts/DR/failover.sh",
        # A `?` or `#` smuggles a query/fragment into the contents URL, so `...?ref=dev`
        # would be appended alongside get_file_at_ref's own `ref=main` and base_sha could
        # bind to a blob on a DIFFERENT ref than the one the model was shown. `%` would
        # slip a pre-encoded byte past that function's quoting. Rejected here as policy;
        # get_file_at_ref quotes as well, so neither layer is load-bearing alone.
        "docs/a.md?ref=dev",
        "docs/a.md#frag",
        "docs/a%2Fb.md",
        "docs/a b.md",
    ],
)
def test_validate_target_rejects(path):
    with pytest.raises(ValueError):
        ap.validate_target(path)


def test_strip_fences_variants():
    assert ap.strip_fences("x = 1\n") == "x = 1\n"
    assert ap.strip_fences("x = 1") == "x = 1\n"
    assert ap.strip_fences("```\nx = 1\n```") == "x = 1\n"
    assert ap.strip_fences("```python\nx = 1\ny = 2\n```\n") == "x = 1\ny = 2\n"
    assert ap.strip_fences("Here you go:\n```python\nx = 1\n```") == "Here you go:\n```python\nx = 1\n```\n"
    assert ap.strip_fences("") == ""


def test_prompt_and_names():
    p = ap.build_edit_prompt("docs/a.md", "Add a line", "old\n")
    assert (
        p.startswith("You are editing the file docs/a.md")
        and "--- current contents of docs/a.md ---\nold\n" in p
        and "Task: Add a line" in p
    )
    assert "does not exist yet" in ap.build_edit_prompt("docs/a.md", "Add", None)
    assert ap.branch_name(1202345, "docs/cockpit-apply-probe.md") == "cockpit/apply-1202345-docs-cockpit-apply-probe-md"
    assert len(ap.branch_name(1, "platform_v2/" + "x" * 100 + ".py")) <= len("cockpit/apply-1-") + 40
    meta = {
        "provider": "omniroute",
        "model": "oc/big-pickle",
        "result": {"model_used": "big-pickle"},
        "prompt_original": "Write a note",
    }
    assert ap.commit_message(7, "docs/a.md", meta).startswith(
        "feat(cockpit-apply): docs/a.md via omniroute:big-pickle (job #7)"
    )
    assert "Co-Authored-By: A.R.C.H.I.E. Cockpit <cockpit@kytranempowerment.com>" in ap.commit_message(
        7, "docs/a.md", meta
    )
    assert ap.pr_title("docs/a.md", meta) == "[cockpit] docs/a.md: Write a note"
    body = ap.pr_body(7, "docs/a.md", meta, "abc1234")
    assert "job #7" in body and "human merge only" in body and "abc1234" in body and "omniroute" in body
    assert ap.content_sha256("x\n") == ap.content_sha256("x\n") and len(ap.content_sha256("x\n")) == 64


def test_apply_precondition():
    ok = {"target_path": "docs/a.md", "result": {"response": "x"}}
    assert ap.apply_precondition("completed", ok) is None
    assert "not completed" in ap.apply_precondition("running", ok)
    assert "no answer" in ap.apply_precondition("completed", {"target_path": "docs/a.md", "result": {"response": ""}})
    assert "without a target file" in ap.apply_precondition("completed", {"result": {"response": "x"}})
    assert "already applied" in ap.apply_precondition("completed", dict(ok, pr_number=12))


def test_blocked_globs_match_the_engine_scope_guard():
    engine = "/mnt/standalone/archie-code/archie_engine/scope_guard.py"
    if not os.path.exists(engine):
        pytest.skip("engine source not mounted here")
    src = open(engine, encoding="utf-8").read()
    for g in ap.ENGINE_BLOCKED_GLOBS:
        assert f'"{g}"' in src, f"{g} is no longer in the engine's blocked_globs — reconcile the two lists"


# ---- executor (#6680 Phase 4b) ---------------------------------------------------------
class _FakeGH:
    def __init__(self, current=None, fail=None, existed=False):
        self.current = current
        self.fail = fail
        # github_service.create_branch returns existed=True when the ref is already on
        # the remote. Defaults False so the `nochange` test keeps exercising the real
        # delete-on-identical-content path for a genuinely NEW branch.
        self.existed = existed
        self.calls = []

    def get_file_at_ref(self, path, ref="main"):
        self.calls.append(("get", path, ref))
        if self.fail == "get":
            raise RuntimeError("github down")
        return self.current

    def create_branch(self, name, base="main"):
        self.calls.append(("branch", name, base))
        return {"success": self.fail != "branch", "branch": name, "existed": self.existed, "error": "no"}

    def push_changes(self, branch, files, msg, content_overrides=None):
        self.calls.append(("push", branch, tuple(files), msg.splitlines()[0], content_overrides))
        if self.fail == "push":
            return {"success": False, "error": "push boom"}
        if self.fail == "nochange":
            return {"success": True, "committed": False, "message": "No changes to commit"}
        return {"success": True, "committed": True, "sha": "deadbeef", "branch": branch}

    def create_pr(self, branch, title, body, labels=None, base="main"):
        self.calls.append(("pr", branch, title, labels))
        if self.fail == "pr":
            return {"success": False, "error": "pr boom"}
        if self.fail == "prnonum":
            # github_service does `pr_number = data.get("number")` and returns success
            # WITHOUT asserting it — so a success carrying no number is reachable. It
            # DOES always carry pr_url (`data.get("html_url", "")`), so the faithful
            # shape includes an empty url: without it the executor would blow up on a
            # KeyError, and this test would pass for a reason production never hits.
            # The real hazard is silent — executed=True with pr_number None stamped.
            return {"success": True, "pr_number": None, "pr_url": ""}
        return {"success": True, "pr_number": 4242, "pr_url": "https://example/pull/4242", "branch": branch}

    def delete_branch(self, name, remote=True):
        self.calls.append(("delete", name))
        return {"success": True}


JOB = {
    "id": 77,
    "status": "completed",
    "metadata": {
        "provider": "omniroute",
        "model": "oc/big-pickle",
        "target_path": "docs/a.md",
        "base_sha": "abc1234",
        "prompt_original": "Write a note",
        "result": {"response": "```\n# note\n```", "model_used": "big-pickle"},
    },
}


def _action(content="# note\n", **over):
    a = {"job_id": 77, "target_path": "docs/a.md", "base_sha": "abc1234", "content_sha256": ap.content_sha256(content)}
    a.update(over)
    return a


def _run(gh, action=None, job=JOB):
    stamps = []
    r = ap.execute(
        action or _action(),
        gh=gh,
        load_job=lambda jid: job if jid == 77 else None,
        stamp_job=lambda jid, patch: stamps.append((jid, patch)),
    )
    return r, stamps


def test_execute_happy_path_orders_the_primitives_and_stamps_the_pr():
    gh = _FakeGH(current={"sha": "abc1234", "content": "old\n", "size": 4})
    r, stamps = _run(gh)
    assert r == {
        "executed": True,
        "pr_number": 4242,
        "pr_url": "https://example/pull/4242",
        "branch": "cockpit/apply-77-docs-a-md",
    }
    kinds = [c[0] for c in gh.calls]
    assert kinds == ["get", "branch", "push", "pr"]
    push = gh.calls[2]
    assert (
        push[2] == ("docs/a.md",)
        and push[4] == {"docs/a.md": "# note\n"}
        and push[3].startswith("feat(cockpit-apply): docs/a.md via omniroute:big-pickle (job #77)")
    )
    assert gh.calls[3][2] == "[cockpit] docs/a.md: Write a note" and gh.calls[3][3] == ["cockpit-apply"]
    assert (
        stamps[-1][0] == 77
        and stamps[-1][1]["pr_number"] == 4242
        and stamps[-1][1]["branch"] == "cockpit/apply-77-docs-a-md"
        and stamps[-1][1]["apply_error"] is None
    )


def test_execute_refuses_when_main_moved_and_writes_nothing():
    gh = _FakeGH(current={"sha": "ffff999", "content": "new\n", "size": 4})
    r, stamps = _run(gh)
    assert (
        r["executed"] is False
        and "changed on main" in r["error"]
        and "abc1234" in r["error"]
        and "ffff999" in r["error"]
    )
    assert [c[0] for c in gh.calls] == ["get"]
    assert stamps[-1][1]["apply_error"].startswith("docs/a.md changed on main")


def test_execute_new_file_needs_base_sha_none():
    gh = _FakeGH(current=None)
    job = dict(JOB, metadata=dict(JOB["metadata"], base_sha=None))
    r, _ = _run(gh, _action(base_sha=None), job=job)
    assert r["executed"] is True
    gh2 = _FakeGH(current={"sha": "now", "content": "x", "size": 1})
    r2, _ = _run(gh2, _action(base_sha=None), job=job)
    assert r2["executed"] is False and "changed on main" in r2["error"]


def test_execute_refuses_content_hash_mismatch():
    gh = _FakeGH(current={"sha": "abc1234", "content": "old\n", "size": 4})
    r, _ = _run(gh, _action(content="something else\n"))
    assert r["executed"] is False and "changed since the approval" in r["error"] and gh.calls == []


def test_execute_cleans_the_branch_on_push_or_pr_failure():
    for fail, needle in (("push", "push boom"), ("pr", "pr boom"), ("nochange", "identical")):
        gh = _FakeGH(current={"sha": "abc1234", "content": "old\n", "size": 4}, fail=fail)
        r, stamps = _run(gh)
        assert r["executed"] is False and needle in r["error"], (fail, r)
        assert ("delete", "cockpit/apply-77-docs-a-md") in gh.calls
        assert stamps[-1][1]["apply_error"]


def test_execute_missing_job_or_github_read_failure():
    r, _ = _run(_FakeGH(), _action(job_id=5))
    assert r["executed"] is False and "not found" in r["error"]
    r, _ = _run(_FakeGH(fail="get"))
    assert r["executed"] is False and "could not read" in r["error"]


def test_execute_refuses_a_pr_with_no_number():
    # A success carrying no pr_number is a status that misreports the artifact: the job
    # would read "applied" with no PR link while a branch with a commit sat on the remote.
    # Treated exactly like a failed PR — clean up the branch, refuse, stamp nothing.
    gh = _FakeGH(current={"sha": "abc1234", "content": "old\n", "size": 4}, fail="prnonum")
    r, stamps = _run(gh)
    assert r["executed"] is False and "no number" in r["error"]
    assert ("delete", "cockpit/apply-77-docs-a-md") in gh.calls
    assert "pr_number" not in stamps[-1][1] and stamps[-1][1]["apply_error"]


def test_execute_refuses_an_already_existing_branch_without_deleting_it():
    # branch_name() is deterministic per (job, target), so a second execution of the same
    # job hits a branch that is already on the remote. github_service.create_branch answers
    # {"success": True, "existed": True} there. Reading only `success` would carry on into
    # push_changes → committed False → the delete arm, destroying the FIRST apply's branch
    # and closing its open PR. Refuse instead, and touch nothing.
    gh = _FakeGH(current={"sha": "abc1234", "content": "old\n", "size": 4}, existed=True)
    r, stamps = _run(gh)
    assert r["executed"] is False
    assert "already exists" in r["error"] and "cockpit/apply-77-docs-a-md" in r["error"]
    assert [c[0] for c in gh.calls] == ["get", "branch"]
    assert not any(c[0] == "delete" for c in gh.calls), "must NOT delete a pre-existing branch"
    assert stamps[-1][1]["apply_error"]


def test_execute_reports_the_pr_even_when_the_success_stamp_fails():
    # The PR genuinely exists on the remote by this point, so reporting executed=False
    # would be the lie. Surface stamp_error instead — and note an unstamped success is
    # what blinds apply_precondition, which is the realistic route into the case above.
    gh = _FakeGH(current={"sha": "abc1234", "content": "old\n", "size": 4})

    def boom(_jid, _patch):
        raise RuntimeError("db blip")

    r = ap.execute(_action(), gh=gh, load_job=lambda jid: JOB if jid == 77 else None, stamp_job=boom)
    assert r["executed"] is True and r["pr_number"] == 4242
    assert r["pr_url"] == "https://example/pull/4242" and r["branch"] == "cockpit/apply-77-docs-a-md"
    assert r["stamp_error"] == "db blip"
    assert [c[0] for c in gh.calls] == ["get", "branch", "push", "pr"]


def test_execute_does_not_raise_when_the_refusal_stamp_fails():
    # A refusal is exactly when the job most needs apply_error recorded — but raising
    # here would lose BOTH the refusal reason and the stamp, and execute() promises in
    # its own docstring that it never raises. Simplest refusal path: base sha moved.
    gh = _FakeGH(current={"sha": "ffff999", "content": "new\n", "size": 4})

    def boom(_jid, _patch):
        raise RuntimeError("db blip")

    r = ap.execute(_action(), gh=gh, load_job=lambda jid: JOB if jid == 77 else None, stamp_job=boom)
    assert r["executed"] is False and "changed on main" in r["error"]
    assert [c[0] for c in gh.calls] == ["get"], "must still have written nothing"
