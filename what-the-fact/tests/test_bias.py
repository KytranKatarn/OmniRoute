import json
from ingest.bias import score_bias

FIXTURE = "what-the-fact/tests/fixtures/bias_golden.json"


def test_golden_file_all_within_one_band():
    """Every golden article scores within 1 band of its expected label."""
    ORDER = ["left", "center-left", "center", "center-right", "right"]
    with open(FIXTURE) as f:
        items = json.load(f)
    failures = []
    for item in items:
        got = score_bias(item["title"], item["body"])
        expected = item["expected_band"]
        distance = abs(ORDER.index(got["band"]) - ORDER.index(expected))
        if distance > 1:
            failures.append(f"{item['title'][:50]!r}: expected {expected}, got {got['band']}")
    assert not failures, "golden-file drift:\n" + "\n".join(failures)


def test_returns_required_keys():
    out = score_bias("T", "body text")
    assert set(out.keys()) >= {"band", "score", "rationale", "heuristic_version"}
    assert -1.0 <= out["score"] <= 1.0
    assert out["heuristic_version"] == "v1"
