"""Regression coverage for /team's "weak spot" feature (2026-09-05).

Follow-up to the investigation that found this field had NEVER existed
anywhere on the platform — not a code bug, no data source, not even in the
design mockup's own backing data (its own comment admits "Weaknesses are
ours", i.e. invented for the mockup). Kytran chose (brainstorm session,
2026-09-05): he hand-writes a short honest line for the 7 agents with no
derivable metric, stored as an optional `weak_spot`/`weak_spot_href` field
on their TEAM_AGENTS dict entry (no key = no line, never a placeholder);
A.U.R.O.R.A. is the one exception — a real, self-updating line computed
from the SAME forecast-verification data /weather/accuracy already
publishes, since a real metric exists for it and doesn't for the other 7.

2026-09-05 follow-up: Kytran asked for the other 7 lines too. Checking
first (rather than just writing them) turned up a SECOND real signal —
V.E.R.I.F.Y.'s own verdict distribution (89.1% "unverified" of 429,804
fact-checks, live-measured) — almost exactly what the design mockup
GUESSED ("declines more claims than it checks") without ever measuring it.
That one is now computed too, same pattern as A.U.R.O.R.A., no href (no
public page currently shows this aggregate — /claims reads a different
table, claim_tracker, not fact_checks).

Everything here traces to either a pure helper on synthetic data, or a
Jinja render with an explicit hand-built context — same pattern as the
other /team test files.
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


def test_aurora_has_no_static_weak_spot_key_in_team_agents():
    # Mutation check (house rule #7) run once at authoring time — NOT a
    # permanent test, per feedback_mutation-check-no-runtime-git.md. Before
    # this change, TEAM_AGENTS had no weak_spot concept at all for any
    # agent; this assertion (and the two below) would all have failed
    # against that pre-fix source.
    src = ROUTES_PY.read_text(encoding="utf-8")
    ta_start = src.index("TEAM_AGENTS = [")
    ta_end = src.index("\n\n\ndef ", ta_start)
    aurora_start = src.index('"name": "A.U.R.O.R.A."', ta_start, ta_end)
    aurora_end = src.index("},", aurora_start)
    aurora_block = src[aurora_start:aurora_end]
    assert "weak_spot" not in aurora_block


def test_route_computes_aurora_weak_spot_from_real_data():
    body = _team_route_body()
    assert "_aurora_team_weak_spot" in body
    assert '"A.U.R.O.R.A."' in body


def test_route_guards_the_aurora_query_with_try_except():
    body = _team_route_body()
    idx = body.index("_aurora_team_weak_spot(c, S)")  # the call, not the docstring mention
    assert "try:" in body[max(0, idx - 200):idx]


# ────────────────────────── _aurora_weak_spot_text ────────────────────────

def test_uses_the_longest_lead_not_a_plain_average():
    summary = {"longest_mae_c": 2.14, "longest_lead_days": 6}
    text = R._aurora_weak_spot_text(summary)
    assert "2.14" in text
    assert "6 days" in text


def test_none_when_no_data_yet():
    assert R._aurora_weak_spot_text({"longest_mae_c": None, "longest_lead_days": None}) is None


def test_none_when_only_one_field_present():
    # Defensive: a summary shape that changes upstream must fail closed to
    # "no line" rather than render "Off by an average of None°C".
    assert R._aurora_weak_spot_text({"longest_mae_c": 2.1, "longest_lead_days": None}) is None
    assert R._aurora_weak_spot_text({"longest_mae_c": None, "longest_lead_days": 6}) is None


def test_never_fabricates_a_zero_when_data_is_missing():
    text = R._aurora_weak_spot_text({})
    assert text is None


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


def _agent(name, weak_spot=None, weak_spot_href=None):
    return {
        "name": name, "full": name, "role": "Role", "model": "qwen2.5:7b",
        "description": "desc", "accent_colour": "#dc2626", "portrait_url": None,
        "coming_soon": False, "welfare": None,
        "status_label": "Active", "status_is_active": True,
        "weak_spot": weak_spot, "weak_spot_href": weak_spot_href,
    }


def test_hand_written_weak_spot_renders():
    html = _render(agents=[_agent(
        "B.I.A.S.", weak_spot="Less reliable on French-language and small-market outlets.",
    )])
    assert "Weak spot:" in html
    assert "Less reliable on French-language and small-market outlets." in html


def test_no_weak_spot_key_renders_no_line_not_a_placeholder():
    html = _render(agents=[_agent("D.R.A.F.T.")])
    assert "Weak spot:" not in html


def test_weak_spot_href_renders_a_details_link():
    html = _render(agents=[_agent(
        "A.U.R.O.R.A.",
        weak_spot="Off by an average of 2.14°C at its longest forecast lead (6 days out).",
        weak_spot_href="/weather/accuracy",
    )])
    assert 'href="/weather/accuracy"' in html
    assert "2.14" in html


def test_weak_spot_without_href_has_no_link():
    import re
    html = _render(agents=[_agent("I.N.K.", weak_spot="Can join two stories that are not the same story.")])
    block = re.search(r'<div class="wtf-team-weak">.*?</div>', html, re.S)
    assert block is not None
    assert "Weak spot:" in block.group(0)
    assert "<a href=" not in block.group(0)  # the footer's own link is elsewhere on the page


def test_multiple_agents_mixed_weak_spot_presence():
    html = _render(agents=[
        _agent("F.A.C.T."),  # no weak_spot yet — nothing renders
        _agent("B.I.A.S.", weak_spot="Real text."),
    ])
    assert html.count("Weak spot:") == 1
    assert "Real text." in html


# ────────────────────────── _verify_weak_spot_text ────────────────────────

def test_verify_uses_the_real_measured_percentage():
    counts = {"unverified": 382875, "true": 39235, "mixed": 4203, "false": 2326, "mostly_true": 1165}
    text = R._verify_weak_spot_text(counts)
    assert "89%" in text
    assert "unverified" in text


def test_verify_none_when_no_fact_checks_at_all():
    assert R._verify_weak_spot_text({}) is None


def test_verify_rounds_to_whole_percent():
    text = R._verify_weak_spot_text({"unverified": 1, "true": 2})
    assert "33%" in text


def test_verify_route_computes_from_real_data():
    body = _team_route_body()
    assert "_verify_team_weak_spot(c, S)" in body
    idx = body.index("_verify_team_weak_spot(c, S)")
    assert "try:" in body[max(0, idx - 200):idx]


def test_verify_has_no_static_weak_spot_key_in_team_agents():
    src = ROUTES_PY.read_text(encoding="utf-8")
    ta_start = src.index("TEAM_AGENTS = [")
    ta_end = src.index("\n\n\ndef ", ta_start)
    verify_start = src.index('"name": "V.E.R.I.F.Y."', ta_start, ta_end)
    verify_end = src.index("},", verify_start)
    assert "weak_spot" not in src[verify_start:verify_end]


def test_verify_weak_spot_renders_with_no_link():
    import re
    html = _render(agents=[_agent(
        "V.E.R.I.F.Y.",
        weak_spot="Declines to verify roughly 89% of the claims it checks — a claim without a primary document stays unverified.",
    )])
    block = re.search(r'<div class="wtf-team-weak">.*?</div>', html, re.S)
    assert block is not None
    assert "89%" in block.group(0)
    assert "<a href=" not in block.group(0)
