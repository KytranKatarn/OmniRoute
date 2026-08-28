"""Tests for the Chronicle voice profile (#5644 slice 3).

Hermetic: no DB, no dispatch. The properties pinned here are the safety ones — a voice
profile is injected into DRAFTING prompts, so anything it carries can end up in real
outbound text.
"""

import services.chronicle_voice_service as V


# ---------------- the figures guard (constraint 1) ----------------
def test_figures_are_stripped_from_the_style_guide():
    """A figure in a style guide is either a fabrication waiting to be parroted, or it
    trips the no-fabrication validator (#4958) which fails CLOSED and burns the draft."""
    raw = {
        "tone": "wry, evidence-first",
        "vocabulary": [
            "plain civic language",
            "MP base salary is $203,100",  # a FACT — must go
            "cites the 2026 budget line of 25 BILLION",  # a FACT — must go
        ],
        "recurring_themes": "affordability and accountability",
    }
    got = V.coerce_style_guide(raw)
    assert got["tone"] == "wry, evidence-first"
    assert got["vocabulary"] == ["plain civic language"]
    blob = str(got)
    for leak in ("203,100", "$", "25 BILLION"):
        assert leak not in blob


def test_a_descriptor_that_is_entirely_factual_is_dropped_not_emptied():
    got = V.coerce_style_guide({"openers": ["$25B fund", "100% of the time"], "tone": "dry"})
    assert "openers" not in got  # nothing survived -> key omitted entirely
    assert got["tone"] == "dry"


def test_unknown_keys_are_dropped():
    """A closed schema stops a chatty model smuggling `talking_points` into a prompt."""
    got = V.coerce_style_guide({"tone": "dry", "talking_points": "carney is wrong", "recent_claims": ["x"]})
    assert set(got) == {"tone"}


def test_non_dict_and_empty_inputs_are_safe():
    assert V.coerce_style_guide(None) == {}
    assert V.coerce_style_guide("not json") == {}
    assert V.coerce_style_guide([1, 2]) == {}
    assert V.coerce_style_guide({}) == {}


# ---------------- loose JSON parsing ----------------
def test_parse_json_loose_handles_fences_and_padding():
    assert V.parse_json_loose('```json\n{"tone": "dry"}\n```') == {"tone": "dry"}
    assert V.parse_json_loose('Sure! {"tone": "dry"} hope that helps') == {"tone": "dry"}
    assert V.parse_json_loose('{"tone": "dry"}') == {"tone": "dry"}
    assert V.parse_json_loose("no json here") is None
    assert V.parse_json_loose("") is None


# ---------------- round-robin budget (constraint: every surface represented) ----------------
def test_round_robin_covers_every_folder_before_doubling_any():
    by_folder = {
        "posts": [{"text": "p" * 100} for _ in range(50)],
        "comments_own": [{"text": "c" * 100} for _ in range(3)],
        "profile": [{"text": "f" * 100}],
    }
    out = V._round_robin_budget(by_folder, total_budget=1000)
    folders = [next(k for k, v in by_folder.items() if item in v) for item in out]
    # The tiny folders must appear even though `posts` could fill the budget alone.
    assert "comments_own" in folders
    assert "profile" in folders


def test_round_robin_respects_the_total_budget():
    by_folder = {"a": [{"text": "x" * 400} for _ in range(10)]}
    out = V._round_robin_budget(by_folder, total_budget=1000)
    assert sum(len(i["text"]) for i in out) <= 1000


def test_round_robin_empty_input():
    assert V._round_robin_budget({}, 1000) == []
    assert V._round_robin_budget({"a": []}, 1000) == []


# ---------------- orchestrator: nothing is written unless it is good ----------------
# The dispatch contract is `queued_dispatch_text`: returns response TEXT, or None on hard
# failure / queued-task failure / poll timeout. It is NOT a DispatchResult — a bare
# `dispatch()` reports failure the moment a model is cold, which on this weekly cadence
# meant the profile would never be built (measured live 2026-08-16: qwen2.5:7b cold,
# warm_boot_ms 120000 -> deferred, written 0).
def _wire(monkeypatch, response, samples=20, entity=66):
    wrote = {}
    monkeypatch.setattr(V, "resolve_entity_id", lambda o, a: entity)
    monkeypatch.setattr(
        V,
        "gather_samples",
        lambda o, a, per_folder=40, **k: [{"folder": "linkedin/posts", "text": "t", "at": None}] * samples,
    )
    monkeypatch.setattr(V, "_dispatch_fn", lambda: (lambda **kw: response))
    monkeypatch.setattr(
        V,
        "upsert_voice_profile",
        lambda *a, **k: wrote.setdefault("called", True) or 1,
    )
    return wrote


def test_happy_path_writes_the_profile(monkeypatch):
    wrote = _wire(monkeypatch, '{"tone": "dry and direct"}')
    res = V.run_voice_profile_build()
    assert res["status"] == "ok"
    assert res["written"] == 1
    assert wrote.get("called")


def test_unresolved_entity_writes_nothing(monkeypatch):
    """Terry matches FIVE chronicle_entity rows on a fuzzy name; an ambiguous resolve must
    not attach his voice to an arbitrary duplicate."""
    wrote = _wire(monkeypatch, '{"tone": "dry"}', entity=None)
    res = V.run_voice_profile_build()
    assert res["status"] == "entity_unresolved"
    assert res["written"] == 0
    assert not wrote


def test_thin_corpus_writes_nothing(monkeypatch):
    wrote = _wire(monkeypatch, '{"tone": "dry"}', samples=3)
    res = V.run_voice_profile_build()
    assert res["status"] == "insufficient_samples"
    assert res["written"] == 0
    assert not wrote


def test_cold_model_defers_instead_of_overwriting(monkeypatch):
    """queued_dispatch_text returns None on failure/timeout -> leave yesterday's guide."""
    wrote = _wire(monkeypatch, None)
    res = V.run_voice_profile_build()
    assert res["status"] == "dispatch_unavailable"
    assert res["written"] == 0
    assert not wrote


def test_unusable_response_writes_nothing(monkeypatch):
    wrote = _wire(monkeypatch, "I'm sorry, I can't help with that.")
    res = V.run_voice_profile_build()
    assert res["status"] == "unusable_response"
    assert res["written"] == 0
    assert not wrote


def test_response_that_is_all_figures_writes_nothing(monkeypatch):
    """Scrubbing can empty a response completely — that is 'unusable', not 'a blank voice'."""
    wrote = _wire(monkeypatch, '{"tone": "quotes $203,100 often"}')
    res = V.run_voice_profile_build()
    assert res["status"] == "unusable_response"
    assert res["written"] == 0
    assert not wrote


def test_dispatch_exception_is_contained(monkeypatch):
    monkeypatch.setattr(V, "resolve_entity_id", lambda o, a: 66)
    monkeypatch.setattr(
        V,
        "gather_samples",
        lambda o, a, per_folder=40, **k: [{"folder": "f", "text": "t", "at": None}] * 20,
    )

    def boom(**kw):
        raise RuntimeError("dispatcher down")

    monkeypatch.setattr(V, "_dispatch_fn", lambda: boom)
    res = V.run_voice_profile_build()
    assert res["status"] == "dispatch_error"
    assert res["written"] == 0


# ---------------- prompt block ----------------
def test_prompt_block_is_empty_when_no_profile(monkeypatch):
    """Empty must mean 'fall back to the existing hardcoded voice hints', never
    'this person has no voice' — so it is the empty STRING, not a placeholder."""
    monkeypatch.setattr(V, "resolve_entity_id", lambda o, a: None)
    assert V.voice_prompt_block() == ""


def test_prompt_block_rescrubs_on_read(monkeypatch):
    """A guide stored before the scrub existed, or hand-edited in the DB, must not reach a
    prompt carrying figures."""
    import services.chronicle_voice_service as M

    class _Cur:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return {"style_guide": {"tone": "dry", "vocabulary": ["says $9,000 a lot"]}}

    class _Ctx:
        def __enter__(self):
            return (None, _Cur())

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(M, "resolve_entity_id", lambda o, a: 66)
    monkeypatch.setitem(
        __import__("sys").modules,
        "database",
        type("m", (), {"get_db_cursor": staticmethod(lambda **k: _Ctx())}),
    )
    block = M.voice_prompt_block()
    assert "dry" in block
    assert "$9,000" not in block
    assert "style only" in block.lower()
