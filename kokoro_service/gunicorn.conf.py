"""gunicorn config for the archie_kokoro GPU TTS sidecar.

WARMS the Kokoro pipeline on the GPU at worker boot (owner directive: always-
loaded voice — keep active and responsive) with a tiny synth, so the FIRST
cockpit request is instant and the model stays resident. workers=1 — one GPU,
no VRAM duplication. Runs only under gunicorn (production), never under pytest.
"""

bind = "0.0.0.0:8092"
workers = 1
timeout = 300  # a fresh node cold-downloads the Kokoro weights on first load


def post_worker_init(worker):
    try:
        import app

        app._synthesize("Voice systems online.", speed=1.0)
        worker.log.info("Kokoro preloaded + warmed on %s", app._device)
    except Exception as exc:  # pragma: no cover — fall back to lazy-load on first request
        worker.log.warning("kokoro preload failed (will lazy-load): %s", exc)
