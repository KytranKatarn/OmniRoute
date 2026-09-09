"""MarkerFilter keeps {{...}} markers out of the streamed view (#6654)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.marker_filter import MarkerFilter


def _run(filter_obj, tokens):
    out = "".join(filter_obj.feed(t) for t in tokens)
    return out + filter_obj.flush()


def test_plain_text_passes_through():
    assert _run(MarkerFilter(), ["Hello ", "world."]) == "Hello world."


def test_whole_marker_in_one_token_is_dropped():
    assert _run(MarkerFilter(), ["A ", "{{DEEPEN}}", " B"]) == "A  B"


def test_marker_split_across_tokens_is_dropped():
    toks = ["On it. ", '{{DELEGATE capability="code_review" ', 'reason="x"}}', " Done."]
    out = _run(MarkerFilter(), toks)
    assert "{{" not in out and "DELEGATE" not in out
    assert out == "On it.  Done."


def test_double_brace_split_exactly_on_the_braces():
    # '{' then '{DEEPEN}}' — the lone leading '{' must be held, not emitted
    out = _run(MarkerFilter(), ["x{", "{DEEPEN}}y"])
    assert out == "xy"


def test_unterminated_marker_at_end_is_not_flashed():
    # stream ends mid-marker: drop the dangling '{{…' rather than show it
    out = _run(MarkerFilter(), ["hi ", "{{DELEGATE capa"])
    assert out == "hi "


def test_long_false_alarm_is_released_not_swallowed():
    # a '{{' with no close within the cap is not a marker — release it
    junk = "{{" + ("z" * 100)
    out = _run(MarkerFilter(cap=64), [junk])
    assert out == junk


def test_two_markers_in_a_stream():
    out = _run(MarkerFilter(), ["a", "{{APPROVALS}}", "b", "{{DEEPEN}}", "c"])
    assert out == "abc"
