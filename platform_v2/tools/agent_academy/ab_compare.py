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
