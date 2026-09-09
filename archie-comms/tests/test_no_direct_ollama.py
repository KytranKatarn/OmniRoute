"""Guard: archie_comms makes NO direct Ollama call — all inference goes through
the platform DHQ endpoint (#6654 / ADR-013). If this fails, someone reintroduced
a bypass that skips welfare/cost gating, the cold-load queue, and
task_execution_log visibility.
"""
import ast
import os

_COMMS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Substrings that mark a direct-inference bypass. A DHQ call
# (/api/internal/dhq/chat[...]) is allowed and deliberately not listed.
_FORBIDDEN = ("_call_ollama", "_stream_ollama", "OLLAMA_HOST", "/api/generate", "ARCHIE_VOICE_MODEL")


def _py_files():
    for base in ("services", "chat"):
        d = os.path.join(_COMMS_ROOT, base)
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            if "__pycache__" in root or "/tests" in root:
                continue
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(root, f)
    top = os.path.join(_COMMS_ROOT, "app_comms.py")
    if os.path.exists(top):
        yield top


def test_no_forbidden_direct_inference_substrings():
    offenders = []
    for path in _py_files():
        src = open(path, encoding="utf-8").read()
        for needle in _FORBIDDEN:
            if needle in src:
                offenders.append(f"{os.path.relpath(path, _COMMS_ROOT)} contains {needle!r}")
    assert not offenders, "direct-Ollama bypass reintroduced:\n" + "\n".join(offenders)


def test_api_chat_reference_is_only_the_dhq_endpoint():
    # '/api/chat' as an Ollama endpoint is forbidden; the platform DHQ path
    # '/api/internal/dhq/chat' and the comms Flask routes '/api/chat/...' are fine.
    for path in _py_files():
        src = open(path, encoding="utf-8").read()
        for line in src.splitlines():
            if "/api/chat" in line:
                assert ("/api/internal/dhq/chat" in line) or ("/api/chat/" in line) or ("/api/chat\"" in line and "route" in line), (
                    f"{os.path.relpath(path, _COMMS_ROOT)}: suspicious /api/chat use: {line.strip()[:100]}"
                )


def test_conversation_service_parses_and_imports_the_stream_client():
    src = open(os.path.join(_COMMS_ROOT, "services", "conversation_service.py"), encoding="utf-8").read()
    tree = ast.parse(src)  # must be valid Python
    names = {n for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for n in [a.name for a in node.names]}
    assert "stream_dhq_chat" in names and "DHQUnavailable" in names
