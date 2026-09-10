"""#6653 Phase 4 — cockpit reads for the coding lane: run history + providers, and the
Code Builder tile deep-link. In-container:
    docker exec -i archie_platform python3 -m pytest tests/test_cloud_code_reads.py -q
"""

import contextlib

import pytest

from services import internal_auth as ia

CALLER_KEYS = {caller: f"key-for-{caller}" for caller in ia.CALLER_ENV}


@pytest.fixture
def keys(monkeypatch):
    # Same shape as the fixture in test_internal_auth_scopes.py (which is not a conftest).
    for caller, env in ia.CALLER_ENV.items():
        monkeypatch.setenv(env, CALLER_KEYS[caller])
    monkeypatch.setenv(ia.LEGACY_ENV, "legacy-flat-key")
    monkeypatch.delenv(ia.LEGACY_ACCEPT_ENV, raising=False)
    return CALLER_KEYS


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql, self.params = rows, None, None

    def execute(self, sql, params=None):
        self.sql, self.params = " ".join(sql.split()), tuple(params or ())

    def fetchall(self):
        return list(self.rows)


@pytest.fixture
def db(monkeypatch):
    def install(rows):
        cur = _Cur(rows)

        @contextlib.contextmanager
        def fake(*a, **k):
            yield (None, cur)

        import database

        monkeypatch.setattr(database, "get_db_cursor", fake)
        return cur

    return install


def _comms_headers(keys):
    return _bearer(keys["archie_comms"])


def test_runs_lists_cloud_code_jobs_without_prompt_text(client, keys, db):
    cur = db(
        [
            {
                "id": 1198308,
                "status": "completed",
                "metadata": {
                    "approval_id": 15233,
                    "model": "oc/big-pickle",
                    "provider": "omniroute",
                    "prompt": "SECRET PROMPT",
                    "result": {
                        "model_used": "big-pickle",
                        "served_model_resolved": True,
                        "prompt_tokens": 454,
                        "completion_tokens": 1010,
                        "error": None,
                        "response": "def fizzbuzz",
                    },
                },
                "error_message": None,
                "created_at": None,
                "completed_at": None,
            }
        ]
    )
    r = client.get("/api/internal/cloud-code/runs?limit=5", headers=_comms_headers(keys))
    assert r.status_code == 200, r.get_json()
    run = r.get_json()["runs"][0]
    assert run["job_id"] == 1198308 and run["result"]["model_used"] == "big-pickle"
    assert "prompt" not in run and "response" not in run["result"]
    assert "job_type = %s" in cur.sql and "ORDER BY id DESC LIMIT %s" in cur.sql and cur.params[-1] == 5


def test_runs_limit_is_capped_at_100(client, keys, db):
    cur = db([])
    r = client.get("/api/internal/cloud-code/runs?limit=5000", headers=_comms_headers(keys))
    assert r.status_code == 200 and cur.params[-1] == 100


def test_providers_lists_active_non_proxy_text_chat_providers(client, keys, db):
    cur = db(
        [
            {
                "provider_key": "omniroute",
                "display_name": "OmniRoute (self-hosted gateway)",
                "default_model": "oc/big-pickle",
                "models": [{"name": "oc/big-pickle"}, {"name": "auto/coding"}],
                "is_active": True,
            }
        ]
    )
    r = client.get("/api/internal/cloud-code/providers", headers=_comms_headers(keys))
    assert r.status_code == 200, r.get_json()
    p = r.get_json()["providers"][0]
    assert (
        p["provider_key"] == "omniroute"
        and p["models"] == ["oc/big-pickle", "auto/coding"]
        and p["default_model"] == "oc/big-pickle"
    )
    assert "is_active" in cur.sql and "is_cloud_proxy" in cur.sql and "text_chat" in cur.sql


def test_cloud_code_reads_need_the_cloud_code_scope(client, keys):
    assert client.get("/api/internal/cloud-code/runs", headers=_bearer(keys["media_hub"])).status_code == 403
    assert client.get("/api/internal/cloud-code/providers").status_code == 401


def test_code_builder_tile_deep_links_to_the_builder_pane():
    from module_registry import MODULES

    tile = next(m for m in MODULES if m.id == "code_builder")
    assert tile.external_url == "https://archie.kytranempowerment.com/cockpit#builder"
