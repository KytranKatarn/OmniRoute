"""/api/internal/dhq/chat must return token usage (#6775).

WHY THIS EXISTS
---------------
archie-tui (Lane 3 — the platform's own builder) routes every completion through
``/api/internal/dhq/chat``. Measured 2026-09-15 over 7 days:

    module_source | model_used       | runs | ok | avg_s | tokens
    archie_engine | engine/archie:7b |   20 | 20 |  21.6 |      0
    archie_engine | mistral:7b       |    2 |  2 |  16.6 |   3019

**20 of 22 runs logged ZERO tokens.** Not because the data was missing — the
dispatcher's ``DispatchResult`` has carried ``prompt_tokens``/``completion_tokens``
all along, and the STREAMING sibling ``/api/internal/dhq/chat/stream`` already emits
both in its done-frame. The non-streaming twin simply did not copy them out of
``result`` into its JSON body, so the numbers were discarded one line from the wire.

The cost is not cosmetic: it made the engine invisible to Token Economy, and it made
archie-tui **un-comparable** against the codex and opencode lanes (which ARE measured,
via omniroute's call log). Comparing coder harnesses is the whole point of the
evaluation program, and it is impossible while one contender reports nothing.

⚠️ This is the same defect FAMILY as #6763/#3339 (omniroute spend invisible) — a
producer that works fine while its telemetry silently reports nothing. Both were found
by reading a token column that read 0, not by any alarm.

NON-VACUITY
-----------
``test_the_pre_fix_shape_would_fail`` reconstructs the pre-fix return dict and asserts
this file's own checker rejects it. Without that, a test asserting "the keys are
present" passes just as happily against a file where someone re-adds them by accident
in a different endpoint.
"""

import ast
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app.py"
_ROUTE = "/api/internal/dhq/chat"
_REQUIRED = {"prompt_tokens", "completion_tokens"}
# The keys that existed BEFORE the fix. They are load-bearing for every existing
# caller, so the fix must be purely additive — never a rename or a removal.
_PRE_EXISTING = {"success", "response", "agent_name", "model_used"}


def _route_function(tree: ast.Module, path: str) -> ast.FunctionDef:
    """The function decorated with @app.route(<path>, ...) — EXACT match.

    Exact, because '/api/internal/dhq/chat' is a prefix of '/api/internal/dhq/chat/stream'
    and the stream variant already returns tokens. A substring match would find the
    streaming twin and pass while the endpoint under test stayed broken.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not dec.args:
                continue
            first = dec.args[0]
            if isinstance(first, ast.Constant) and first.value == path:
                return node
    raise AssertionError(f"no function is routed at exactly {path!r}")


def _success_payload_keys(fn: ast.FunctionDef) -> set[str]:
    """Keys of the jsonify({...}) dict on the SUCCESS path.

    Identified as the returned dict literal carrying "response" — the 502/500 error
    returns carry "error" instead, so they are skipped without depending on line
    numbers or ordering.
    """
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "jsonify"):
            continue
        if not call.args or not isinstance(call.args[0], ast.Dict):
            continue
        keys = {k.value for k in call.args[0].keys if isinstance(k, ast.Constant)}
        if "response" in keys:
            return keys
    raise AssertionError("no jsonify({... 'response' ...}) success return found")


@pytest.fixture(scope="module")
def payload_keys() -> set[str]:
    return _success_payload_keys(_route_function(ast.parse(_APP.read_text(encoding="utf-8")), _ROUTE))


def test_success_response_reports_token_usage(payload_keys):
    """THE REGRESSION. Pre-fix this set was exactly _PRE_EXISTING and tokens were lost."""
    missing = _REQUIRED - payload_keys
    assert not missing, (
        f"{_ROUTE} does not return {sorted(missing)} — archie-tui cannot report its own "
        "token spend, so it logs 0 and stays un-comparable against the other coder lanes"
    )


def test_the_fix_is_purely_additive(payload_keys):
    """Every pre-fix key must survive; callers depend on them."""
    lost = _PRE_EXISTING - payload_keys
    assert not lost, f"{_ROUTE} dropped pre-existing key(s) {sorted(lost)} — not an additive change"


def test_the_streaming_sibling_still_reports_usage():
    """The streaming twin was already correct; it must not regress to match the old shape."""
    src = _APP.read_text(encoding="utf-8")
    idx = src.index(f'"{_ROUTE}/stream"')
    window = src[idx : idx + 2000]
    for key in _REQUIRED:
        assert key in window, f"{_ROUTE}/stream no longer documents/emits {key}"


def test_the_pre_fix_shape_would_fail():
    """NON-VACUITY: the checker must REJECT the pre-fix payload.

    Guards against this file degrading into a test that passes on any app.py.
    """
    pre_fix = ast.parse(
        "def f():\n" "    return jsonify({'success': True, 'response': r, " "'agent_name': a, 'model_used': m})\n"
    )
    keys = _success_payload_keys(pre_fix.body[0])
    assert _REQUIRED - keys == _REQUIRED, "checker failed to reject the pre-fix shape"


def test_exact_route_match_does_not_resolve_the_stream_variant():
    """NON-VACUITY: prove the resolver is exact, not prefix-based.

    '/api/internal/dhq/chat' is a strict prefix of the stream route. A prefix match
    would silently test the already-correct sibling.
    """
    tree = ast.parse(_APP.read_text(encoding="utf-8"))
    base = _route_function(tree, _ROUTE)
    stream = _route_function(tree, f"{_ROUTE}/stream")
    assert base.name != stream.name, "resolver collapsed the two routes onto one function"
