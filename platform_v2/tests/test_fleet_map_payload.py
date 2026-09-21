"""The A.R.M.A.D.A. node panel can only be as honest as the payload behind it.

Three defects, all the same shape — a field the UI needed was either not fetched,
not passed, or defaulted to a literal:

1. ``list_nodes()`` never SELECTed ``cpu_cores``, a populated column, so the panel
   rendered ``CPU: --`` on all five live nodes while the table held 2/8/12/16/20.
2. ``inference_type`` was ``caps.get("inference_type", "gpu")`` — a bare literal
   default. Measured 2026-09-21: 4 of 5 live nodes declared nothing, and **Citadel**
   (``gpu_available=false``, ``gpu_vram_gb=NULL``, 31.3 GB RAM, ``max_model_gb=6``)
   therefore reported ``'gpu'``. The other three were right only by luck.
3. ``gpu_vram_total_gb`` was never passed, so the panel showed the Starbase as a flat
   "12 GB" — correct as the largest SINGLE card, misleading as the machine, which
   holds 20 GB across two.

⚠️ NON-VACUITY was proven at authoring time against the pre-fix module from git, not
at runtime (see memory: mutation-check-no-runtime-git — a baked-in ``git show`` fails
forever after the merge). Against ``HEAD~`` of fleet_service.py, measured:
    derive_inference_type              -> AttributeError (did not exist)
    Citadel-shaped row                 -> 'gpu'   (now 'cpu')
    cpu_cores in payload               -> KeyError (now 8)
    gpu_vram_total_gb in payload       -> KeyError (now 20)
    'cpu_cores' in the list_nodes SELECT -> False  (now True)
"""

from __future__ import annotations

import io
import os

import pytest

from services import fleet_service as fs

DEPT_HQ_JS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools",
    "department_hq",
    "static",
    "js",
    "department-hq.js",
)

FLEET_SERVICE_PY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "services",
    "fleet_service.py",
)

# Shaped after the real rows measured 2026-09-21.
CITADEL = {"gpu_available": False, "gpu_vram_gb": None, "cpu_cores": 8, "ram_gb": 31.3}
STARBASE = {"gpu_available": True, "gpu_vram_gb": 12, "cpu_cores": 20, "ram_gb": 128}


class TestDeriveInferenceType:
    def test_a_node_with_no_gpu_is_cpu(self):
        # THE bug: this row reported 'gpu' for months.
        assert fs.derive_inference_type(CITADEL, {}) == "cpu"

    def test_a_node_with_a_gpu_is_gpu(self):
        assert fs.derive_inference_type(STARBASE, {}) == "gpu"

    def test_an_explicit_declaration_wins_over_hardware(self):
        # An operator who writes 'cpu' onto GPU hardware means it — a card reserved
        # for ComfyUI, say. Deriving must not override a deliberate statement.
        assert fs.derive_inference_type(STARBASE, {"inference_type": "cpu"}) == "cpu"

    def test_an_explicit_gpu_declaration_survives_missing_hardware(self):
        assert fs.derive_inference_type(CITADEL, {"inference_type": "gpu"}) == "gpu"

    def test_a_declaration_is_normalised(self):
        assert fs.derive_inference_type(CITADEL, {"inference_type": "  GPU  "}) == "gpu"

    def test_a_blank_declaration_counts_as_absent(self):
        # Must fall through to the derivation, never be returned as ''.
        assert fs.derive_inference_type(CITADEL, {"inference_type": "   "}) == "cpu"
        assert fs.derive_inference_type(STARBASE, {"inference_type": ""}) == "gpu"

    def test_a_flagged_gpu_with_no_vram_reads_as_cpu(self):
        # Both signals are required: a row that cannot state its VRAM cannot size a
        # single model, so reporting it as a GPU node of unknown capacity is worse
        # than reporting CPU.
        row = {"gpu_available": True, "gpu_vram_gb": None}
        assert fs.derive_inference_type(row, {}) == "cpu"

    def test_vram_may_come_from_extra_capabilities(self):
        row = {"gpu_available": True, "gpu_vram_gb": None}
        assert fs.derive_inference_type(row, {"gpu_vram_gb": 8}) == "gpu"

    def test_caps_may_be_omitted_entirely(self):
        assert fs.derive_inference_type(CITADEL) == "cpu"


@pytest.fixture
def map_data(monkeypatch):
    """get_fleet_map_data over two synthetic rows — no DB, so no vacuous pass."""
    rows = [
        dict(
            CITADEL,
            id=128,
            node_id="outpost_e834ff6949a3d7a6",
            node_name="Citadel - United States",
            hostname="2.25.133.122",
            status="online",
            latitude=42.36,
            longitude=-71.06,
            extra_capabilities={"max_model_gb": 6},
        ),
        dict(
            STARBASE,
            id=68,
            node_id="archie-starbase",
            node_name="Starbase - A.R.C.H.I.E.",
            hostname="192.168.1.200",
            status="online",
            latitude=45.5,
            longitude=-73.57,
            gpu_model="TITAN X 12GB + Quadro M4000 8GB",
            extra_capabilities={"gpu_vram_total_gb": 20},
        ),
    ]
    monkeypatch.setattr(fs, "live_nodes", lambda: rows)
    monkeypatch.setattr(fs, "get_node_agents", lambda _id: [])
    monkeypatch.setattr(fs, "list_providers", lambda: [])
    return {n["name"]: n for n in fs.get_fleet_map_data()["nodes"]}


class TestPayload:
    def test_cpu_cores_reaches_the_panel(self, map_data):
        assert map_data["Citadel - United States"]["cpu_cores"] == 8
        assert map_data["Starbase - A.R.C.H.I.E."]["cpu_cores"] == 20

    def test_cpu_cores_falls_back_to_extra_capabilities(self, monkeypatch):
        row = {
            "id": 9,
            "node_name": "N",
            "status": "online",
            "cpu_cores": None,
            "extra_capabilities": {"cpu_cores": 4},
        }
        monkeypatch.setattr(fs, "live_nodes", lambda: [row])
        monkeypatch.setattr(fs, "get_node_agents", lambda _id: [])
        monkeypatch.setattr(fs, "list_providers", lambda: [])
        assert fs.get_fleet_map_data()["nodes"][0]["cpu_cores"] == 4

    def test_the_declared_vram_total_is_passed_through(self, map_data):
        hub = map_data["Starbase - A.R.C.H.I.E."]
        # Largest single card and the aggregate are DIFFERENT numbers and both travel.
        assert hub["gpu_vram_gb"] == 12
        assert hub["gpu_vram_total_gb"] == 20

    def test_an_undeclared_vram_total_stays_absent(self, map_data):
        # Not back-filled from gpu_vram_gb: absence of a declaration is not proof of a
        # single card, and inventing the total is how "12 GB" became "the machine".
        assert map_data["Citadel - United States"]["gpu_vram_total_gb"] is None

    def test_inference_type_is_derived_not_defaulted(self, map_data):
        assert map_data["Citadel - United States"]["inference_type"] == "cpu"
        assert map_data["Starbase - A.R.C.H.I.E."]["inference_type"] == "gpu"


class TestTheFieldsArePubliclyFetched:
    """The original bug was upstream of the payload: a column the panel needed was
    never in the SELECT, so no amount of payload work could surface it. Running
    list_nodes() needs a DB, so this reads the query text — the one thing that can
    fail without one."""

    def test_the_node_query_fetches_what_the_payload_reads(self):
        src = io.open(FLEET_SERVICE_PY, encoding="utf-8").read()
        start = src.index("def list_nodes(")
        query = src[start : src.index("FROM remote_nodes", start)]
        for col in ("cpu_cores", "gpu_available", "gpu_vram_gb", "cpu_model"):
            assert col in query, "list_nodes must SELECT %s — the payload reads it" % col


class TestBothNodeIdentitiesTravel:
    """`remote_nodes` has an int PK `id` AND a varchar `node_id`, and the payload names
    the INT one `node_id`. 20+ node routes are `<int:node_id>` and want exactly that, so
    the name is not simply wrong — but ONE route, GET
    /api/nodes/<node_id>/model-recommendation, looks up `WHERE node_id = %s`.

    Given the int it returns a clean **404 "Node not found"** — the URL segment arrives
    as a string, so `WHERE node_id = '93'` is a valid comparison matching nothing. No
    exception, no error log. Measured live 2026-09-21: id 93 -> 404, 'outpost_us_001' ->
    200 with real hardware. The panel rendered "Recommendation unavailable", which is
    also what a node with no recommendation would show, so the AI Models section had
    never once loaded and nothing said so.

    fleet.md calls id-vs-node_id a recurring trap and says to keep them apart.
    """

    def test_the_payload_carries_both(self, map_data):
        hub = map_data["Starbase - A.R.C.H.I.E."]
        assert hub["node_id"] == 68, "node_id stays the int PK the other 20+ routes want"
        assert hub["node_key"] == "archie-starbase", "node_key is the varchar identity"

    def test_they_are_different_kinds(self, map_data):
        # The whole defect is that one was substituted for the other. If these ever
        # become the same type, a mix-up stops being detectable by inspection.
        n = map_data["Citadel - United States"]
        assert isinstance(n["node_id"], int)
        assert isinstance(n["node_key"], str)

    def test_node_key_survives_a_missing_varchar(self, monkeypatch):
        # A row with no varchar identity yields None, and the caller guards on it,
        # rather than silently falling back to the int and 404ing.
        row = {"id": 5, "node_name": "N", "status": "online", "extra_capabilities": {}}
        monkeypatch.setattr(fs, "live_nodes", lambda: [row])
        monkeypatch.setattr(fs, "get_node_agents", lambda _i: [])
        monkeypatch.setattr(fs, "list_providers", lambda: [])
        assert fs.get_fleet_map_data()["nodes"][0]["node_key"] is None

    def test_the_recommendation_call_uses_the_key_not_the_pk(self):
        """The gap this defect lived in: the payload was right for its 20 consumers and
        the route was right for its own lookup. Only the JOIN between them was wrong, so
        neither a payload test nor a route test could see it. This reads the call site."""
        js = io.open(DEPT_HQ_JS, encoding="utf-8").read()
        i = js.index("model-recommendation'")
        window = js[max(0, i - 3000) : i]
        assert "var nid = node.node_key;" in window, (
            "the model-recommendation fetch must build its URL from node_key — node_id "
            "is the int PK and 404s against this route's varchar lookup"
        )
        assert "var nid = node.node_id;" not in window
