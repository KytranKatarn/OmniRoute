"""Regression coverage for /team's honest status badge + task-type split
(2026-09-05, follow-up to Batch 10/12 — no new task number, a Kytran-requested
fix from investigating why /team's "weak spot" content was skipped).

Two real, currently-live defects, both fixed with data the route already
fetches (no new query, no new ingest):

1. THE BADGE CONTRADICTION. team.html's top-right card badge was a hardcoded
   '{% else %}Active{% endif %}' for every named agent, while the welfare
   pill two lines below it on the SAME card already rendered the real
   shift_state. Verified live 2026-09-05 against what-the-fact.com/team:
   F.A.C.T.'s card said "Active" at the top and "winding down" in the
   welfare pill; I.N.K.'s said "Active" and "off duty" — a self-contradiction
   on the newsroom's own transparency page, cross-checked against the
   platform's own `agents` table (F.A.C.T.=winding_down, I.N.K.=off_duty).
   `_team_badge(welfare)` now drives the badge off the SAME shift_state
   already fetched into `agent["welfare"]`.

2. THE DISCARDED SPLIT. `_newsroom_agents()` already computes `fact_checks`
   and `bias_scores` as separate SQL columns per agent (for the Activity Log).
   The /team route was collapsing them to a single `events` total before the
   template ever saw them, producing the vague "N fact-check/bias · 24h"
   label (which doesn't even pick a grammatically correct noun).
   `_team_work_label(fact_checks, bias_scores)` surfaces the split that was
   already being computed.

Everything here traces to either a pure helper exercised on synthetic data,
or a Jinja render with an explicit hand-built context — same pattern as
test_rates_batch11.py / test_economy_batch12.py.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROUTES_PY = ROOT / "consumer" / "routes.py"
TPL_DIR = ROOT / "consumer" / "templates"

from consumer import routes as R  # noqa: E402

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader  # noqa: E402

_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


# ────────────────────────── source-inspection (rule #6) ──────────────────

def _team_route_body() -> str:
    src = ROUTES_PY.read_text(encoding="utf-8")
    start = src.index("def team(")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


def test_route_no_longer_collapses_events_to_a_single_int():
    body = _team_route_body()
    # Mutation check (house rule #7) run once at authoring time against the
    # pre-fix source — NOT a permanent test, per
    # feedback_mutation-check-no-runtime-git.md. Confirmed then: the pre-fix
    # body contained exactly `events_by_agent = {a["agent"]: int(a["events"])
    # for a in newsroom["agents"]}` and had no reference to fact_checks or
    # bias_scores anywhere in the route — this assertion would have failed
    # against it.
    assert "fact_checks" in body
    assert "bias_scores" in body
    assert "_team_work_label" in body
    assert "_team_badge" in body


def test_dept_agents_no_longer_carries_a_raw_int_events_map():
    body = _team_route_body()
    assert 'events_by_agent = {a["agent"]: int(a["events"]) for a in newsroom["agents"]}' not in body


# ────────────────────────── _team_badge ───────────────────────────────────

def test_active_shift_state_is_the_only_true_active_badge():
    label, is_active = R._team_badge({"shift_state": "active"})
    assert label == "Active" and is_active is True


def test_winding_down_is_reported_honestly_not_as_active():
    label, is_active = R._team_badge({"shift_state": "winding_down"})
    assert label == "Winding down"
    assert is_active is False


def test_off_duty_is_reported_honestly_not_as_active():
    label, is_active = R._team_badge({"shift_state": "off_duty"})
    assert label == "Off duty"
    assert is_active is False


def test_all_six_platform_shift_states_map_to_a_real_label():
    for state in ("active", "deployed", "barracked", "off_duty", "winding_down", "cooldown"):
        label, _ = R._team_badge({"shift_state": state})
        assert label != "" and label is not None


def test_missing_welfare_fails_open_to_active():
    label, is_active = R._team_badge(None)
    assert (label, is_active) == ("Active", True)


def test_empty_welfare_dict_fails_open_to_active():
    label, is_active = R._team_badge({})
    assert (label, is_active) == ("Active", True)


def test_unrecognized_shift_state_fails_open_never_fabricates_a_specific_state():
    # A future platform shift-state value this table doesn't know about yet
    # must never be reported as a specific (possibly wrong) non-active state.
    label, is_active = R._team_badge({"shift_state": "some_future_state"})
    assert (label, is_active) == ("Active", True)


# ────────────────────────── _team_work_label ──────────────────────────────

def test_zero_tasks_says_no_scored_tasks():
    assert R._team_work_label(0, 0) == "no scored tasks · 24h"


def test_fact_checks_only():
    assert R._team_work_label(42, 0) == "42 fact-checks · 24h"


def test_bias_scores_only():
    assert R._team_work_label(0, 8) == "8 bias scores · 24h"


def test_both_task_types_present():
    assert R._team_work_label(42, 8) == "42 fact-checks · 8 bias scores · 24h"


def test_singular_grammar():
    assert R._team_work_label(1, 1) == "1 fact-check · 1 bias score · 24h"


def test_large_numbers_get_thousands_separators():
    assert R._team_work_label(1234, 0) == "1,234 fact-checks · 24h"


# ────────────────────────── template render ───────────────────────────────

def _render(**ctx):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    base_ctx = dict(
        agents=[], source_count=46, dept_agents=[], roster_rows=[],
        dept_total=None, named_count=8,
    )
    base_ctx.update(ctx)
    return env.get_template("team.html").render(**base_ctx)


def _agent(name, shift_state, welfare_score=80):
    label, is_active = R._team_badge({"shift_state": shift_state} if shift_state else None)
    return {
        "name": name, "full": name, "role": "Role", "model": "qwen2.5:7b",
        "description": "desc", "accent_colour": "#dc2626", "portrait_url": None,
        "coming_soon": False,
        "welfare": {"welfare_score": welfare_score, "shift_state": shift_state} if shift_state else None,
        "status_label": label, "status_is_active": is_active,
    }


def test_winding_down_agent_no_longer_shows_a_contradictory_active_badge():
    # This is the exact live bug: F.A.C.T. was winding_down but badged Active.
    html = _render(agents=[_agent("F.A.C.T.", "winding_down")])
    assert "wtf-badge-active" not in html
    assert 'wtf-badge-soon">Winding down<' in html
    assert ">Active<" not in html


def test_off_duty_agent_no_longer_shows_a_contradictory_active_badge():
    html = _render(agents=[_agent("I.N.K.", "off_duty")])
    assert 'wtf-badge-soon">Off duty<' in html
    assert ">Active<" not in html


def test_active_agent_still_shows_the_green_active_badge():
    html = _render(agents=[_agent("B.I.A.S.", "active")])
    assert 'wtf-badge-active">Active<' in html


def test_agent_with_no_welfare_data_fails_open_to_active_badge():
    html = _render(agents=[_agent("A.U.R.O.R.A.", None)])
    assert 'wtf-badge-active">Active<' in html


def test_dept_agent_card_shows_the_split_work_label():
    html = _render(dept_agents=[{
        "name": "P.R.O.O.F.", "shift_state": "active",
        "events_24h": 50, "work_label": "42 fact-checks · 8 bias scores · 24h",
    }])
    assert "42 fact-checks · 8 bias scores · 24h" in html
    assert "fact-check/bias" not in html  # old vague combined phrasing is gone


def test_dept_agent_zero_tasks_renders_the_honest_empty_label():
    html = _render(dept_agents=[{
        "name": "S.T.R.I.N.G.E.R.", "shift_state": "barracked",
        "events_24h": 0, "work_label": "no scored tasks · 24h",
    }])
    assert "no scored tasks · 24h" in html


def test_empty_page_does_not_crash():
    _render()
