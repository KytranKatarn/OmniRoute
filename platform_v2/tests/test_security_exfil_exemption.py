"""#5308 — the exfiltration detector must not flag the hub for being a server.

EVIDENCE (2026-07-27): 'Possible exfiltration: 192.168.1.200' fired 4x in one day
(Upload 787→876 GB vs ~156 GB down, ratio 5.0–5.6x). Triage — both an independent
hand triage AND S.H.I.E.L.D.'s delegated analysis (#5305) — reached the same
verdict: the 'upload' is the hub's OWN Plex/Jellyfin streaming to the registered
Fire TV (192.168.1.76), plus DR WAL streaming, backup tier-sync, and mesh
dispatch. Upload >> download is the hub's DESIGNED profile.

network_traffic_stats has NO destination column, so a LAN-vs-WAN flow split is
impossible with current data — the per-host exemption is the available lever.
This test pins the exempt-set composition: dropping hub_ips from the union
re-opens the 4-alerts-a-day false positive and the bell/dashboard pollution.
"""

import os
import sys

_TREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TREE_ROOT not in sys.path:
    sys.path.insert(0, _TREE_ROOT)

import tools.security_network.anomaly_detection as ad  # noqa: E402


class TestExfilExemptSet:
    def test_union_includes_all_three_sources(self):
        out = ad._exfil_exempt_ip_set({"10.0.0.1"}, {"10.0.0.2"}, {"192.168.1.200"})
        assert out == {"10.0.0.1", "10.0.0.2", "192.168.1.200"}

    def test_hub_and_fleet_ips_are_exempt_by_default(self):
        """The #5308 change itself: the hub/fleet hosts land in the exempt set."""
        hub_ips = ad._get_hub_ips()
        assert "192.168.1.200" in hub_ips, "hub LAN IP missing from _get_hub_ips"
        out = ad._exfil_exempt_ip_set(set(), set(), hub_ips)
        assert "192.168.1.200" in out
        assert "192.168.1.246" in out and "192.168.1.245" in out

    def test_empty_inputs_yield_empty_set(self):
        assert ad._exfil_exempt_ip_set(set(), set(), set()) == set()

    def test_inputs_are_not_mutated(self):
        iot = {"a"}
        ad._exfil_exempt_ip_set(iot, {"b"}, {"c"})
        assert iot == {"a"}
