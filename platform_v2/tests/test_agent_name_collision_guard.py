"""Agent name-collision guard — dots are the naming convention, not decoration (#5272).

'A.T.L.A.S.' and 'Atlas' are the SAME name. A literal string comparison says they
are not, so ``propose_hire`` waved through a hire that collided with existing agent
#17 'Atlas'. Ten such twins exist today (F.O.R.G.E./Forge and C.O.D.E.X./Codex are
both ACTIVE pairs), and two of them — A.T.L.A.S. #430 and H.A.V.E.N. #431 — were
minted AFTER the hole was reported.

The guard now lives at the single-writer choke point (``create_agent``) as well as
in the proposal path, because a rule enforced in one caller is not enforced at all
— the same shape as the #5194 merge-governance hole.

Pure/mocked: no DB. (Host-side pytest reaches a Postgres with no agent rows, so a
DB-backed assertion here would be vacuously green.)
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from services import agent_service as svc

_ATLAS_ROW = {"id": 17, "name": "Atlas", "shift_state": "decommissioned"}


class FakeCursor:
    """A tiny in-memory ``agents`` table that HONOURS the WHERE clause it is given.

    Deliberately not a canned-response stub. A stub that returns a preloaded row
    regardless of the SQL passes just as happily against the literal comparison
    this fix replaces — so the behavioural tests below would be vacuous and could
    never detect a revert. Instead this evaluates the predicate the code actually
    sent: normalized (dots/case folded) vs literal. Revert the guard and the
    lookups genuinely stop matching, exactly as in production.
    """

    def __init__(self, rows=None, new_id=999):
        self.rows = list(rows or [])
        self.new_id = new_id
        self.executed = []
        self._result = None

    def execute(self, sql, params=None):
        flat = " ".join(str(sql).split())
        self.executed.append((flat, params))
        if "INSERT INTO agents" in flat:
            self._result = {"id": self.new_id}
            return
        if "FROM agents" in flat:
            needle = (params or ("",))[0]
            if "replace(lower(name), '.', '')" in flat:
                hit = [r for r in self.rows if svc.normalized_agent_name(r["name"]) == needle]
            else:  # the pre-fix literal predicate
                hit = [r for r in self.rows if r["name"] == needle]
            self._result = hit[0] if hit else None
            return
        self._result = None

    def fetchone(self):
        return self._result

    @property
    def statements(self):
        return [sql for sql, _ in self.executed]

    def ran_insert(self):
        return any("INSERT INTO agents" in s for s in self.statements)


def _patch_db(cur):
    @contextmanager
    def _fake(*_a, **_k):
        yield (None, cur)

    return patch.object(svc, "get_db_cursor", _fake)


# --------------------------------------------------------------------------
# the normalizer
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("A.T.L.A.S.", "Atlas"),
        ("F.O.R.G.E.", "Forge"),
        ("C.O.D.E.X.", "codex"),
        ("H.A.V.E.N.", "Haven"),
        ("S.I.F.T.", "sift"),
    ],
)
def test_dotted_and_undotted_are_the_same_name(a, b):
    assert svc.normalized_agent_name(a) == svc.normalized_agent_name(b)
    # ...and a literal comparison — the thing being replaced — does NOT see it.
    assert a != b


@pytest.mark.parametrize(
    "a,b",
    [
        ("Wei Chen", "WeiChen"),  # spaces distinguish
        ("mp-expenses", "mpexpenses"),  # hyphens distinguish
        ("beat_worker", "beatworker"),  # underscores distinguish
        ("P.R.O.B.E.", "Probes"),  # not a prefix match
    ],
)
def test_normalization_is_narrow_and_does_not_overreach(a, b):
    """Over-eager folding would REJECT legitimate hires — worse than a twin."""
    assert svc.normalized_agent_name(a) != svc.normalized_agent_name(b)


def test_normalizer_tolerates_empty_and_none():
    assert svc.normalized_agent_name(None) == ""
    assert svc.normalized_agent_name("") == ""


def test_find_name_collision_queries_on_the_normalized_key():
    cur = FakeCursor([_ATLAS_ROW])
    got = svc.find_name_collision(cur, "A.T.L.A.S.")
    assert got == _ATLAS_ROW
    sql, params = cur.executed[0]
    assert "replace(lower(name), '.', '')" in sql
    assert params == ("atlas",)
    # every shift_state is searched — a retired agent still owns its name
    assert "shift_state" not in sql.split("WHERE")[1].split("ORDER BY")[0]


# --------------------------------------------------------------------------
# propose_hire — the friendly early check
# --------------------------------------------------------------------------


def _propose(name):
    return svc.propose_hire(
        name=name,
        display_name="Test Display",
        department="Engineering & Technology",
        model="mistral:7b",
        capability="code",
        reason="unit test",
    )


def test_propose_hire_blocks_a_dotted_twin():
    cur = FakeCursor(rows=[_ATLAS_ROW])
    with _patch_db(cur):
        out = _propose("A.T.L.A.S.")
    assert out["success"] is False
    assert "#17" in out["error"] and "Atlas" in out["error"]
    # the message must EXPLAIN the collision, or it reads as a false positive
    assert "same name" in out["error"]


def test_propose_hire_still_blocks_an_exact_duplicate():
    cur = FakeCursor(rows=[{"id": 136, "name": "F.O.R.G.E.", "shift_state": "active"}])
    with _patch_db(cur):
        out = _propose("F.O.R.G.E.")
    assert out["success"] is False
    assert "already exists" in out["error"]


def test_propose_hire_lets_a_clean_name_past_the_guard():
    cur = FakeCursor(rows=[_ATLAS_ROW])
    with _patch_db(cur):
        out = _propose("T.E.M.P.E.R.")
    # It may still fail later (request_approval is not stubbed here) — the point
    # is that it must not fail on the COLLISION guard.
    err = out.get("error", "")
    assert "collides" not in err and "already exists" not in err


# --------------------------------------------------------------------------
# create_agent — the choke point
# --------------------------------------------------------------------------


def _create(name, **kw):
    return svc.create_agent(name, "Test Display", "Engineering & Technology", "mistral:7b", **kw)


def test_create_agent_refuses_a_twin_and_writes_nothing():
    cur = FakeCursor(rows=[_ATLAS_ROW])
    with _patch_db(cur):
        with pytest.raises(ValueError) as exc:
            _create("A.T.L.A.S.")
    assert "#17" in str(exc.value)
    # fail CLOSED: the row must not be created
    assert not cur.ran_insert()


def test_create_agent_allows_a_clean_name():
    cur = FakeCursor(rows=[_ATLAS_ROW], new_id=999)
    with _patch_db(cur):
        assert _create("T.E.M.P.E.R.") == 999
    assert cur.ran_insert()


def test_create_agent_escape_hatch_is_explicit_only():
    """#376 'Codex' legitimately coexists with #146 'C.O.D.E.X.' — but on purpose."""
    cur = FakeCursor(rows=[{"id": 146, "name": "C.O.D.E.X.", "shift_state": "active"}], new_id=376)
    with _patch_db(cur):
        assert _create("Codex", allow_duplicate_name=True) == 376
    assert cur.ran_insert()


def test_create_agent_rejects_a_blank_name():
    cur = FakeCursor(rows=[])
    with _patch_db(cur):
        with pytest.raises(ValueError):
            _create("   ")
    assert not cur.ran_insert()


# --------------------------------------------------------------------------
# the guard must be load-bearing — a test that cannot fail is worse than none
# --------------------------------------------------------------------------


def test_guard_is_load_bearing_literal_comparison_lets_the_twin_through():
    """Reintroduce the defect (literal match) and prove the twin gets created.

    If someone reverts find_name_collision to `WHERE name = %s`, 'A.T.L.A.S.'
    stops matching 'Atlas', create_agent stops raising, and the INSERT happens —
    exactly the behaviour that produced agents #430 and #431. This test asserts
    that outcome against the OLD logic, so the guard's absence is detectable and
    the passing tests above are not vacuous.
    """

    def _literal_collision(cur, name):
        cur.execute("SELECT id, name, shift_state FROM agents WHERE name = %s LIMIT 1", (name,))
        return cur.fetchone()

    # a literal lookup finds nothing for 'A.T.L.A.S.' even though 'Atlas' exists
    cur = FakeCursor(rows=[_ATLAS_ROW], new_id=431)
    with _patch_db(cur), patch.object(svc, "find_name_collision", _literal_collision):
        created = _create("A.T.L.A.S.")
    assert created == 431
    assert cur.ran_insert(), "old behaviour must create the twin — else this proves nothing"
