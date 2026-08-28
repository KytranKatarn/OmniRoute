from __future__ import annotations
from tools.agent_academy.ab_compare import (
    parse_model_selection,
    classify_run,
    build_judge_prompt,
    parse_judge_result,
    decide_worker_action,
)


def test_parse_local_model_with_colon():
    # local ollama tags contain a colon and must NOT be read as cloud
    assert parse_model_selection("qwen2.5:7b") == {"kind": "local", "provider": None, "model": "qwen2.5:7b"}


def test_parse_cloud_model_splits_on_first_colon_only():
    # model name may itself contain colons/slashes/dashes
    assert parse_model_selection("provider:groq:llama-3.3-70b-versatile") == {
        "kind": "cloud",
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
    }


def test_parse_cloud_proxy_model_with_colon_suffix():
    assert parse_model_selection("provider:minimax_cloud:minimax-m2.5:cloud") == {
        "kind": "cloud",
        "provider": "minimax_cloud",
        "model": "minimax-m2.5:cloud",
    }


def test_classify_both_local():
    a = parse_model_selection("qwen2.5:7b")
    b = parse_model_selection("mistral:7b")
    assert classify_run(a, b) == {"has_cloud": False, "cloud_providers": []}


def test_classify_one_cloud():
    a = parse_model_selection("qwen2.5:7b")
    b = parse_model_selection("provider:groq:llama-3.3-70b")
    assert classify_run(a, b) == {"has_cloud": True, "cloud_providers": ["groq"]}


def test_classify_two_cloud_dedups_providers():
    a = parse_model_selection("provider:groq:m1")
    b = parse_model_selection("provider:groq:m2")
    assert classify_run(a, b) == {"has_cloud": True, "cloud_providers": ["groq"]}


def test_build_judge_prompt_contains_both_answers_and_prompt():
    p = build_judge_prompt("What is 2+2?", "four", "4")
    assert "What is 2+2?" in p and "four" in p and "4" in p and "JSON" in p


def test_parse_judge_result_clean_json():
    raw = '{"score_a": 80, "score_b": 95, "winner": "b", "rationale": "B is more precise"}'
    assert parse_judge_result(raw) == {"score_a": 80, "score_b": 95, "winner": "b", "rationale": "B is more precise"}


def test_parse_judge_result_json_embedded_in_prose():
    raw = 'Here is my assessment:\n{"score_a": 50, "score_b": 50, "winner": "tie", "rationale": "equal"}\nDone.'
    out = parse_judge_result(raw)
    assert out["winner"] == "tie" and out["score_a"] == 50


def test_parse_judge_result_clamps_and_defaults_on_garbage():
    out = parse_judge_result("the model refused to answer")
    assert out == {"score_a": None, "score_b": None, "winner": None, "rationale": "the model refused to answer"[:500]}


def test_parse_judge_result_clamps_out_of_range_scores():
    raw = '{"score_a": 130, "score_b": -5, "winner": "x", "rationale": "r"}'
    out = parse_judge_result(raw)
    assert out["score_a"] == 100 and out["score_b"] == 0 and out["winner"] is None  # invalid winner -> None


def test_parse_judge_result_skips_decoy_json_block():
    raw = (
        '{"note": "thinking..."}\nFinal verdict:\n{"score_a": 70, "score_b": 60, "winner": "a", "rationale": "A wins"}'
    )
    out = parse_judge_result(raw)
    assert out["score_a"] == 70 and out["score_b"] == 60 and out["winner"] == "a"


def test_parse_judge_result_strips_markdown_fences():
    raw = '```json\n{"score_a": 80, "score_b": 90, "winner": "b", "rationale": "r"}\n```'
    out = parse_judge_result(raw)
    assert out["winner"] == "b" and out["score_a"] == 80


def test_parse_judge_result_case_folds_winner():
    raw = '{"score_a": 50, "score_b": 50, "winner": "Tie", "rationale": "equal"}'
    assert parse_judge_result(raw)["winner"] == "tie"


def test_classify_two_different_cloud_providers_order_preserved():
    a = parse_model_selection("provider:groq:m1")
    b = parse_model_selection("provider:openai:m2")
    assert classify_run(a, b) == {"has_cloud": True, "cloud_providers": ["groq", "openai"]}


def test_decide_worker_action():
    assert decide_worker_action("approved", 10) == "run"
    assert decide_worker_action("rejected", 10) == "cancel"
    assert decide_worker_action("pending", 10) == "skip"
    assert decide_worker_action("pending", 90000) == "cancel"  # >24h -> expired
    assert decide_worker_action("timeout", 10) == "cancel"
