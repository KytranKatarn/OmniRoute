"""Portrait identity consistency: variant prompt source + approval status.

Run: python -m unittest tests.test_portrait_identity_consistency -v
"""

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "tools.media_studio.services.portrait_service",
    Path(__file__).resolve().parents[1] / "tools/media_studio/services/portrait_service.py",
)
service = importlib.util.module_from_spec(spec)
service.__package__ = "tools.media_studio.services"
spec.loader.exec_module(service)


def make_row(**overrides):
    """Build a row matching the variant query's SELECT (agents a + agent_portraits p).

    The SQL computes COALESCE(NULLIF(a.avatar_generation_prompt,''), NULLIF(a.portrait_prompt,''), NULLIF(p.identity_prompt,'')) AS identity_prompt.
    The mock must simulate that SQL-level alias, not return the raw portrait row's identity_prompt.
    """
    avatar_prompt = overrides.pop("avatar_generation_prompt", "effective roster prompt")
    portrait_prompt = overrides.pop("portrait_prompt", "effective roster prompt")
    raw_identity = overrides.pop("identity_prompt", "stale portrait row prompt")

    # Simulate SQL COALESCE + NULLIF + alias
    effective = avatar_prompt or portrait_prompt or raw_identity

    base = {
        # agents a columns (used by COALESCE)
        "_avatar_prompt": avatar_prompt,
        "_portrait_prompt": portrait_prompt,
        # SQL result columns (what fetchone returns)
        "identity_prompt": effective,  # COALESCE result aliased
        "ip_adapter_ref_path": "/static/ref.png",
        "canonical_image_path": "/static/canonical.png",
        "face_seed": 42,
        "approved": True,
        "name": "A.R.M.A.D.A.",
        "display_name": "A.R.M.A.D.A.",
        "gender": "",
        "pronouns": "",
        "ethnicity": "",
        "age_range": "",
        "appearance_notes": "",
    }
    base.update(overrides)
    return base


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return self.row


@contextmanager
def fake_cursor(row, commit=False):
    yield None, FakeCursor(row)


class VariantPromptSourceTests(unittest.TestCase):
    def test_variant_uses_effective_roster_prompt_not_stale_portrait_row(self):
        """Variant must use COALESCE(avatar_generation_prompt, portrait_prompt, portrait_row.identity_prompt)."""
        row = make_row()
        submitted = {}

        def fake_submit(**kwargs):
            submitted.update(kwargs)
            return {"queue_id": 1}

        with patch.object(service, "get_db_cursor", lambda commit=False: fake_cursor(row)), patch(
            "tools.media_studio.services.generation_service.submit_generation", fake_submit
        ), patch.object(
            service, "_portrait_model_params", return_value={"model": "sd_xl_base_1.0.safetensors"}
        ), patch.object(
            service,
            "_identity_generation_params",
            return_value={"identity_mode": "faceid_detail", "identity_weight": 0.85},
        ), patch.object(
            service, "_portrait_negative_prompt", return_value="bad"
        ):
            result = service.generate_variant(337)

        self.assertNotIn("error", result)
        self.assertTrue(submitted["prompt"].startswith("effective roster prompt"))

    def test_variant_rejects_unapproved_canonical(self):
        row = make_row(approved=False)

        with patch.object(service, "get_db_cursor", lambda commit=False: fake_cursor(row)), patch(
            "tools.media_studio.services.generation_service.submit_generation"
        ) as submit:
            result = service.generate_variant(337)

        self.assertIn("error", result)
        self.assertIn("approved", result["error"])
        submit.assert_not_called()

    def test_variant_falls_back_to_portrait_row_when_roster_fields_empty(self):
        row = make_row(avatar_generation_prompt="", portrait_prompt="")
        submitted = {}

        def fake_submit(**kwargs):
            submitted.update(kwargs)
            return {"queue_id": 1}

        with patch.object(service, "get_db_cursor", lambda commit=False: fake_cursor(row)), patch(
            "tools.media_studio.services.generation_service.submit_generation", fake_submit
        ), patch.object(
            service, "_portrait_model_params", return_value={"model": "sd_xl_base_1.0.safetensors"}
        ), patch.object(
            service,
            "_identity_generation_params",
            return_value={"identity_mode": "faceid_detail", "identity_weight": 0.85},
        ), patch.object(
            service, "_portrait_negative_prompt", return_value="bad"
        ):
            result = service.generate_variant(337)

        self.assertNotIn("error", result)
        self.assertTrue(submitted["prompt"].startswith("stale portrait row prompt"))


class ApprovalStatusTests(unittest.TestCase):
    def test_approve_canonical_marks_generation_completed(self):
        """Approving a canonical must set generation_status='completed', not leave legacy 'pending'."""
        media = {
            "file_path": "/static/media/images/canonical.png",
            "thumbnail_path": "/static/thumb.png",
            "seed": 42,
            "metadata": {},
        }
        calls = []

        class Cursor:
            def execute(self, sql, params=None):
                calls.append((" ".join(sql.split()), params))

            def fetchone(self):
                # First call is the media_library SELECT; second is the RETURNING.
                if any("media_library" in c[0] for c in calls):
                    return media
                return None

        @contextmanager
        def cursor(commit=False):
            yield None, Cursor()

        with patch.object(service, "get_db_cursor", cursor), patch.object(
            service.agent_service, "update_agent", return_value=True
        ), patch.object(service, "_sync_all_site_thumbs", return_value=(None, [])), patch(
            "services.public_roster_service.write_directory_snapshot"
        ):
            result = service.approve_canonical(337, 999)

        self.assertEqual(result["status"], "approved")
        upsert = [c for c in calls if c[0].startswith("INSERT INTO agent_portraits")]
        self.assertEqual(len(upsert), 1)
        self.assertIn("'completed'", upsert[0][0])


if __name__ == "__main__":
    unittest.main()
