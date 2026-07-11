"""gunicorn config for the archie_whisper sidecar.

WARMS the faster-whisper model at worker boot (owner directive: always-loaded
voice — keep active and responsive) so the FIRST transcription is instant and the
model stays resident. Runs only under gunicorn (production), never under pytest.
"""

bind = "0.0.0.0:8090"
workers = 1
timeout = 120


def post_worker_init(worker):
    try:
        import app

        app._get_model()
        worker.log.info("faster-whisper preloaded (warm)")
    except Exception as exc:  # pragma: no cover — fall back to lazy-load on first request
        worker.log.warning("whisper preload failed (will lazy-load): %s", exc)
