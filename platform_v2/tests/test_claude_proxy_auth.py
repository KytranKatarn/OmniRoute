"""The Claude CLI proxy must not run `claude -p --dangerously-skip-permissions` for anyone.

`scripts/claude_proxy.py` listens on 0.0.0.0:7682 and a POST there executes the Claude CLI
with permissions skipped, as the host user. Until this change it did so with NO
authentication of any kind — verified answering HTTP 200 from the LAN address — so anyone
on the network had remote code execution on the hub.

These tests drive the handler directly (no socket) and pin four properties:

  1. FAIL CLOSED — an unset or empty ``CLAUDE_PROXY_TOKEN`` refuses every POST (503).
     An unset secret must never mean "allow"; that is exactly the state the hole ran in.
  2. A missing or wrong ``X-Claude-Proxy-Token`` is refused (401) and never reaches
     ``subprocess.run``.
  3. The correct token DOES reach the subprocess (the gate is not simply "always deny").
  4. The comparison uses ``hmac.compare_digest``, not ``==``.

Plus: GET stays open (every caller uses it as a liveness probe), the token is never
logged, and all three POST call sites plus their compose wiring carry the header.
"""

import email.message
import importlib.util
import io
import json
import sys

import pytest

from tests.repo_root import platform_root, repo_path

PROXY_PATH = repo_path("scripts", "claude_proxy.py")

TOKEN = "s3cr3t-token-for-tests"

# The three services whose code POSTs to the proxy, and the files that do it.
# platform_root(), NOT repo_path("platform_v2", ...): platform_v2 is bind-mounted AS /app
# in the container, so a repo-rooted path to it resolves nowhere and the test SKIPS
# instead of failing — the vacuity trap documented in tests/repo_root.py.
CALLER_FILES = (
    ("archie-comms", repo_path("archie-comms", "collaboration", "claude_bridge.py")),
    ("consciousness", platform_root() / "tools" / "consciousness" / "claude_bridge.py"),
    (
        "orchestration_engine",
        platform_root() / "tools" / "department_hq" / "services" / "orchestration_engine.py",
    ),
)

pytestmark = pytest.mark.skipif(
    not PROXY_PATH.exists(),
    reason=f"claude_proxy.py not reachable at {PROXY_PATH}",
)


def _load_proxy():
    """Import scripts/claude_proxy.py by path — it is a script, not an installed module."""
    spec = importlib.util.spec_from_file_location("_claude_proxy_under_test", PROXY_PATH)
    module = importlib.util.module_from_spec(spec)
    # Registered so @patch-style lookups and dataclass/enum reprs resolve cleanly.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def proxy():
    module = _load_proxy()
    yield module
    sys.modules.pop("_claude_proxy_under_test", None)


def _make_handler(proxy, headers: dict, body: dict | None = None):
    """A handler instance driven without a socket.

    BaseHTTPRequestHandler.__init__ does the whole socket dance, so the subclass below
    replaces it: `headers` is the email.message.Message that the real class populates,
    `rfile` is the request body, and `_respond` records instead of writing to a socket.
    """
    raw = json.dumps(body if body is not None else {"message": "hello"}).encode()

    msg = email.message.Message()
    for key, value in headers.items():
        msg[key] = value
    msg["Content-Length"] = str(len(raw))

    class _Driven(proxy.ClaudeProxyHandler):
        def __init__(self):  # noqa: D107 - deliberately bypasses the socket __init__
            self.headers = msg
            self.rfile = io.BytesIO(raw)
            self.client_address = ("10.0.0.99", 51234)
            self.responses = []

        def _respond(self, status_code, data):
            self.responses.append((status_code, data))

    return _Driven()


class _FakeCompleted:
    def __init__(self, stdout="ok from claude", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def spy_subprocess(proxy, monkeypatch):
    """Replace subprocess.run so `claude` is NEVER actually invoked."""
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _FakeCompleted()

    monkeypatch.setattr(proxy.subprocess, "run", _fake_run)
    return calls


# ---------------------------------------------------------------------------
# 1. Fail closed on an unconfigured secret
# ---------------------------------------------------------------------------


def test_post_refused_when_token_env_is_unset(proxy, monkeypatch, spy_subprocess):
    monkeypatch.delenv("CLAUDE_PROXY_TOKEN", raising=False)

    handler = _make_handler(proxy, {"Content-Type": "application/json"})
    handler.do_POST()

    status, payload = handler.responses[0]
    assert status == 503, "an unset secret must refuse, never allow"
    assert payload["success"] is False
    assert spy_subprocess == [], "the CLI must not run when the proxy is unconfigured"


def test_post_refused_when_token_env_is_empty(proxy, monkeypatch, spy_subprocess):
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", "   ")

    handler = _make_handler(proxy, {"X-Claude-Proxy-Token": "   "})
    handler.do_POST()

    status, _ = handler.responses[0]
    assert status == 503, "whitespace is not a secret — a blank token cannot authenticate"
    assert spy_subprocess == []


# ---------------------------------------------------------------------------
# 2. Wrong / missing header is refused
# ---------------------------------------------------------------------------


def test_post_refused_without_the_header(proxy, monkeypatch, spy_subprocess):
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", TOKEN)

    handler = _make_handler(proxy, {"Content-Type": "application/json"})
    handler.do_POST()

    status, payload = handler.responses[0]
    assert status == 401
    assert "X-Claude-Proxy-Token" in payload["error"]
    assert spy_subprocess == []


def test_post_refused_with_a_wrong_token(proxy, monkeypatch, spy_subprocess):
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", TOKEN)

    handler = _make_handler(proxy, {"X-Claude-Proxy-Token": TOKEN + "x"})
    handler.do_POST()

    status, _ = handler.responses[0]
    assert status == 401
    assert spy_subprocess == []


def test_a_non_ascii_token_is_a_401_not_a_500(proxy, monkeypatch, spy_subprocess):
    """compare_digest on str raises TypeError for non-ASCII — bytes must be compared."""
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", TOKEN)

    handler = _make_handler(proxy, {"X-Claude-Proxy-Token": "tökén-ünicode"})
    handler.do_POST()

    status, _ = handler.responses[0]
    assert status == 401
    assert spy_subprocess == []


# ---------------------------------------------------------------------------
# 3. The correct token still works (the gate is not "always deny")
# ---------------------------------------------------------------------------


def test_correct_token_reaches_the_subprocess(proxy, monkeypatch, spy_subprocess):
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", TOKEN)

    handler = _make_handler(proxy, {"X-Claude-Proxy-Token": TOKEN})
    handler.do_POST()

    status, payload = handler.responses[0]
    assert status == 200
    assert payload["success"] is True
    assert len(spy_subprocess) == 1, "the authenticated request must reach the CLI"
    cmd = spy_subprocess[0][0]
    assert cmd[0] == "claude"


def test_surrounding_whitespace_on_the_header_is_tolerated(proxy, monkeypatch, spy_subprocess):
    """An env-file value and a header both get stripped, so they still match."""
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", TOKEN)

    handler = _make_handler(proxy, {"X-Claude-Proxy-Token": f"  {TOKEN}  "})
    handler.do_POST()

    assert handler.responses[0][0] == 200
    assert len(spy_subprocess) == 1


# ---------------------------------------------------------------------------
# 4. compare_digest, not ==
# ---------------------------------------------------------------------------


def test_comparison_goes_through_hmac_compare_digest(proxy, monkeypatch, spy_subprocess):
    """Behavioural, not a grep: the real compare_digest is observed being called."""
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", TOKEN)

    real = proxy.hmac.compare_digest
    seen = []

    def _spy(a, b):
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(proxy.hmac, "compare_digest", _spy)

    handler = _make_handler(proxy, {"X-Claude-Proxy-Token": TOKEN})
    handler.do_POST()

    assert handler.responses[0][0] == 200
    assert seen, "the token comparison must go through hmac.compare_digest"
    # Bytes, so a non-ASCII header can never raise instead of returning False.
    assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in seen)


def test_source_contains_no_plain_equality_on_the_token(proxy):
    """A `==` on the secret would be timing-attackable and silently replace the gate."""
    source = PROXY_PATH.read_text()
    assert "hmac.compare_digest" in source
    for bad in ("presented == expected", "expected == presented"):
        assert bad not in source, f"token compared with `{bad}` instead of compare_digest"


# ---------------------------------------------------------------------------
# GET stays open; the token is never logged
# ---------------------------------------------------------------------------


def test_get_health_check_needs_no_token(proxy, monkeypatch):
    """Callers poll GET for liveness; it returns only {"status": "ok"}."""
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", TOKEN)

    handler = _make_handler(proxy, {})
    handler.do_GET()

    status, payload = handler.responses[0]
    assert status == 200
    assert payload["status"] == "ok"


def test_the_token_is_never_logged(proxy, monkeypatch, caplog, spy_subprocess):
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", TOKEN)
    wrong = "attacker-supplied-value"

    with caplog.at_level("DEBUG"):
        _make_handler(proxy, {"X-Claude-Proxy-Token": wrong}).do_POST()
        _make_handler(proxy, {"X-Claude-Proxy-Token": TOKEN}).do_POST()

    logged = caplog.text
    assert TOKEN not in logged, "the configured secret leaked into the logs"
    assert wrong not in logged, "a presented token leaked into the logs"


# ---------------------------------------------------------------------------
# Caller + compose wiring — a gate nothing sends the header to is an outage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,path", CALLER_FILES, ids=[n for n, _ in CALLER_FILES])
def test_every_proxy_caller_sends_the_header(name, path):
    if not path.exists():
        pytest.skip(f"{name} source not reachable at {path}")
    source = path.read_text()
    assert "X-Claude-Proxy-Token" in source, f"{name} POSTs to the proxy without the token"
    assert "CLAUDE_PROXY_TOKEN" in source, f"{name} never reads the CLAUDE_PROXY_TOKEN env"


def test_compose_passes_the_token_to_every_calling_service():
    """A caller that reads the env var but is never given it fails closed at the proxy."""
    yaml = pytest.importorskip("yaml")
    compose = repo_path("docker-compose.yml")
    if not compose.exists():
        pytest.skip("docker-compose.yml not reachable")

    services = yaml.safe_load(compose.read_text())["services"]
    for svc in ("archie_platform", "archie_scheduler", "archie_comms"):
        env = services[svc].get("environment") or {}
        if isinstance(env, dict):
            present = "CLAUDE_PROXY_TOKEN" in env
        else:
            present = any(str(e).split("=")[0] == "CLAUDE_PROXY_TOKEN" for e in env)
        assert present, f"{svc} calls the proxy but compose never passes CLAUDE_PROXY_TOKEN"


def test_the_secret_is_not_committed_to_the_repo():
    """The token lives in .env only — a literal value in compose would be a leak."""
    compose = repo_path("docker-compose.yml")
    if not compose.exists():
        pytest.skip("docker-compose.yml not reachable")
    for line in compose.read_text().splitlines():
        stripped = line.strip().lstrip("- ")
        if stripped.startswith("CLAUDE_PROXY_TOKEN"):
            value = stripped.split(":", 1)[-1] if ":" in stripped else stripped.split("=", 1)[-1]
            assert "${" in value, f"CLAUDE_PROXY_TOKEN must interpolate from .env, got: {line!r}"
