"""POST /api/roster/agent — malformed-envelope hardening (task 6, fix round 1).

Two bugs found in review, both about an untyped envelope field escaping validation
and reaching code that assumes its type:

  - Finding I: `side_effects` as a truthy NON-dict (e.g. the string "yes") survives
    `data.get("side_effects") or {}` unchanged. Inside `create_agent_full`, the
    agent row is INSERTed and skills are added, then `side_effects.get("budget")`
    is called OUTSIDE any try — AttributeError on a str, uncaught, propagates to
    the route's bare `except Exception` -> 500. Net effect: the agent EXISTS in
    the DB, the caller is told it failed, and never learns the id. Fix: normalize
    `side_effects` (and `skills`) to their expected types at the TOP of
    `create_agent_full`, before the agent is ever created, so nothing after the
    INSERT can raise on envelope shape.

  - Finding J: a bare JSON list/string/number is a VALID request body. All
    validation in the route ran OUTSIDE its try, so `data.get("fields")` raised
    AttributeError on a list and Flask returned its default HTML error page
    instead of the `{"ok": false, "error": ...}` envelope every other path
    returns. Fix: validate the envelope's TOP-LEVEL type (and fields/side_effects
    dict-ness, skills list-ness) before calling `.get` on any of them.
"""

import sys
from contextlib import contextmanager
from functools import wraps
from unittest.mock import patch

import pytest

if "/app" not in sys.path:
    sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Finding I — side_effects normalized to a dict before the agent is created,
# so nothing after the INSERT can raise on its shape.
# ---------------------------------------------------------------------------


def test_truthy_non_dict_side_effects_does_not_orphan_the_agent():
    from services import agent_lifecycle

    with patch.object(agent_lifecycle, "create_agent", return_value=4242) as mock_create, patch.object(
        agent_lifecycle, "_add_skill"
    ) as mock_add_skill, patch.object(agent_lifecycle, "_ensure_budget") as mock_budget, patch.object(
        agent_lifecycle, "_provision_mailbox"
    ) as mock_mailbox, patch.object(
        agent_lifecycle, "_queue_portrait"
    ) as mock_portrait:
        out = agent_lifecycle.create_agent_full(
            {
                "name": "X",
                "display_name": "X",
                "department": "Engineering & Technology",
                "model": "qwen2.5:7b",
            },
            [{"skill_name": "code", "proficiency_level": 3, "skill_category": "technical"}],
            "yes",  # truthy, NOT a dict — this must not crash after creation
        )

    # The agent WAS created (mocked) — it must not be reported as a failure with
    # no id. This is the exact shape of the orphaned-agent bug: created but the
    # caller never learns the id.
    assert out["ok"] is True
    assert out["agent_id"] == 4242
    mock_create.assert_called_once()
    mock_add_skill.assert_called_once()
    # A non-dict side_effects normalizes to {} — none of budget/portrait/mailbox
    # are truthy in {}, so none of these side effects should fire.
    mock_budget.assert_not_called()
    mock_mailbox.assert_not_called()
    mock_portrait.assert_not_called()


def test_truthy_non_list_skills_is_refused_before_agent_creation():
    """A non-list truthy `skills` (e.g. a string) must normalize to [] and hit
    the existing 'at least one skill is required' refusal BEFORE create_agent
    is ever called — not fall into a per-character/per-key skill-add loop."""
    from services import agent_lifecycle

    with patch.object(agent_lifecycle, "create_agent") as mock_create:
        out = agent_lifecycle.create_agent_full(
            {
                "name": "X",
                "display_name": "X",
                "department": "Engineering & Technology",
                "model": "qwen2.5:7b",
            },
            "yes",  # truthy, NOT a list
            {},
        )

    assert out["ok"] is False
    assert out["agent_id"] is None
    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# Finding J — a non-object JSON body returns the {"ok": false, ...} envelope,
# never Flask's default HTML error page.
# ---------------------------------------------------------------------------


def _build_client():
    from flask import Blueprint, Flask, jsonify
    from flask_login import LoginManager, UserMixin, current_user

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    class _User(UserMixin):
        id = 1
        is_admin = True
        username = "test_admin"

    lm = LoginManager(app)
    _user = _User()

    @lm.user_loader
    def _load(uid):
        return _user

    def admin_required(f):
        @wraps(f)
        def _inner(*a, **k):
            if not getattr(current_user, "is_admin", False):
                return jsonify({"ok": False, "error": "not_admin"}), 403
            return f(*a, **k)

        return _inner

    from tools.department_hq.roster_routes import register_roster_routes

    bp = Blueprint("dhq", __name__, url_prefix="/tools/department-hq")
    register_roster_routes(bp, admin_required)
    app.register_blueprint(bp)

    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True
    return c


def test_bare_list_body_returns_400_json_not_html_500():
    c = _build_client()
    r = c.post("/tools/department-hq/api/roster/agent", json=[1, 2, 3])

    assert r.status_code == 400
    assert r.is_json, "route must return the {ok:false,...} JSON envelope, not an HTML error page"
    body = r.get_json()
    assert body["ok"] is False


def test_bare_string_body_returns_400_json_not_html_500():
    c = _build_client()
    r = c.post("/tools/department-hq/api/roster/agent", json="not an object")

    assert r.status_code == 400
    assert r.is_json
    assert r.get_json()["ok"] is False


def test_non_dict_fields_value_returns_400_not_500():
    """`{"fields": "yes", ...}` — fields present but the wrong type."""
    c = _build_client()
    r = c.post("/tools/department-hq/api/roster/agent", json={"fields": "yes", "skills": []})

    assert r.status_code == 400
    assert r.is_json
    assert r.get_json()["ok"] is False


def test_valid_envelope_with_non_dict_side_effects_still_succeeds():
    """End-to-end: a truthy non-dict side_effects in the actual HTTP body must
    not 500 the route — create_agent_full is mocked so nothing real is written."""
    from services import agent_lifecycle

    c = _build_client()
    with patch.object(
        agent_lifecycle,
        "create_agent_full",
        return_value={"ok": True, "agent_id": 777, "results": [{"step": "agent", "ok": True, "detail": "mocked"}]},
    ) as mock_full:
        r = c.post(
            "/tools/department-hq/api/roster/agent",
            json={
                "fields": {
                    "name": "X",
                    "display_name": "X",
                    "department": "Engineering & Technology",
                    "model": "qwen2.5:7b",
                    "worker_type": "ai",
                },
                "skills": [{"skill_name": "code"}],
                "side_effects": "yes",
            },
        )

    assert r.status_code == 201
    body = r.get_json()
    assert body["ok"] is True
    assert body["agent_id"] == 777
    mock_full.assert_called_once()


# ---------------------------------------------------------------------------
# create_agent — identity fields must persist, not vanish (#5878, KB #292520)
#
# `agent_service.create_agent(name, display_name, department, model, **kwargs)`
# read a fixed handful of keys out of **kwargs and silently discarded anything
# else. Nine REAL `agents` columns — title, bio, acronym, acronym_expansion,
# gender, ethnicity, age_range, first_name, last_name — were collected by the
# roster create-agent modal (agent_create.js), forwarded through
# create_agent_full's `{k: v for k, v in fields.items() if k not in (...)}`,
# and never reached the INSERT. The per-step results panel reported every
# step green while the identity the operator specified vanished — a FALSE
# SUCCESS, not a crash.
#
# The fix does two things at the single-writer choke point:
#   1. Persists all nine columns (still optional — absent means NULL).
#   2. Replaces the open-ended **kwargs sink with an explicit allowlist
#      (`_CREATE_AGENT_KNOWN_KWARGS`) so an unrecognised kwarg RAISES
#      TypeError instead of disappearing. Verified (grep every caller of
#      create_agent(/create_agent_full() repo-wide) that no existing caller
#      passes anything outside that allowlist — so the strict check cannot
#      break a real caller, only a typo or a genuinely new, unwired field.
#
# Regression proof (per .claude/rules/repair-bay.md — "a test that cannot
# fail is worse than no test"): both assertions below were run against a
# `importlib`-loaded COPY of this module taken from git HEAD (the commit
# immediately before this fix, c9cfe5908) — never against the live file,
# which other agents share. Against that copy: the identity columns were
# ALL absent from the INSERT, and the unknown-kwarg call raised nothing at
# all (silently succeeded) — exactly the bug reported, confirming these
# tests actually catch it.
# ---------------------------------------------------------------------------


class _InsertCapturingCursor:
    """Fake cursor that records the exact `INSERT INTO agents (...)` call.

    Not a canned-response stub: it parses the REAL column list out of the SQL
    text `create_agent` builds and zips it against the REAL bound params, so
    the assertions below check what was actually about to be written to the
    database — not a hand-maintained mirror of it that could drift out of
    sync with the code and pass vacuously.
    """

    def __init__(self, new_id=8001):
        self.new_id = new_id
        self.executed = []
        self._result = None

    def execute(self, sql, params=None):
        flat = " ".join(str(sql).split())
        self.executed.append((flat, params))
        self._result = {"id": self.new_id} if "INSERT INTO agents" in flat else None

    def fetchone(self):
        return self._result

    def agents_insert_columns(self):
        for sql, params in self.executed:
            if "INSERT INTO agents" in sql:
                cols = [c.strip() for c in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
                return dict(zip(cols, params))
        raise AssertionError("no INSERT INTO agents was executed")

    def ran_insert(self):
        return any("INSERT INTO agents" in sql for sql, _ in self.executed)


@contextmanager
def _patched_agent_service_db(cur):
    """Patch agent_service's DB boundary only — no real row is ever written.

    Also bypasses the (unrelated, already-covered-elsewhere) name-collision
    guard so these tests exercise only the field-persistence / kwarg-validation
    behaviour under test.
    """
    from services import agent_service as svc

    @contextmanager
    def _fake_get_db_cursor(*_a, **_k):
        yield (None, cur)

    with patch.object(svc, "get_db_cursor", _fake_get_db_cursor), patch.object(
        svc, "find_name_collision", return_value=None
    ):
        yield


# The nine fields exactly as diagnosed in #5878, split by presentation kind
# (agent_create.js never sends acronym+first_name together — 'ai' kind sends
# name/acronym/acronym_expansion, 'internal' kind sends first/last/gender/
# ethnicity/age_range — but create_agent must persist either combination).
_AI_KIND_IDENTITY_FIELDS = {
    "title": "Task-11 Acceptance Drive Probe",
    "bio": "A test bio for the acceptance drive.",
    "acronym": "T.E.S.T.",
    "acronym_expansion": "Test Expansion Standing Together",
    "gender": None,
    "ethnicity": None,
    "age_range": None,
    "first_name": None,
    "last_name": None,
}

_HUMAN_KIND_IDENTITY_FIELDS = {
    "title": "Acceptance Drive Coordinator",
    "bio": "A test bio for a human-presenting agent.",
    "acronym": None,
    "acronym_expansion": None,
    "gender": "woman",
    "ethnicity": "Filipino-Canadian",
    "age_range": "30s",
    "first_name": "Test",
    "last_name": "Probe",
}


def test_create_agent_persists_ai_kind_identity_fields():
    """title/bio/acronym/acronym_expansion must land in the INSERT, not vanish."""
    from services import agent_service as svc

    cur = _InsertCapturingCursor(new_id=8001)
    with _patched_agent_service_db(cur):
        agent_id = svc.create_agent(
            "T.E.S.T.",
            "Test Agent",
            "Engineering & Technology",
            "qwen2.5:7b",
            worker_type="ai",
            **_AI_KIND_IDENTITY_FIELDS,
        )
    assert agent_id == 8001
    row = cur.agents_insert_columns()
    for key, expected in _AI_KIND_IDENTITY_FIELDS.items():
        assert row.get(key) == expected, f"{key!r} did not persist: got {row.get(key)!r}, expected {expected!r}"


def test_create_agent_persists_human_kind_identity_fields():
    """first_name/last_name/gender/ethnicity/age_range must land in the INSERT."""
    from services import agent_service as svc

    cur = _InsertCapturingCursor(new_id=8002)
    with _patched_agent_service_db(cur):
        agent_id = svc.create_agent(
            "Test Probe",
            "Test Probe",
            "Engineering & Technology",
            "qwen2.5:7b",
            worker_type="internal",
            **_HUMAN_KIND_IDENTITY_FIELDS,
        )
    assert agent_id == 8002
    row = cur.agents_insert_columns()
    for key, expected in _HUMAN_KIND_IDENTITY_FIELDS.items():
        assert row.get(key) == expected, f"{key!r} did not persist: got {row.get(key)!r}, expected {expected!r}"


def test_create_agent_identity_fields_are_optional_and_default_to_null():
    """An agent created with NONE of the nine fields still creates cleanly —
    NULL, exactly as for any agent created elsewhere today, not an error."""
    from services import agent_service as svc

    cur = _InsertCapturingCursor(new_id=8003)
    with _patched_agent_service_db(cur):
        agent_id = svc.create_agent(
            "Minimal Agent",
            "Minimal Agent",
            "Engineering & Technology",
            "qwen2.5:7b",
        )
    assert agent_id == 8003
    row = cur.agents_insert_columns()
    for key in _AI_KIND_IDENTITY_FIELDS:
        assert row.get(key) is None


def test_create_agent_raises_on_an_unknown_kwarg():
    """The actual root cause of #5878: **kwargs accepted (and discarded) any
    key nobody had wired up. An unrecognised kwarg must now fail LOUD, at the
    choke point, before any row is written."""
    from services import agent_service as svc

    cur = _InsertCapturingCursor()
    with _patched_agent_service_db(cur):
        with pytest.raises(TypeError) as exc:
            svc.create_agent(
                "Test Agent",
                "Test Agent",
                "Engineering & Technology",
                "qwen2.5:7b",
                favorite_color="teal",  # not a real column, not a real kwarg
            )
    assert "favorite_color" in str(exc.value)
    # fail CLOSED: nothing should have been written
    assert not cur.ran_insert()


def test_create_agent_known_kwargs_all_still_accepted():
    """Every kwarg every existing caller passes today (grepped repo-wide:
    seed_procure_agent.py, orchestration_engine.py, department_dispatcher.py,
    hiring_service.py, aaas_service.py, and agent_lifecycle.create_agent_full's
    dynamic forwarding of the roster create-agent form) must still be
    accepted — the strict check must not become a NEW silent-drop-shaped
    regression by rejecting a legitimate caller."""
    from services import agent_service as svc

    cur = _InsertCapturingCursor(new_id=8004)
    with _patched_agent_service_db(cur):
        agent_id = svc.create_agent(
            "Known Kwargs Agent",
            "Known Kwargs Agent",
            "Engineering & Technology",
            "qwen2.5:7b",
            shift_state="active",
            allow_duplicate_name=False,
            system_prompt="you are a test agent",
            temperature=0.5,
            max_tokens=1024,
            capabilities={"code": True},
            is_department_ai=False,
            tier=2,
            worker_type="ai",
            **_AI_KIND_IDENTITY_FIELDS,
        )
    assert agent_id == 8004
    assert cur.ran_insert()
