"""Tests for approvals follow-up work — #2167 bridge resume."""

import json as _json
import os
import sys

import psycopg2
import psycopg2.extras
import pytest

if "/mnt/archie_brain/ai_bridge" not in sys.path:
    sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
if "/app" not in sys.path:
    sys.path.insert(0, "/app")


def _get_db_password():
    try:
        return open("/run/secrets/db_password").read().strip()
    except FileNotFoundError:
        return os.environ.get("DB_PASSWORD", "")


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        dbname=os.environ.get("DB_NAME", "archie"),
        user=os.environ.get("DB_USER", "archie"),
        password=_get_db_password(),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    yield conn
    conn.close()


def _seed_approved_bridge_image(db, prompt="test prompt", user_id=2):
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO bridge_jobs
               (job_type, module_source, description, status, agent_name,
                station_code, total_steps, metadata)
               VALUES ('image_generation', 'media_studio',
                       'Cloud image gen (approved): test',
                       'approved', 'Pixel', 'CREATIVE', 1, %s)
               RETURNING id""",
            (
                _json.dumps(
                    {
                        "target_host": "cloud",
                        "prompt": prompt,
                        "escalation": "paid_cloud",
                        "user_id": user_id,
                        "image_params": {},
                    }
                ),
            ),
        )
        return cur.fetchone()["id"]


class TestResumeApprovedBridgeJobs:
    def test_resume_success_flips_to_completed(self, db, monkeypatch):
        """Approved image_generation row is dispatched to paid cloud → completed."""
        from services import agent_jobs
        from ai_bridge import external_providers

        monkeypatch.setattr(
            external_providers,
            "get_providers_with_capability",
            lambda cap: [{"provider_key": "openai_stub", "tier_position": 5}],
        )
        monkeypatch.setattr(
            external_providers,
            "generate_media",
            lambda pkey, payload: {
                "success": True,
                "file_path": "/fake/out.png",
                "cost_usd": 0.04,
            },
        )

        row_id = _seed_approved_bridge_image(db)
        try:
            agent_jobs.resume_approved_bridge_jobs()
            with db.cursor() as cur:
                cur.execute(
                    "SELECT status, description, completed_at FROM bridge_jobs WHERE id=%s",
                    (row_id,),
                )
                r = cur.fetchone()
            assert r["status"] == "completed"
            assert r["completed_at"] is not None
            assert "/fake/out.png" in (r["description"] or "")
        finally:
            with db.cursor() as cur:
                cur.execute("DELETE FROM bridge_jobs WHERE id=%s", (row_id,))

    def test_resume_failure_flips_to_failed(self, db, monkeypatch):
        """Provider error → row ends in 'failed' with error_message set."""
        from services import agent_jobs
        from ai_bridge import external_providers

        monkeypatch.setattr(
            external_providers,
            "get_providers_with_capability",
            lambda cap: [{"provider_key": "openai_stub", "tier_position": 5}],
        )
        monkeypatch.setattr(
            external_providers,
            "generate_media",
            lambda pkey, payload: {"success": False, "error": "quota exceeded"},
        )

        row_id = _seed_approved_bridge_image(db)
        try:
            agent_jobs.resume_approved_bridge_jobs()
            with db.cursor() as cur:
                cur.execute(
                    "SELECT status, error_message FROM bridge_jobs WHERE id=%s",
                    (row_id,),
                )
                r = cur.fetchone()
            assert r["status"] == "failed"
            assert "quota exceeded" in (r["error_message"] or "")
        finally:
            with db.cursor() as cur:
                cur.execute("DELETE FROM bridge_jobs WHERE id=%s", (row_id,))

    def test_resume_skips_non_image_types(self, db, monkeypatch):
        """job_type='cloud_dispatch' should NOT be picked up (only image_generation)."""
        from services import agent_jobs
        from ai_bridge import external_providers

        called = []
        monkeypatch.setattr(
            external_providers,
            "generate_media",
            lambda *a, **k: called.append(True) or {"success": True},
        )

        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO bridge_jobs
                   (job_type, module_source, description, status, agent_name, total_steps, metadata)
                   VALUES ('cloud_dispatch', 'media_studio', 'non-image', 'approved',
                           'Pixel', 1, '{}'::jsonb)
                   RETURNING id"""
            )
            row_id = cur.fetchone()["id"]
        try:
            agent_jobs.resume_approved_bridge_jobs()
            with db.cursor() as cur:
                cur.execute("SELECT status FROM bridge_jobs WHERE id=%s", (row_id,))
                r = cur.fetchone()
            assert r["status"] == "approved"  # unchanged
            assert not called
        finally:
            with db.cursor() as cur:
                cur.execute("DELETE FROM bridge_jobs WHERE id=%s", (row_id,))


class TestResumeDispatchTable:
    def test_dispatch_table_covers_image_generation(self):
        from services.agent_jobs import _BRIDGE_RESUME_HANDLERS, _resume_image_generation

        assert "image_generation" in _BRIDGE_RESUME_HANDLERS
        assert _BRIDGE_RESUME_HANDLERS["image_generation"] is _resume_image_generation

    def test_dispatch_table_select_uses_registered_keys(self, db):
        """Rows with unregistered job_type are not even selected by the job."""
        from services import agent_jobs

        # Seed an approved row with job_type NOT in the dispatch table.
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO bridge_jobs
                   (job_type, module_source, description, status, agent_name, total_steps, metadata)
                   VALUES ('unknown_future_type', 'mod', 'x', 'approved', 'Pixel', 1, '{}'::jsonb)
                   RETURNING id"""
            )
            row_id = cur.fetchone()["id"]
        try:
            agent_jobs.resume_approved_bridge_jobs()
            with db.cursor() as cur:
                cur.execute("SELECT status FROM bridge_jobs WHERE id=%s", (row_id,))
                r = cur.fetchone()
            assert r["status"] == "approved", "unknown job_type should remain untouched"
        finally:
            with db.cursor() as cur:
                cur.execute("DELETE FROM bridge_jobs WHERE id=%s", (row_id,))
