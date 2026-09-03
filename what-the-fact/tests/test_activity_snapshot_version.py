"""Guards for the /activity snapshot's shape check.

⚠️ THE BUG THIS EXISTS FOR, and it shipped to production (KB #302073).

`/activity` serves most requests from a stored snapshot rather than recomputing.
PR #3083 added `agent_throughput` to the bundle, deployed cleanly — correct
code, correct template, query returning six rows, every route 200, no errors —
and the panel rendered NOTHING. The stored snapshot had been written by the
previous build and carried the older 12 keys. Every reader got the old shape.

The snapshot had no version stamp, so a snapshot written by older code was
indistinguishable from a current one, and the age check could never notice: it
WAS fresh. It only cleared when someone forced a recompute by hand.

Two things are pinned here:

  1. `read_snapshot(require_keys=...)` rejects a short snapshot as STALE, so the
     caller recomputes and the system heals on the first request.
  2. The required-key list cannot drift from the bundle the code actually
     builds. That second guard is the important one — a hand-maintained list of
     "what the bundle contains" is the same failure as the snapshot itself,
     one level up. It is derived from routes.py's own source here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ROUTES = ROOT / "consumer" / "routes.py"

pytest.importorskip("flask")


def _builder_keys() -> set[str]:
    """Every key the /activity bundle builder actually writes.

    Read from source rather than by calling the builder: the builder needs a
    populated database, and a guard that SKIPS without one would be no guard at
    all on the machine where it matters (the same reason the weather parsers are
    kept stdlib-only, KB #290497).

    Two shapes are collected — the `B = { ... }` literal, and any later
    `B["key"] = ...` assignment, which is exactly how `agent_throughput` is
    attached and therefore exactly the shape a naive parse would miss.
    """
    src = ROUTES.read_text(encoding="utf-8")
    body = src.split("    B = {", 1)[1]
    literal = body.split("\n    }", 1)[0]
    keys = set(re.findall(r'^\s*"([a-z_]+)":', literal, re.M))
    # `B["agent_throughput"] = ...` within the same function
    tail = body.split("\n    }", 1)[1].split("\n@", 1)[0]
    keys |= set(re.findall(r'^\s*B\["([a-z_]+)"\]\s*=', tail, re.M))
    # `computed_at` is stamped after the snapshot write and is deliberately not
    # part of the persisted contract.
    keys.discard("computed_at")
    return keys


def test_the_required_key_list_matches_what_the_builder_writes():
    """The guard that keeps the guard honest.

    If someone adds a key to the bundle and forgets the constant, the snapshot
    check silently stops covering the new key and #302073 recurs verbatim. This
    fails at that moment instead.
    """
    from consumer.routes import _ACTIVITY_SNAPSHOT_REQUIRED_KEYS

    declared = set(_ACTIVITY_SNAPSHOT_REQUIRED_KEYS)
    built = _builder_keys()
    assert built, "could not parse the bundle builder — fix this parse, not the assert"
    assert declared == built, (
        f"declared-but-not-built: {sorted(declared - built)}; "
        f"built-but-not-declared: {sorted(built - declared)}"
    )


def test_agent_throughput_is_covered():
    """The specific key whose absence was invisible in production."""
    from consumer.routes import _ACTIVITY_SNAPSHOT_REQUIRED_KEYS

    assert "agent_throughput" in _ACTIVITY_SNAPSHOT_REQUIRED_KEYS


# --------------------------------------------------------------------------
# read_snapshot's behaviour
# --------------------------------------------------------------------------


class _Row(dict):
    def mappings(self):  # emulate SQLAlchemy's .mappings().first()
        return self

    def first(self):
        return self


class _Conn:
    """Minimal stand-in — read_snapshot only ever calls conn.execute(...)."""

    def __init__(self, bundle, age_s=1.0):
        self._row = _Row(bundle=bundle, computed_at="2026-09-03T00:00:00Z", age_s=age_s)

    def execute(self, *_a, **_k):
        return self._row


FULL = {
    "source_count": 46, "stats": {"a": 1}, "trends": [], "beat_breakdown": [],
    "top_stories": [], "throughput_sparkline": [], "bias_spectrum": [],
    "llm_rate": 0, "geo_rate": 0, "sparklines": {}, "source_health": [],
    "newsroom": {}, "agent_throughput": [{"name": "V.E.R.I.F.Y."}],
}
REQUIRED = tuple(FULL)


def test_a_complete_snapshot_is_served():
    from consumer import activity_snapshot as snap

    got = snap.read_snapshot(_Conn(FULL), require_keys=REQUIRED)
    assert got is not None and got[0]["agent_throughput"]


def test_a_snapshot_from_an_older_build_is_refused():
    """The exact production shape: fresh, well-formed, one key short."""
    from consumer import activity_snapshot as snap

    old = {k: v for k, v in FULL.items() if k != "agent_throughput"}
    assert snap.read_snapshot(_Conn(old), require_keys=REQUIRED) is None


def test_without_require_keys_behaviour_is_unchanged():
    """Callers that pass nothing keep today's semantics exactly — the parameter
    must not become a silent behaviour change for other readers."""
    from consumer import activity_snapshot as snap

    old = {k: v for k, v in FULL.items() if k != "agent_throughput"}
    assert snap.read_snapshot(_Conn(old)) is not None


def test_age_still_wins_over_shape():
    """A stale-by-age snapshot is refused whether or not its keys are complete —
    the new check must not accidentally rescue an old one."""
    from consumer import activity_snapshot as snap

    assert snap.read_snapshot(_Conn(FULL, age_s=10**9), require_keys=REQUIRED) is None


def test_a_bundle_missing_stats_is_still_malformed():
    """The pre-existing guard must survive: `stats` absent would break the
    template, and that is a different failure from 'written by an old build'.

    ⚠️ require_keys is deliberately NOT passed. With it, this test passed even
    after the `stats` guard was deleted — because REQUIRED happens to contain
    "stats", the new check masked the old one and the test proved nothing.
    Exercising the old guard alone is the only way to pin it.
    """
    from consumer import activity_snapshot as snap

    broken = {k: v for k, v in FULL.items() if k != "stats"}
    assert snap.read_snapshot(_Conn(broken)) is None


def test_the_caller_actually_passes_require_keys():
    """⚠️ THE WIRING, not the mechanism.

    Removing `require_keys=` from the call site deactivates this entire fix and
    every other test here still passes — they exercise read_snapshot directly.
    A guard that exists but is not wired at the choke point is the recurring
    shape in this codebase (#5194, #5862, #6035): the fix is to WIRE it, and the
    test is to prove it stayed wired.
    """
    src = ROUTES.read_text(encoding="utf-8")
    call = src.split("_snap.read_snapshot(", 1)
    assert len(call) > 1, "routes.py no longer calls read_snapshot at all"
    assert "require_keys=_ACTIVITY_SNAPSHOT_REQUIRED_KEYS" in call[1][:200], (
        "read_snapshot is called WITHOUT require_keys — a stale-shaped snapshot "
        "would be served again (KB #302073)")
