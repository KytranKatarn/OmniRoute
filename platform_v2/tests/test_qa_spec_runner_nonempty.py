"""Unit tests for the data-nonempty assertions in qa_spec_runner._run_api_test (KB #270283).

These are the checks that catch an empty-but-HTTP-200 standalone site — the exact
failure mode that let legal/civic serve a blank page through a green QA suite on
2026-06-02. `expect.json_contains` could not express them (exact dict-eq only, and
it throws on top-level arrays), so json_nonempty / min_items / json_gt were added.

Runnable two ways (no network — the session is stubbed):
    docker exec archie_platform python3 -m pytest /app/tests/test_qa_spec_runner_nonempty.py
    docker exec archie_platform python3 /app/tests/test_qa_spec_runner_nonempty.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.qa_spec_runner import _run_api_test  # noqa: E402


class _FakeResp:
    def __init__(self, status, payload, valid_json=True):
        self.status_code = status
        self._payload = payload
        self._valid_json = valid_json

    def json(self):
        if not self._valid_json:
            raise ValueError("not json")
        return self._payload


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp

    def request(self, *args, **kwargs):
        return self._resp


def _run(expect, payload, status=200, valid_json=True):
    test = {"name": "t", "method": "GET", "path": "/api/x", "expect": expect}
    sess = _FakeSession(_FakeResp(status, payload, valid_json))
    return _run_api_test(test, "http://test", sess, None)


def test_min_items_fails_on_empty_array():
    r = _run({"status": [200], "min_items": 1}, [])
    assert r["status"] == "fail"
    assert r["assertions"]["min_items"] == "fail"


def test_min_items_passes_on_nonempty_array():
    r = _run({"status": [200], "min_items": 1}, [{"id": 1}])
    assert r["status"] == "pass"
    assert r["assertions"]["min_items"] == "pass"


def test_json_nonempty_fails_on_empty_dict():
    r = _run({"status": [200], "json_nonempty": True}, {})
    assert r["status"] == "fail"


def test_json_nonempty_passes_on_nonempty_dict():
    r = _run({"status": [200], "json_nonempty": True}, {"total": 1})
    assert r["status"] == "pass"


def test_json_gt_fails_on_zero():
    r = _run({"status": [200], "json_gt": {"total_events": 0}}, {"total_events": 0})
    assert r["status"] == "fail"


def test_json_gt_passes_on_positive():
    r = _run({"status": [200], "json_gt": {"total_events": 0}}, {"total_events": 1021})
    assert r["status"] == "pass"


def test_json_gt_fails_on_missing_key():
    r = _run({"status": [200], "json_gt": {"total_events": 0}}, {"other": 5})
    assert r["status"] == "fail"


def test_json_gt_rejects_bool_true():
    # True == 1 in Python; a boolean must not satisfy "count > 0".
    r = _run({"status": [200], "json_gt": {"ok": 0}}, {"ok": True})
    assert r["status"] == "fail"


def test_array_payload_does_not_crash():
    # The legacy json_contains path threw on top-level arrays; min_items must not.
    r = _run({"status": [200], "min_items": 2}, [1, 2, 3])
    assert r["status"] == "pass"


def test_invalid_json_fails_nonempty_check():
    r = _run({"status": [200], "json_nonempty": True}, None, valid_json=False)
    assert r["status"] == "fail"
    assert r["assertions"]["json_parse"] == "fail"


def test_backward_compat_no_new_keys():
    r = _run({"status": [200]}, {"anything": True})
    assert r["status"] == "pass"
    assert "min_items" not in r["assertions"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
