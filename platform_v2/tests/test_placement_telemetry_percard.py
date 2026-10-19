"""record_placement must accept the per-card fields model_service passes (#5273/#6106).

Regression: model_service._record_placement(**kw) forwarded card_index and
cards_free_gb, record_placement() had no such parameters, and every per-card
decision was dropped behind a "placement telemetry unavailable" warning
(41 in 3h on 2026-10-19).
"""

from __future__ import annotations

import contextlib
import inspect
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import placement_telemetry  # noqa: E402


class _FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))


def _run(**kw):
    cur = _FakeCursor()

    @contextlib.contextmanager
    def fake_cursor(commit=False):
        yield (object(), cur)

    with mock.patch("database.get_db_cursor", fake_cursor, create=True):
        placement_telemetry.record_placement(**kw)
    return cur.calls


class TestPerCardFields(unittest.TestCase):
    def test_signature_accepts_every_field_model_service_sends(self):
        params = inspect.signature(placement_telemetry.record_placement).parameters
        for name in ("card_index", "cards_free_gb"):
            self.assertIn(name, params)

    def test_percard_row_is_written_with_card_fields(self):
        calls = _run(
            model="qwen2.5:7b",
            decision="gpu",
            reason="percard_fits_reserve_intact",
            card_index=1,
            cards_free_gb=(7.9, 11.9),
            needed_gb=5.9,
        )
        self.assertEqual(len(calls), 1)
        sql, params = calls[0]
        self.assertIn("card_index", sql)
        self.assertIn("cards_free_gb", sql)
        self.assertEqual(params[-2], 1)
        self.assertEqual(params[-1], [7.9, 11.9])  # tuple coerced to a list for psycopg2

    def test_legacy_callers_still_write_null_card_fields(self):
        calls = _run(model="m", decision="cpu", reason="budget_short")
        self.assertEqual(len(calls), 1)
        _sql, params = calls[0]
        self.assertIsNone(params[-2])
        self.assertIsNone(params[-1])

    def test_placeholder_count_matches_params(self):
        sql, params = _run(model="m", decision="gpu", reason="resident")[0]
        self.assertEqual(sql.count("%s"), len(params))


if __name__ == "__main__":
    unittest.main()
