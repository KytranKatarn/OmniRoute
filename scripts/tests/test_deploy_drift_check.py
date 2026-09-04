"""Tests for scripts/deploy_drift_check.py's ancestry fallback (#6236).

Monorepo-subtree products (wtf, media_hub) are stamped with the REPO's HEAD at
build time, which is routinely ahead of the last commit that touched the
product's own PATH. Before this fix, that alone reported PERMANENT false
DRIFT even when the running image demonstrably contained every change to the
product's path. These tests pin the ancestry fallback that fixes it, and
confirm it stays out of the way for the genuine cases (exact match, real
drift, and no-information fail-open).
"""

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "deploy_drift_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("deploy_drift_check", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["deploy_drift_check"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ddc():
    return _load_module()


def _fake_response(payload: dict):
    """A context-manager stand-in for urllib.request.urlopen(...)."""
    body = json.dumps(payload).encode()
    cm = mock.MagicMock()
    cm.__enter__.return_value = types.SimpleNamespace(read=lambda: body)
    cm.__exit__.return_value = False
    return cm


class TestPathHeadIsAncestor:
    def test_behind_by_zero_means_ancestor(self, ddc, monkeypatch):
        monkeypatch.setattr(
            ddc.urllib.request,
            "urlopen",
            lambda *a, **k: _fake_response({"behind_by": 0, "ahead_by": 4, "status": "ahead"}),
        )
        assert ddc._path_head_is_ancestor("owner/repo", "abc1234", "def5678") is True

    def test_behind_by_nonzero_means_real_drift(self, ddc, monkeypatch):
        monkeypatch.setattr(
            ddc.urllib.request,
            "urlopen",
            lambda *a, **k: _fake_response({"behind_by": 3, "ahead_by": 0, "status": "behind"}),
        )
        assert ddc._path_head_is_ancestor("owner/repo", "abc1234", "def5678") is False

    def test_api_failure_does_not_clear_drift(self, ddc, monkeypatch):
        def _raise(*a, **k):
            raise OSError("network blip")

        monkeypatch.setattr(ddc.urllib.request, "urlopen", _raise)
        assert ddc._path_head_is_ancestor("owner/repo", "abc1234", "def5678") is False

    def test_missing_inputs_short_circuit_without_a_network_call(self, ddc, monkeypatch):
        called = mock.MagicMock()
        monkeypatch.setattr(ddc.urllib.request, "urlopen", called)
        assert ddc._path_head_is_ancestor(None, "abc1234", "def5678") is False
        assert ddc._path_head_is_ancestor("owner/repo", "", "def5678") is False
        assert ddc._path_head_is_ancestor("owner/repo", "abc1234", "") is False
        called.assert_not_called()


class TestCheckProductsStatusClassification:
    """check_products() iterates the module-level PRODUCTS dict, so exercise
    exactly one entry (wtf_consumer) with the three lower-level calls it makes
    mocked out — no real network traffic, no dependency on live GitHub state.
    """

    def _isolate_to_wtf_consumer(self, ddc, monkeypatch):
        monkeypatch.setattr(
            ddc,
            "PRODUCTS",
            {"wtf_consumer": ddc.PRODUCTS["wtf_consumer"]},
        )

    def test_exact_match_is_in_sync_without_calling_the_ancestry_fallback(self, ddc, monkeypatch):
        self._isolate_to_wtf_consumer(ddc, monkeypatch)
        monkeypatch.setattr(ddc, "_expected_sha", lambda *a, **k: "cc2284f770000000000000000000000000000000")
        monkeypatch.setattr(ddc, "_baked_sha", lambda *a, **k: "cc2284f77")
        ancestor_call = mock.MagicMock()
        monkeypatch.setattr(ddc, "_path_head_is_ancestor", ancestor_call)

        [result] = ddc.check_products()
        assert result["status"] == "in_sync"
        ancestor_call.assert_not_called()

    def test_repo_head_ahead_of_path_head_is_in_sync_via_ancestry(self, ddc, monkeypatch):
        """The exact #6236 scenario: baked SHA is the repo HEAD at build time,
        NOT the path-head, but it demonstrably contains the path-head."""
        self._isolate_to_wtf_consumer(ddc, monkeypatch)
        monkeypatch.setattr(ddc, "_expected_sha", lambda *a, **k: "1134b11e00000000000000000000000000000000")
        monkeypatch.setattr(ddc, "_baked_sha", lambda *a, **k: "6cbd6ccdf")
        monkeypatch.setattr(ddc, "_path_head_is_ancestor", lambda *a, **k: True)

        [result] = ddc.check_products()
        assert result["status"] == "in_sync"

    def test_genuinely_stale_image_is_still_drift(self, ddc, monkeypatch):
        self._isolate_to_wtf_consumer(ddc, monkeypatch)
        monkeypatch.setattr(ddc, "_expected_sha", lambda *a, **k: "1134b11e00000000000000000000000000000000")
        monkeypatch.setattr(ddc, "_baked_sha", lambda *a, **k: "0ldstalesha")
        monkeypatch.setattr(ddc, "_path_head_is_ancestor", lambda *a, **k: False)

        [result] = ddc.check_products()
        assert result["status"] == "drift"

    def test_unresolvable_expected_sha_stays_fail_open(self, ddc, monkeypatch):
        """No expected SHA at all (repo not wired / API down) must NEVER reach
        the ancestry fallback — there is nothing to compare against."""
        self._isolate_to_wtf_consumer(ddc, monkeypatch)
        monkeypatch.setattr(ddc, "_expected_sha", lambda *a, **k: None)
        monkeypatch.setattr(ddc, "_baked_sha", lambda *a, **k: "6cbd6ccdf")
        ancestor_call = mock.MagicMock()
        monkeypatch.setattr(ddc, "_path_head_is_ancestor", ancestor_call)

        [result] = ddc.check_products()
        assert result["status"] == "fail_open"
        ancestor_call.assert_not_called()
