"""The shared portrait negative prompt must exclude multi-person output (S.I.F.T. rendered as five people, 2026-10-20)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tools.media_studio.services import portrait_service as ps  # noqa: E402


def test_negative_prompt_excludes_groups():
    neg = ps._portrait_negative_prompt()
    for term in ("group", "multiple people", "crowd", "extra faces"):
        assert term in neg


def test_negative_prompt_keeps_identity_terms():
    neg = ps._portrait_negative_prompt()
    for term in ("identity drift", "extra limbs", "different person"):
        assert term in neg
