"""Pure logic for the Cloud Comparison Lane (#4661). No I/O — unit-testable."""

from __future__ import annotations
import json
import re

_CLOUD_PREFIX = "provider:"
_EXPIRE_SECONDS = 24 * 3600


def parse_model_selection(value: str) -> dict:
    """'qwen2.5:7b' -> local; 'provider:<key>:<model>' -> cloud (model may contain colons)."""
    value = (value or "").strip()
    if value.startswith(_CLOUD_PREFIX):
        rest = value[len(_CLOUD_PREFIX) :]
        provider, _, model = rest.partition(":")  # split on FIRST colon only
        return {"kind": "cloud", "provider": provider, "model": model}
    return {"kind": "local", "provider": None, "model": value}


def classify_run(sel_a: dict, sel_b: dict) -> dict:
    providers: list[str] = []
    for sel in (sel_a, sel_b):
        if sel.get("kind") == "cloud" and sel.get("provider") not in providers:
            providers.append(sel["provider"])
    return {"has_cloud": bool(providers), "cloud_providers": providers}


# ---------------------------------------------------------------------------
# The NODE axis (#383 slice 1 / revives #825)
#
# WHY. Until now a side of an A/B run was just a model name, and the model list
# came from the HUB's Ollama only. That makes two questions impossible to ask,
# and they are the two the calibration program exists to answer:
#   * "same capability, different MODEL"    — needs models the hub may not hold
#   * "same MODEL, different HARDWARE"      — needs a node per side
#
# The second one is not hypothetical. `gemma3:12b` measures 35% on the hub and
# 95% on USS-246 across 2,918 runs. Collapsing that to one fleet-wide average
# (56%) is how the model blocklist got seeded and reversed the same day
# (fleet.md 2026-08-21). A "winner" is the TUPLE (capability, model, node, tier)
# — never a bare model name.
# ---------------------------------------------------------------------------


def normalize_side(model: str, node: str | None = None) -> dict:
    """One side of a run: the model selection plus WHERE it should execute.

    `node` is a hint, not a guarantee — it becomes `preferred_node` at dispatch,
    and the dispatcher may place elsewhere (capacity, presence, welfare). So the
    node RECORDED with a result must be the node that actually ran it, read back
    after the fact, not this request. Storing the request as if it were the
    outcome is how a placement finding becomes fiction.

    Cloud sides have no node: a provider's hardware is not ours to choose. Any
    node passed alongside a cloud model is dropped rather than silently kept,
    so it cannot later read as a placement claim we never made.
    """
    sel = parse_model_selection(model)
    sel["node"] = (node or "").strip() or None if sel["kind"] == "local" else None
    return sel


def side_label(sel: dict) -> str:
    """Human/storage label — 'qwen2.5:7b @ USS-246', 'openai:gpt-4o-mini'."""
    if sel.get("kind") == "cloud":
        return f"{sel.get('provider') or '?'}:{sel.get('model') or '?'}"
    node = sel.get("node")
    return f"{sel.get('model') or '?'}" + (f" @ {node}" if node else "")


def comparison_kind(sel_a: dict, sel_b: dict) -> str:
    """What is this run actually measuring?

    Model choice and placement are SEPARATE questions and must be reported
    separately — reporting a placement result as a model verdict is exactly the
    error the blocklist reversal came from.

      'placement' — same model, different node. The answer is about HARDWARE.
      'model'     — different models. The answer is about the MODEL.
      'mixed'     — different model AND different node. Two variables at once,
                    so NEITHER conclusion is clean; the UI should say so rather
                    than pick one. Deliberately not silently called 'model'.
      'identical' — same model, same node. A noise/repeatability probe, which is
                    a legitimate thing to run and a useless thing to mislabel.
    """
    same_model = (sel_a.get("model") or "") == (sel_b.get("model") or "")
    same_kind = sel_a.get("kind") == sel_b.get("kind")
    same_node = sel_a.get("node") == sel_b.get("node")
    if same_model and same_kind:
        return "identical" if same_node else "placement"
    return "model" if same_node else "mixed"


def build_judge_prompt(prompt: str, resp_a: str, resp_b: str) -> str:
    return (
        "You are an impartial evaluator. Given a user PROMPT and two answers "
        "(A and B), score each 0-100 on accuracy, completeness, and clarity, then "
        "pick the better answer. Respond with ONLY a JSON object of the form "
        '{"score_a": <int>, "score_b": <int>, "winner": "a"|"b"|"tie", "rationale": "<one sentence>"}.\n\n'
        f"PROMPT:\n{prompt}\n\nANSWER A:\n{resp_a}\n\nANSWER B:\n{resp_b}\n"
    )


def _clamp_score(v) -> int | None:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return None


def _extract_judge_json(raw: str):
    """First JSON object that looks like a judge verdict; scans from each '{'."""
    text = re.sub(r"```(?:json)?", "", raw or "")
    decoder = json.JSONDecoder()
    first_dict = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, i)
        except ValueError:
            continue
        if isinstance(obj, dict):
            if first_dict is None:
                first_dict = obj
            if "winner" in obj or "score_a" in obj:
                return obj
    return first_dict


def parse_judge_result(raw: str) -> dict:
    raw = raw or ""
    data = _extract_judge_json(raw)
    if data is not None:
        winner = str(data.get("winner", "")).strip().lower()
        if winner not in ("a", "b", "tie"):
            winner = None
        return {
            "score_a": _clamp_score(data.get("score_a")),
            "score_b": _clamp_score(data.get("score_b")),
            "winner": winner,
            "rationale": str(data.get("rationale", ""))[:500],
        }
    return {"score_a": None, "score_b": None, "winner": None, "rationale": raw[:500]}


def decide_worker_action(approval_status: str, age_seconds: float) -> str:
    """Resolve a pending run's approval into an action for the worker."""
    if approval_status == "approved":
        return "run"
    if approval_status in ("rejected", "timeout", "expired"):
        return "cancel"
    if age_seconds > _EXPIRE_SECONDS:  # pending too long -> expired
        return "cancel"
    return "skip"
