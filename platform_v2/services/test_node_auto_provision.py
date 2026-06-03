"""Unit tests for the node auto-provision diff logic (#3732).
Run: PYTHONPATH=platform_v2 python3 platform_v2/services/test_node_auto_provision.py
Pure logic — no DB.
"""

from services.node_auto_provision import _ollama_present

_p = _f = 0


def check(desc, cond):
    global _p, _f
    if cond:
        _p += 1
    else:
        _f += 1
        print("FAIL:", desc)


present = ["nomic-embed-text:latest", "qwen2.5:7b", "llama3.2:3b", "qwen2.5:1.5b"]
full = set(present)
bases = {m.split(":")[0] for m in present}

# Tag-quirk matching: a tagless recommendation matches a present ':latest'.
check("tagless nomic matches present nomic:latest", _ollama_present("nomic-embed-text", full, bases) is True)
check("exact qwen2.5:7b present", _ollama_present("qwen2.5:7b", full, bases) is True)
check("qwen2.5:1.5b present", _ollama_present("qwen2.5:1.5b", full, bases) is True)
check("mistral:7b NOT present (tagged, absent)", _ollama_present("mistral:7b", full, bases) is False)
check("phi3 NOT present (tagless, absent)", _ollama_present("phi3", full, bases) is False)

# A brand-new (empty) node → every recommended model is a gap to pull.
efull, ebases = set(), set()
check("empty node: nomic-embed-text is a gap", _ollama_present("nomic-embed-text", efull, ebases) is False)
check("empty node: qwen2.5:7b is a gap", _ollama_present("qwen2.5:7b", efull, ebases) is False)

print(f"PASS={_p} FAIL={_f}")
raise SystemExit(1 if _f else 0)
