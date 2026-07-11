"""Kokoro TTS startup warmup (COO Cockpit Slice 3 follow-up — owner directive).

The platform must warm the REQUEST-SERVING synthesizer singleton with HER voice
(get_voice_synthesizer().synthesize_for_agent, agent 2 = af_heart+af_jessica) at
startup, so the first cockpit/HA TTS is instant. It previously warmed a throwaway
KokoroEngine()._get_pipeline("af_heart") — a different instance + only one voice —
which left the request singleton cold. Static source-pin (no execution).
"""

import os


def _warmup_body():
    # ONLY the _warmup_kokoro function — end at its module-level invocation so the
    # separate voice-cache warmup block below (which legitimately uses _get_pipeline)
    # is not swept in.
    path = os.environ.get("ARCHIE_APP_PY", "/app/app.py")
    src = open(path, "r", encoding="utf-8").read()
    start = src.index("def _warmup_kokoro")
    end = src.index("\n_warmup_kokoro()", start)
    return src[start:end]


def test_warmup_warms_the_request_serving_singleton():
    body = _warmup_body()
    assert "get_voice_synthesizer" in body, "warmup must warm the request-serving singleton"
    assert "synthesize_for_agent" in body, "warmup must exercise her actual voice path"


def test_warmup_uses_her_agent_id():
    body = _warmup_body()
    # agent 2 = A.R.C.H.I.E. -> loads her af_heart+af_jessica blend + profile + emotion
    assert "synthesize_for_agent(" in body and ", 2," in body


def test_warmup_does_not_use_throwaway_pipeline():
    # the old bug: KokoroEngine()._get_pipeline("af_heart") warmed a DIFFERENT engine
    assert "_get_pipeline" not in _warmup_body()


def test_warmup_is_invoked_at_startup():
    path = os.environ.get("ARCHIE_APP_PY", "/app/app.py")
    src = open(path, "r", encoding="utf-8").read()
    assert "\n_warmup_kokoro()\n" in src, "warmup must be called at module load (per gunicorn worker)"
