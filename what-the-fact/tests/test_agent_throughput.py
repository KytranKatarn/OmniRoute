"""Guards for the /activity per-agent throughput strip (newsroom rebuild, Phase 2).

Both tests below exist because the bug they describe actually happened while
building this, and neither would have been caught by "does the page return 200"
— the page returned 200 the whole time, with the panel silently absent.

1. ORDERING. `agent_throughput` was first added to the bundle AFTER
   `write_snapshot()`. Most requests are served from that stored snapshot rather
   than from a fresh compute, so the key was persisted by nobody and the panel
   rendered its empty state forever while the code that fills it looked correct.

2. CONTEXT. `activity()` enumerates its template context keys, so a bundle key
   that is not listed in the `render_template` call reaches the template as
   Undefined — which is falsy, so `{% if agent_throughput %}` silently skips.
   The route already carries a comment warning about exactly this.

The third test pins the honesty property that motivated the whole design.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "consumer" / "routes.py").read_text()
TEMPLATE = (ROOT / "consumer" / "templates" / "activity.html").read_text()


# --------------------------------------------------------------------------
# The two bugs
# --------------------------------------------------------------------------


def test_throughput_is_computed_before_the_snapshot_is_written():
    """A key added after write_snapshot() is never persisted, so every request
    served from the snapshot renders the empty state."""
    set_at = ROUTES.index('B["agent_throughput"] = _activity_agent_throughput')
    write_at = ROUTES.index("_snap.write_snapshot(")
    assert set_at < write_at, (
        "agent_throughput must be set BEFORE write_snapshot — otherwise the "
        "stored snapshot omits it and the panel is permanently empty"
    )


def test_throughput_is_passed_explicitly_to_the_template():
    """This route enumerates its context keys; an unlisted bundle key is
    Undefined in the template, which is falsy and skips the panel."""
    assert 'agent_throughput=B.get("agent_throughput") or []' in ROUTES


# --------------------------------------------------------------------------
# The honesty property
# --------------------------------------------------------------------------


def test_the_window_is_measured_not_assumed():
    """GREATEST(now()-24h, min(col)) is what makes a young column honest.

    `geo_processed_at` shipped today and is deliberately not backfilled, so
    L.O.C.A.L. had 509 events in a window labelled 24h while the column was 4.7h
    old. Beside V.E.R.I.F.Y.'s 8,133 that reads as "16x slower" when L.O.C.A.L.
    is in fact third-fastest by rate. Hardcoding 24 here reintroduces exactly
    that lie.
    """
    assert "GREATEST(now() - interval '24 hours', min(" in ROUTES


def test_a_short_window_is_flagged_to_the_reader():
    assert "partial" in ROUTES
    assert "short window" in TEMPLATE


def test_the_headline_number_is_a_rate_not_a_count():
    """Counts over unequal windows are not comparable; rates are. The big
    number in the card must be per_hour, with the raw count demoted to context.
    """
    card = TEMPLATE[TEMPLATE.index("Throughput now") : TEMPLATE.index("Throughput now") + 2200]
    big = re.search(r'font-size:1\.32rem[^>]*>\{\{\s*([a-z_.]+)', card)
    assert big, "could not find the card's headline number"
    assert big.group(1) == "a.per_hour", f"headline is {big.group(1)}, must be the rate"


def test_invented_metrics_are_not_rendered():
    """The design prototype carries model name, average duration and a per-agent
    target as sample constants. The first two live in another database; a target
    is a policy nobody has set. Rendering them here would put fabricated figures
    on the page whose subject is how honestly this newsroom reports itself.
    """
    card = TEMPLATE[TEMPLATE.index("Throughput now") : TEMPLATE.index("Throughput now") + 2200]
    for invented in ("target", "avg_duration", "model_name"):
        assert invented not in card, f"{invented} is not measurable here"


# --------------------------------------------------------------------------
# Separation from the coverage grid
# --------------------------------------------------------------------------


def test_the_strip_uses_the_canonical_paywall_macro():
    """Not a hand-rolled block. `paywall()`'s own comment in _archetypes.html
    records this exact four-part block being duplicated across 14 templates and
    drifting to four different CTA colours, not one of them --wtf-accent."""
    assert '{% from "_archetypes.html" import paywall %}' in TEMPLATE
    head = TEMPLATE[: TEMPLATE.index("Pipeline health bar")]
    assert "paywall(" in head, "the strip must offer the paywall, not vanish"


def test_the_strip_gates_itself_rather_than_riding_the_blanket_gate():
    """Inside the blanket `{% if is_subscriber %}` a signed-out reader saw the
    panel silently absent — indistinguishable from "the agents did no work".
    Self-gating is what lets it show a paywall instead of nothing."""
    assert "{% if agent_throughput and is_subscriber %}" in TEMPLATE
    # …and it sits ABOVE the blanket gate, or the else-branch is unreachable.
    assert TEMPLATE.index("agent_throughput and is_subscriber") < TEMPLATE.index(
        "Pipeline health bar"
    )


def test_the_paywall_returns_the_reader_to_this_page():
    """A CTA that drops you on the homepage after signing in loses the intent."""
    head = TEMPLATE[: TEMPLATE.index("Pipeline health bar")]
    assert "'/activity'" in head or '"/activity"' in head


def test_throughput_and_coverage_stay_separate():
    """Coverage answers 'how much of the corpus has this agent ever touched';
    throughput answers 'is it working right now'. A stalled agent can show 99%
    coverage, so blending them into one number hides the failure."""
    assert "Throughput now" in TEMPLATE
    # the pre-existing coverage grid is still there, not replaced
    assert "stats.bias_scored" in TEMPLATE
