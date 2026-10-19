"""Warm-up runs once per cluster start and does not retry a deterministic refusal (#7328)."""

from __future__ import annotations

import ast
import time
from pathlib import Path

from services.model_service import ModelService
from services.warmup_claim import DEFAULT_TTL_SECONDS, _bounded_ttl, claim_warmup

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text()


def _fn_src(name):
    tree = ast.parse(APP)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(APP, fn)


def test_the_claim_winner_warms_up_and_the_others_skip():
    holders = []

    def claim(h):
        holders.append(h)
        return len(holders) == 1  # only the first caller wins

    assert claim_warmup(claim=claim, holder="w1") is True
    assert claim_warmup(claim=claim, holder="w2") is False
    assert claim_warmup(claim=claim, holder="w3") is False
    assert holders == ["w1", "w2", "w3"]


def test_claim_fails_open_on_db_error():
    def boom(_h):
        raise RuntimeError("db down")

    assert claim_warmup(claim=boom) is True  # the old behaviour: warm up anyway


def test_ttl_is_bounded_and_defaults_safely():
    assert _bounded_ttl(None) == DEFAULT_TTL_SECONDS
    assert _bounded_ttl("junk") == DEFAULT_TTL_SECONDS
    assert _bounded_ttl(1) == 30  # floor: a 1s TTL would let the other workers through
    assert _bounded_ttl(10**6) == 1800


def test_app_checks_the_claim_before_starting_the_warmup_thread():
    src = _fn_src("_warmup_ollama_models")
    assert src.index("claim_warmup()") < src.index("threading.Thread(")
    assert "if not claim_warmup():" in src


def test_warmup_does_not_retry_a_refusal():
    src = _fn_src("_warmup_ollama_models")
    assert "model_svc.was_load_refused(model_name)" in src
    assert src.index("was_load_refused(") < src.index("load failed, retry")


def _svc():
    svc = object.__new__(ModelService)  # skip __init__: no Ollama/DB needed
    svc._load_refused = {}
    return svc


def test_was_load_refused_window():
    svc = _svc()
    assert svc.was_load_refused("gemma3:12b") is False
    svc._load_refused["gemma3:12b"] = time.time()
    assert svc.was_load_refused("gemma3:12b") is True
    svc._load_refused["gemma3:12b"] = time.time() - 120
    assert svc.was_load_refused("gemma3:12b") is False  # stale refusal must not suppress a later retry
    assert svc.was_load_refused("other:7b") is False


def test_load_model_records_the_refusal():
    src = (ROOT / "services/model_service.py").read_text()
    body = src.split("REFUSING hub CPU load", 1)[1].split("return False", 1)[0]
    assert "self._load_refused[model] = time.time()" in body
