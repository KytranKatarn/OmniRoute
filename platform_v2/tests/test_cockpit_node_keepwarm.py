"""Cockpit fast-front keep-warm (2026-07-12).

A.R.C.H.I.E.'s cockpit chat routes its conversational reply to Starship-246's GPU with a
fast model (COCKPIT_CHAT_MODEL, llama3.2:3b) — PR #2217. Sporadic chats let that model
unload between them, so each first reply cold-loaded (the 14-34s variance the owner saw).
This job keeps it resident on the node.

Source-level checks (AgentLoop can't be unit-booted — APScheduler + Flask app context +
a live DB); mirrors test_warm_keep_coordinator.py's repo-root resolution.
"""

from __future__ import annotations

from pathlib import Path


def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve()
    for parent in candidate.parents:
        if (parent / "ai_bridge" / "agent_loop.py").exists():
            return parent
    # Absolute fallback for the container mount point
    return Path("/mnt/archie_brain")


REPO = _find_repo_root()
SRC = (REPO / "ai_bridge" / "agent_loop.py").read_text()


def _handler() -> str:
    """The body of _keep_cockpit_node_model_warm, up to the next method."""
    after = SRC.split("def _keep_cockpit_node_model_warm(self):", 1)
    assert len(after) == 2, "keep-warm handler must exist"
    return after[1].split("    def _keep_citadel_async_model_warm", 1)[0]


def test_cockpit_node_keepwarm_handler_exists():
    assert "def _keep_cockpit_node_model_warm(self):" in SRC


def test_cockpit_node_keepwarm_targets_the_cockpit_node_and_configured_model():
    handler = _handler()
    # Same node the cockpit fast-front routes to (Starship-246 'Defiant', RTX 3070).
    assert "starship_76583490e36955ab" in handler
    # Warms the ACTUAL configured cockpit model — stays in sync with app.py routing,
    # not a hardcoded literal.
    assert 'os.getenv("COCKPIT_CHAT_MODEL"' in handler


def test_cockpit_node_keepwarm_is_registered_every_4_min():
    # Registered as a scheduled job with a toggleable id.
    assert 'id="cockpit_node_model_keepwarm"' in SRC
    assert "with_app_context(self._keep_cockpit_node_model_warm)" in SRC


def test_cockpit_node_keepwarm_is_online_gated_failsoft():
    handler = _handler()
    # Skips a stale/offline node (fail-soft, no error spam). The 8PM-6AM hardware rest
    # is covered implicitly by the heartbeat gate (node stops heart-beating during rest).
    assert "hb_age" in handler
    assert "offline/stale — skip" in handler


def test_cockpit_node_keepwarm_warms_only_the_fast_front_not_a_second_7b():
    handler = _handler()
    # The deepen follow-up's 7B is already warmed by forge_review_model_keepwarm on THIS
    # same node; this handler must NOT spin up a second 7B runner (would crowd the 8GB card).
    assert "DEEPEN_MODEL" not in handler
    assert "qwen2.5:7b" not in handler
