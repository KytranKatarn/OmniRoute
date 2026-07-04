"""
XTTS v2 Compatibility Patches
Allows Coqui TTS 0.22.0 to work with torch>=2.6.0 and transformers>=4.45.0

Problem 1: torch>=2.6.0 changed torch.load() default to weights_only=True.
  TTS 0.22.0 has 28 torch.load() calls without weights_only=False, causing
  UnpicklingError on model loading.

Problem 2: transformers>=4.45.0 removed BeamSearchScorer, which XTTS v2's
  stream_generator.py imports for beam search decoding.

Import this module BEFORE importing TTS or torch in voice_synthesis.py.
"""

import importlib
import logging
import sys

logger = logging.getLogger("xtts_compat")

_patched = False


def apply_patches():
    """Apply all compatibility patches. Safe to call multiple times."""
    global _patched
    if _patched:
        return
    _patched = True

    _patch_torch_load()
    _patch_beam_search_scorer()
    logger.info("[XTTSCompat] Compatibility patches applied")


def _patch_torch_load():
    """Wrap torch.load to default weights_only=False for TTS compatibility.

    torch>=2.6.0 changed the default from False to True, breaking all 28
    torch.load() calls in TTS 0.22.0 that don't pass weights_only explicitly.
    """
    try:
        import torch

        version = tuple(int(x) for x in torch.__version__.split("+")[0].split(".")[:2])
        if version < (2, 6):
            logger.debug("[XTTSCompat] torch %s < 2.6, no patch needed", torch.__version__)
            return

        _original_load = torch.load

        def _patched_load(*args, **kwargs):
            if "weights_only" not in kwargs:
                kwargs["weights_only"] = False
            return _original_load(*args, **kwargs)

        torch.load = _patched_load
        logger.info("[XTTSCompat] Patched torch.load default weights_only=False (torch %s)", torch.__version__)

    except ImportError:
        logger.debug("[XTTSCompat] torch not installed, skipping patch")


def _patch_beam_search_scorer():
    """Provide BeamSearchScorer stub if transformers>=4.45.0 removed it.

    XTTS v2's stream_generator.py imports BeamSearchScorer and
    ConstrainedBeamSearchScorer from transformers. These were removed in 4.45.0.
    We inject a compatibility module that re-exports them if missing.
    """
    try:
        import transformers

        version = tuple(
            int(x) for x in transformers.__version__.split(".")[:2]
        )
        if version < (4, 45):
            logger.debug("[XTTSCompat] transformers %s < 4.45, no patch needed", transformers.__version__)
            return

        # Check if BeamSearchScorer still exists (future versions might re-add)
        try:
            from transformers import BeamSearchScorer  # noqa: F401
            logger.debug("[XTTSCompat] BeamSearchScorer still present, no patch needed")
            return
        except ImportError:
            pass

        # Try to import from the old location (generation.beam_search)
        try:
            from transformers.generation.beam_search import (  # noqa: F401,F811
                BeamSearchScorer,
                ConstrainedBeamSearchScorer,
            )
            # Re-export at top level
            transformers.BeamSearchScorer = BeamSearchScorer
            transformers.ConstrainedBeamSearchScorer = ConstrainedBeamSearchScorer
            logger.info("[XTTSCompat] Re-exported BeamSearchScorer from generation.beam_search")
            return
        except ImportError:
            pass

        # Last resort: provide a minimal stub that raises at runtime
        # This allows import to succeed but will error if actually called
        logger.warning(
            "[XTTSCompat] BeamSearchScorer removed in transformers %s — "
            "installing stub. XTTS streaming mode will not work.",
            transformers.__version__,
        )

        class BeamSearchScorerStub:
            """Stub for removed BeamSearchScorer. Raises if actually used."""

            def __init__(self, *args, **kwargs):
                raise NotImplementedError(
                    "BeamSearchScorer was removed in transformers >= 4.45.0. "
                    "XTTS v2 streaming mode requires transformers < 4.45.0 or "
                    "a Coqui TTS version that doesn't use BeamSearchScorer."
                )

        transformers.BeamSearchScorer = BeamSearchScorerStub
        transformers.ConstrainedBeamSearchScorer = BeamSearchScorerStub

        # Also patch the generation module so `from transformers.generation import ...` works
        if hasattr(transformers, "generation"):
            transformers.generation.BeamSearchScorer = BeamSearchScorerStub
            transformers.generation.ConstrainedBeamSearchScorer = BeamSearchScorerStub

    except ImportError:
        logger.debug("[XTTSCompat] transformers not installed, skipping patch")
