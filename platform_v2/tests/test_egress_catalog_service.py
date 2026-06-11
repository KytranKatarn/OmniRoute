"""Tests for egress_catalog_service (#4007).

The hub-path of is_valid_egress needs no DB; node validation is tested with
list_egress_nodes monkeypatched so the suite stays DB-free + deterministic.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import egress_catalog_service as ec  # noqa: E402


class TestIsValidEgress:
    def test_hub_aliases_valid_without_db(self):
        # These must short-circuit before any DB call.
        assert ec.is_valid_egress(None)
        assert ec.is_valid_egress("")
        assert ec.is_valid_egress("hub")
        assert ec.is_valid_egress("HUB")
        assert ec.is_valid_egress("auto")

    def test_ready_node_valid(self, monkeypatch):
        monkeypatch.setattr(
            ec,
            "list_egress_nodes",
            lambda: [
                dict(ec.HUB),
                {"node_name": "Outpost - United Kingdom", "country": "United Kingdom", "egress_ready": True},
                {"node_name": "Outpost - Singapore", "country": "Singapore", "egress_ready": False},
            ],
        )
        assert ec.is_valid_egress("Outpost - United Kingdom")

    def test_unready_node_invalid(self, monkeypatch):
        monkeypatch.setattr(
            ec,
            "list_egress_nodes",
            lambda: [
                dict(ec.HUB),
                {"node_name": "Outpost - Singapore", "country": "Singapore", "egress_ready": False},
            ],
        )
        assert not ec.is_valid_egress("Outpost - Singapore")

    def test_unknown_node_invalid(self, monkeypatch):
        monkeypatch.setattr(ec, "list_egress_nodes", lambda: [dict(ec.HUB)])
        assert not ec.is_valid_egress("Outpost - Atlantis")


def test_hub_constant_is_ready_and_first():
    # The synthetic hub entry is always selectable and is prepended by
    # list_egress_nodes so the UI default is hub.
    assert ec.HUB["node_name"] == "hub"
    assert ec.HUB["egress_ready"] is True
