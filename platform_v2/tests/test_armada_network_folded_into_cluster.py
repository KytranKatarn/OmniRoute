"""A.R.M.A.D.A. NETWORK sub-tab retired — its contents must survive the move.

Owner request 2026-09-11: put REPAIR NODE / ADD NODE and the fleet map on the
CLUSTER sub-tab, then delete NETWORK. Two things made that more than a cut-paste:

1. CLUSTER already had its OWN map — "FLEET WORLD MAP" (#clusterGeoMap, #3230),
   the same nodes as plain coloured dots. Keeping both would have put two Leaflet
   instances on one tab painting one /api/fleet-map response. The circular map is
   a strict superset (node logos, live online/offline styling, contractor
   favicons), so it replaced the dot map rather than joining it.

2. FLEET USAGE (30 DAYS) is CONTRACTOR spend, not node state, and its
   loadFleetUsage() painter ALSO fills #fleetBudgetTableBody on the Contractors
   tab. Moving the panel to Contractors keeps one function feeding two panels
   that can never disagree; deleting the function would have silently emptied
   the budget table.

These are source-level assertions — the markup is a 3k-line template and the
switcher is a string in a 7k-line JS file, so there is no seam to unit-test.
A check that names the defect beats no check.
"""

import pathlib
import re

import pytest

DHQ = pathlib.Path(__file__).resolve().parents[1] / "tools" / "department_hq"
TPL = DHQ / "templates" / "department_hq.html"
JS = DHQ / "static" / "js" / "department-hq.js"


def _src(p: pathlib.Path) -> str:
    if not p.exists():
        pytest.skip(f"{p} not reachable from this test root")
    return p.read_text()


_TRIPLE_D = chr(34) * 3
_TRIPLE_S = chr(39) * 3


def _code_only(src: str) -> str:
    """Source with comments and docstrings removed.

    Written after making the SAME mistake three times in one session: a check of
    the form "this bad pattern must not appear" matched the COMMENT explaining
    why the pattern was removed. `"clusterGeoMap" not in tpl` hit the note saying
    it was deleted; the square-map check hit the retirement note quoting the old
    rule; `'"starbase" in' not in src` hit the warning about substring matching.

    A negative source assertion has to run against code, never against the
    file's own explanation of itself.
    """
    out = re.sub(_TRIPLE_D + r"[\s\S]*?" + _TRIPLE_D, "", src)
    out = re.sub(_TRIPLE_S + r"[\s\S]*?" + _TRIPLE_S, "", out)
    out = re.sub(r"/\*[\s\S]*?\*/", "", out)
    keep = []
    for line in out.splitlines():
        st = line.strip()
        if st.startswith("#") or st.startswith("//"):
            continue
        keep.append(line)
    return "\n".join(keep)


class TestTheNetworkSubTabIsGone:
    def test_no_network_button(self):
        assert "switchArmadaSection('network')" not in _src(TPL)
        assert 'id="armadaBtn-network"' not in _src(TPL)

    def test_no_network_section_or_wrapper(self):
        tpl = _src(TPL)
        assert 'id="armadaSection-network"' not in tpl
        assert 'id="fleetNetworkContent"' not in tpl

    def test_the_switcher_no_longer_lists_it(self):
        m = re.search(r"var sections = \[([^\]]+)\]", _src(JS))
        assert m, "the armada sections array has moved"
        assert "network" not in m.group(1)

    def test_a_stored_network_preference_cannot_blank_the_tab(self):
        """⚠️ THE upgrade hazard. switchArmadaSection persists to localStorage
        ('dhq_armada_section'), so anyone whose last visit was NETWORK reopens
        DHQ with a value matching no section — every panel hidden, no button
        lit, a blank A.R.M.A.D.A. tab. It must normalise to cluster."""
        js = _src(JS)
        i = js.index("function switchArmadaSection")
        head = js[i : i + 900]
        assert "indexOf(s) === -1" in head, "no fallback for an unknown/stored section"
        guard = re.search(r"if \(sections\.indexOf\(s\) === -1\)[^\n]*", head)
        assert guard and "'cluster'" in guard.group(0)
        # and it must run BEFORE the show/hide loop, or the blank frame still renders
        assert head.index("indexOf(s) === -1") < head.index("sections.forEach")


class TestClusterInheritedTheMapAndButtons:
    def _cluster(self) -> str:
        tpl = _src(TPL)
        start = tpl.index('id="armadaSection-cluster"')
        end = tpl.index('id="panel-contractors"')
        return tpl[start:end]

    def test_node_buttons_live_on_cluster_now(self):
        blk = self._cluster()
        assert "openRepairNodeModal()" in blk
        assert "openAddNodeModal()" in blk

    def test_the_fleet_map_lives_on_cluster_now(self):
        blk = self._cluster()
        assert 'id="fleetMap"' in blk and 'id="fleetMapContainer"' in blk

    def test_the_duplicate_dot_map_is_gone(self):
        """Two maps drawing one payload is the thing this change removed."""
        assert 'id="clusterGeoMap"' not in _src(TPL)
        js = _src(JS)
        assert "function loadClusterMap" not in js
        assert "loadClusterMap()" not in js, "a call survives its function — TypeError on open"
        assert "_clusterGeoMap" not in js

    def test_cluster_initialises_the_map_it_now_owns(self):
        """The map used to be initialised by the NETWORK mount branch. If the
        cluster branch does not do it, the panel renders an empty grey box."""
        js = _src(JS)
        i = js.index("if (s === 'cluster')")
        blk = js[i : i + 700]
        assert "initFleetMap()" in blk
        assert "invalidateSize" in blk, (
            "Leaflet measures 0x0 while the section is display:none and never "
            "re-measures on its own — without this the tiles render clipped"
        )


class TestFleetUsageMovedToContractors:
    def test_the_panel_is_on_the_contractors_tab(self):
        tpl = _src(TPL)
        usage = tpl.index('id="fleetUsageCalls"')
        contractors = tpl.index('id="panel-contractors"')
        assert usage > contractors, "FLEET USAGE must sit inside panel-contractors"

    def test_it_is_not_left_behind_on_cluster(self):
        tpl = _src(TPL)
        cluster = tpl.index('id="armadaSection-cluster"')
        contractors = tpl.index('id="panel-contractors"')
        assert not (cluster < tpl.index('id="fleetUsageCalls"') < contractors)

    def test_its_painter_survives_because_it_also_fills_the_budget_table(self):
        """⚠️ loadFleetUsage() sets the three usage figures AND populates
        #fleetBudgetTableBody. Deleting it along with the panel would have left
        PROVIDER BUDGETS permanently empty with nothing raising."""
        js = _src(JS)
        assert "async function loadFleetUsage" in js
        i = js.index("async function loadFleetUsage")
        assert "fleetBudgetTableBody" in js[i : i + 3000]
        assert "loadFleetUsage()" in js, "the function has no callers left"

    def test_the_hidden_providers_grid_container_survived(self):
        """The provider CARDS moved to Contractors long ago; the container did
        not. loadCloudProviders()/loadProviderManagement() still write into it."""
        assert 'id="fleetProvidersGrid"' in _src(TPL)


CSS = DHQ / "static" / "css" / "department-hq.css"


class TestTheMapIsRectangularWithASonarOverlay:
    """The map box WAS the circle: a square div with border-radius:50%, sized
    `width:min(560px,calc(100vw - 210px))` and the same expression for height,
    inside a flex row with flex-shrink:1.

    That draws an EGG, and not by rounding error. flex-shrink acts on the MAIN
    axis only, so the flex algorithm narrowed the width while the height kept its
    computed value — the two stopped matching as soon as the row ran short. The
    viewport-relative calc() guaranteed it would: it measures the WINDOW, but the
    box lives inside a padded column inside an LCARS frame, so the value was
    always larger than the space available and shrink always fired.

    A map is rectangular. It now fills its column; the circle survives as a
    decorative sonar overlay, which cannot distort because its rings size off the
    container height and hold their own aspect-ratio.
    """

    def test_the_map_box_is_no_longer_a_circle(self):
        tpl = _src(TPL)
        i = tpl.index('id="fleetMapContainer"')
        box = tpl[i : i + 400]
        assert "border-radius:50%" not in box, "the map box is round again — egg incoming"
        assert "fleet-map-frame" in box

    def test_it_no_longer_sizes_itself_off_the_viewport(self):
        """calc(100vw - …) measures the window, not the column the box sits in."""
        tpl = _src(TPL)
        i = tpl.index('id="fleetMapContainer"')
        assert "100vw" not in tpl[i : i + 400]

    def test_the_frame_fills_its_column_and_has_real_height(self):
        css = _src(CSS)
        i = css.index(".fleet-map-frame")
        blk = css[i : i + 400]
        assert "width: 100%" in blk
        assert "height: clamp(" in blk, "a fixed px height will not adjust to the screen"

    def test_the_overlay_cannot_eat_map_gestures(self):
        """⚠️ LOAD-BEARING. An overlay stretched across the map with default
        pointer-events swallows every drag and wheel event, and the map silently
        stops panning and zooming — it still LOOKS right, which is the worst
        version of this bug."""
        css = _src(CSS)
        i = css.index(".fleet-sonar {")
        assert "pointer-events: none" in css[i : i + 300]

    def test_the_rings_are_circles_at_any_container_width(self):
        css = _src(CSS)
        i = css.index(".fleet-sonar-ring,")
        assert (
            "aspect-ratio: 1 / 1" in css[i : i + 300]
        ), "without aspect-ratio the rings stretch with the rectangle — the egg, moved"

    def test_ring_sizes_are_keyed_by_class_not_sibling_position(self):
        """nth-of-type counts every <span>, and the crosshairs are spans too —
        adding one decoration element would silently resize all three rings."""
        css = _src(CSS)
        assert ".fleet-sonar-ring.r1" in css
        assert ".fleet-sonar-ring:nth-of-type" not in css

    def test_motion_is_optional(self):
        assert "prefers-reduced-motion" in _src(CSS)


class TestTheIndexIsThreeColumns:
    def test_three_columns_declared(self):
        css = _src(CSS)
        assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css

    def test_no_important_override_can_un_grid_it(self):
        """⚠️ There WAS one. A @media(max-width:767px) block forced
        `flex-direction`/`flex-wrap` on #fleetNodeIndex with !important and
        re-sized the map to a SQUARE via
        `width/height: min(500px, calc(100vw - 40px)) !important` — which
        re-creates the circular box, wins on !important, and puts the egg back
        below 767px. It is retired; this stops it coming back."""
        css = _src(CSS)
        for decl in css.split("}"):
            if "#fleetNodeIndex" in decl or "#fleetMapContainer" in decl:
                body = decl.split("{", 1)[1] if "{" in decl else ""
                # strip comments before judging — the retirement note quotes the old rule
                assert "!important" not in body, f"an !important override is back: {decl[:120]}"

    def test_headers_span_the_full_width(self):
        """A section header landing in one grid cell reads as a list item."""
        assert "grid-column: 1 / -1" in _src(CSS)
        js = _src(JS)
        assert "fleet-index-head" in js, "the JS-built headers never get the class"

    def test_it_collapses_on_narrow_screens(self):
        css = _src(CSS)
        assert "max-width: 900px" in css and "max-width: 560px" in css


class TestRetiredNodesNeverReachTheMap:
    """The map rendered Beacon plus the three EU/Asia outposts retired on
    2026-08-29 — machines whose subscriptions are cancelled — as live pins and
    index rows, because ``list_nodes()`` has no status filter and
    ``get_fleet_map_data`` called it directly.

    ⚠️ THIRD instance of one shape. LOADED MODELS showed the same three outposts
    off ``model_load_state`` (#3290); NODE HEALTH, on the same page, filtered
    correctly the whole time. The table is never the bug — each panel deciding
    for itself whether to filter is. ``live_nodes()`` is the one place to decide.
    """

    def _svc(self, monkeypatch, rows):
        from services import fleet_service

        monkeypatch.setattr(fleet_service, "list_nodes", lambda: rows)
        return fleet_service

    ROWS = [
        {"node_name": "Archie Starbase", "status": "online"},
        {"node_name": "Starship - Defiant - USS-246", "status": "online"},
        {"node_name": "Outpost - Singapore", "status": "retired"},
        {"node_name": "Outpost - Lithuania", "status": "retired"},
        {"node_name": "Beacon", "status": "retired"},
    ]

    def test_retired_nodes_are_dropped(self, monkeypatch):
        svc = self._svc(monkeypatch, self.ROWS)
        names = [n["node_name"] for n in svc.live_nodes()]
        assert "Outpost - Singapore" not in names
        assert "Beacon" not in names
        assert len(names) == 2

    def test_an_OFFLINE_node_still_shows(self, monkeypatch):
        """Offline is news — the node exists and is down, and hiding it would
        turn an outage into silence. Retired is noise: it does not exist."""
        rows = self.ROWS + [{"node_name": "Starship - Runabout - USS-245", "status": "offline"}]
        svc = self._svc(monkeypatch, rows)
        assert "Starship - Runabout - USS-245" in [n["node_name"] for n in svc.live_nodes()]

    def test_an_unknown_status_is_kept_not_guessed_away(self, monkeypatch):
        """Fail-OPEN: only the literal 'retired' is excluded. A node with a
        status we do not recognise stays visible rather than vanishing."""
        rows = [{"node_name": "Mystery", "status": None}, {"node_name": "Odd", "status": "provisioning"}]
        svc = self._svc(monkeypatch, rows)
        assert len(svc.live_nodes()) == 2

    def test_it_filters_on_status_not_a_hardcoded_name_list(self, monkeypatch):
        """Retiring the NEXT node must need no code change."""
        import inspect
        from services import fleet_service

        src = inspect.getsource(fleet_service.live_nodes)
        assert "Singapore" not in src and "Beacon" not in src.split('"""')[2]
        assert "status" in src

    def test_the_map_builder_uses_it(self):
        import inspect
        from services import fleet_service

        src = inspect.getsource(fleet_service.get_fleet_map_data)
        assert "live_nodes()" in src
        assert "list_nodes()" not in src, "the map is back on the unfiltered accessor"


class TestTheProviderCountDescribesTheMap:
    """The panel read "26 providers active" beside SIX pins. Both numbers were
    honest about different populations: 26 is the count of active rows in
    contractor_providers (the same list the Contractors tab shows), while a pin
    needs a lat/lon, which comes from the hardcoded PROVIDER_LOCATIONS dict.

    Twenty missed. Three of those were pure KEY mismatches — the coordinates
    already existed under a name no provider row uses (`anthropic` vs `claude`,
    `cloudflare` vs `cloudflare_ai`, `grok` vs `xai`).
    """

    def test_the_key_mismatches_are_fixed(self):
        from services.fleet_service import PROVIDER_LOCATIONS

        for real_key in ("claude", "cloudflare_ai", "xai"):
            assert real_key in PROVIDER_LOCATIONS, f"{real_key} still has no location"

    def test_the_label_counts_what_can_be_drawn(self):
        js = _src(JS)
        i = js.index("function updateFleetStats")
        blk = js[i : i + 1400]
        assert "mappable" in blk, "the label still counts rows the map cannot draw"
        assert "of ' + provCount" in blk or "of '+provCount" in blk

    def test_third_party_routers_are_deliberately_unmapped_not_forgotten(self):
        """openrouter brokers to whichever upstream wins, so it has no single
        inference location; pollinations has none I can confirm. Pinning either
        to an office would draw a fact that is not true — the absence is a
        recorded decision, not an oversight."""
        import inspect
        from services import fleet_service

        src = inspect.getsource(fleet_service)
        assert "DELIBERATELY ABSENT" in src
        for k in ("openrouter", "pollinations"):
            assert k in src
            assert k not in fleet_service.PROVIDER_LOCATIONS

    def test_self_hosted_providers_are_pinned_to_the_hub(self):
        """⚠️ omniroute was first excluded as "a router" on the strength of its
        NAME. Its base_url is http://omniroute:20128/v1 — a Docker service name,
        a container on the hub. For self-hosted providers the hub is not an
        approximation, it is the address; excluding them hides real infrastructure
        from the fleet map."""
        from services.fleet_service import HUB_LOCATION, PROVIDER_LOCATIONS

        for key in ("omniroute", "comfyui", "ollama_diffuser"):
            assert key in PROVIDER_LOCATIONS, f"{key} is self-hosted but has no pin"
            assert PROVIDER_LOCATIONS[key]["lat"] == HUB_LOCATION["lat"]
            assert PROVIDER_LOCATIONS[key]["lon"] == HUB_LOCATION["lon"]


class TestHostedIsItsOwnSection:
    """Owner request: a HOSTED section between NODES and CONTRACTORS, because a
    provider we run in Docker is not a contractor.

    The split is DERIVED from base_url, never a name list — the four live cases
    are all distinguishable (measured 2026-09-11):
        http://archie_comfyui:8188 / http://archie_diffuser:11435 /
        http://omniroute:20128/v1  — bare docker service names
        http://localhost:7682/v1   — loopback
    against 22 external https:// FQDNs.
    """

    def test_the_classifier_reads_the_url_not_the_name(self):
        import inspect
        from services.fleet_service import is_self_hosted_url

        src = inspect.getsource(is_self_hosted_url)
        # strip the docstring — it cites the real base_urls as measured examples,
        # and grepping prose instead of code is how a check passes on its own text
        body = src.split('"""', 2)[-1]
        for name in ("comfyui", "omniroute", "ollama_diffuser", "claude"):
            assert name not in body, "the classifier hardcodes a provider name"

    def test_the_four_real_shapes_classify_correctly(self):
        from services.fleet_service import is_self_hosted_url

        for url in (
            "http://archie_comfyui:8188",
            "http://archie_diffuser:11435",
            "http://omniroute:20128/v1",
            "http://localhost:7682/v1",
            "http://192.168.1.200:3000",
            "http://100.64.0.4:3000",  # Headscale mesh
            "http://10.0.0.5/v1",
            "http://172.20.0.3:8080",
        ):
            assert is_self_hosted_url(url) is True, url

        for url in (
            "https://api.openai.com/v1",
            "https://openrouter.ai/api/v1",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "https://fal.run",
        ):
            assert is_self_hosted_url(url) is False, url

    def test_a_non_url_sentinel_is_external(self):
        """qwen3_cloud/minimax_cloud carry base_url 'ollama_cloud_proxy' — not a
        URL at all. It has no dot, so a naive 'no dot means docker' rule would
        call a CLOUD provider self-hosted."""
        from services.fleet_service import is_self_hosted_url

        assert is_self_hosted_url("ollama_cloud_proxy") is False

    def test_it_fails_safe_toward_external(self):
        """Mislabelling a cloud API as ours understates where data goes — the
        expensive direction to be wrong in."""
        from services.fleet_service import is_self_hosted_url

        for bad in (None, "", "://", "not a url", 12345):
            assert is_self_hosted_url(bad) is False, bad

    def test_hosted_is_not_the_same_claim_as_local_compute(self):
        """⚠️ omniroute and claude answer at an address we own and do their
        thinking elsewhere. A panel that calls all four 'hosted' full stop is
        claiming we run Claude on our GPUs."""
        from services.fleet_service import LOCAL_COMPUTE_PROVIDERS

        assert "comfyui" in LOCAL_COMPUTE_PROVIDERS
        assert "ollama_diffuser" in LOCAL_COMPUTE_PROVIDERS
        assert "claude" not in LOCAL_COMPUTE_PROVIDERS
        assert "omniroute" not in LOCAL_COMPUTE_PROVIDERS

    def test_the_payload_carries_both_flags(self):
        import inspect
        from services import fleet_service

        src = inspect.getsource(fleet_service.get_fleet_map_data)
        assert '"self_hosted": is_self_hosted_url(' in src
        assert '"local_compute": key in LOCAL_COMPUTE_PROVIDERS' in src

    def test_the_index_renders_hosted_between_nodes_and_contractors(self):
        js = _src(JS)
        i = js.index("function renderFleetIndex")
        # search forward from the function start — no fixed window. A window is a
        # magic number that silently turns "out of order" into "not found": the
        # first cut used 6000 and the contractor section begins at offset 5999.
        order = [
            js.index(tok, i)
            for tok in ("'STARBASE'", "'NODES'", "'MESH'", "fleetHostedSection", "fleetContractorSection")
        ]
        assert order == sorted(order), (
            "index sections are out of order; expected " "STARBASE -> NODES -> MESH -> HOSTED -> CONTRACTORS"
        )

    def test_each_hosted_row_says_which_kind_it_is(self):
        js = _src(JS)
        i = js.index("fleetHostedSection")
        blk = js[i : i + 1600]
        assert "local gpu" in blk and "gateway" in blk

    def test_self_hosted_providers_get_no_map_pin(self):
        """They sit at the hub. Pinning them stacks four markers on the hub's own
        pin and makes the cluster look bigger than it is."""
        js = _src(JS)
        # .index() finds the function DEFINITION first; the CALL is what matters
        i = js.index("jitterClusteredProviders(pinnable)")
        blk = js[max(0, i - 500) : i + 120]
        assert "!p.self_hosted" in blk, "self-hosted providers are being pinned again"

    def test_contractors_exclude_the_hosted_ones(self):
        js = _src(JS)
        i = js.index("var contractors = ")
        assert "!p.self_hosted" in js[i : i + 160], "hosted rows double-counted as contractors"

    def test_the_stat_reports_both_populations(self):
        js = _src(JS)
        i = js.index("function updateFleetStats")
        blk = js[i : i + 1800]
        assert "hostedCount" in blk
        assert "' hosted'" in blk


class TestTheHubIsOneEndpointNotTwo:
    """`hub` was hardcoded from HUB_LOCATION while remote_nodes ALSO held a real
    row for the same machine (node_name 'Archie Starbase', deployment_mode
    'starbase'). They sat 22 m apart — 45.5017/-73.5673 vs 45.5019/-73.5674 — so
    the tab drew two pins and listed two rows for ONE computer, and the index
    showed 6 entries while the stat line said 5 nodes.
    """

    def _rows(self):
        return [
            {"name": "Archie Starbase", "deployment_mode": "starbase", "lat": 45.5019, "lon": -73.5674},
            {"name": "Citadel - United States", "deployment_mode": "starbase_outpost", "lat": 42.36, "lon": -71.06},
            {"name": "Outpost - United States", "deployment_mode": "outpost", "lat": 38.89, "lon": -77.47},
        ]

    def test_the_hub_row_is_matched_EXACTLY_not_by_substring(self):
        """⚠️ Citadel's deployment_mode is 'starbase_outpost'. `"starbase" in
        mode` flags it as a SECOND hub — the same nearly-right check that has
        produced every other defect on this tab."""
        import inspect
        from services import fleet_service

        code = _code_only(inspect.getsource(fleet_service.get_fleet_map_data))
        assert '== "starbase"' in code, "hub detection is not an exact match"
        assert '"starbase" in' not in code, "substring match would flag Citadel as a second hub"

        modes = [r["deployment_mode"] for r in self._rows()]
        hubs = [m for m in modes if m == "starbase"]
        assert hubs == ["starbase"], "exactly one row may be the hub"

    def test_the_db_row_wins_over_the_hardcoded_literal(self):
        """The DB row is the canonical identity every other panel shows and
        carries live hardware/status; HUB_LOCATION is a frozen literal."""
        import inspect
        from services import fleet_service

        src = inspect.getsource(fleet_service.get_fleet_map_data)
        assert 'hub_node["is_hub"] = True' in src
        assert "name=hub_node.get(" in src

    def test_the_hub_row_STAYS_in_nodes(self):
        """It is a real machine. Removing it from `nodes` would drop the fleet
        count from 5 to 4 — trading a double-count for an under-count."""
        import inspect
        from services import fleet_service

        src = inspect.getsource(fleet_service.get_fleet_map_data)
        assert "nodes.remove" not in src and "del nodes" not in src

    def test_the_ui_skips_the_duplicate_in_BOTH_places(self):
        """Index and markers are separate loops; fixing one leaves the other
        drawing two hubs."""
        js = _src(JS)
        assert js.count("!n.is_hub") >= 2, "is_hub is filtered in fewer than two places"
        i_idx = js.index("function renderFleetIndex")
        i_pins = js.index("function renderFleetPins")
        lo, hi = sorted((i_idx, i_pins))
        assert "!n.is_hub" in js[lo : hi + 4000]


class TestCoincidentNodesAreSeparable:
    """USS-245 and USS-246 carry BYTE-IDENTICAL coordinates (45.5017/-73.667 —
    the same house), so no zoom level can ever separate them and the pins sat
    exactly on top of each other even at max zoom.

    ⚠️ The provider spreader could not be reused as-is: its 0.22° radius is
    ~24 km, which is fine for two San Francisco head offices and a lie about two
    machines in one room. Nodes get ~1.3 km — measured at ~70 px apart at zoom
    12 (markers are 34 px) and under 1 px when zoomed out, which is what they
    actually are.
    """

    def test_there_is_ONE_spreader_not_two_copies(self):
        js = _src(JS)
        assert js.count("function spreadCoincident(") == 1
        assert (
            "return spreadCoincident(providers, 0.18, 0.22)" in js
        ), "provider behaviour must be unchanged by the refactor"

    def test_nodes_use_a_tighter_radius_than_providers(self):
        js = _src(JS)
        m = re.search(
            r"function spreadCoincidentNodes\(nodes\) \{\s*return spreadCoincident\(nodes, ([\d.]+), ([\d.]+)\)", js
        )
        assert m, "spreadCoincidentNodes not found"
        cluster, spread = float(m.group(1)), float(m.group(2))
        assert spread < 0.05, f"{spread}° is kilometres of fiction for machines in one room"
        assert cluster < 0.05
        assert spread > 0.005, "too small to separate 34px markers even at max zoom"

    def test_both_render_paths_spread(self):
        """Index click-to-zoom and the markers must agree, or clicking a node
        flies to a point where its pin is not."""
        js = _src(JS)
        assert js.count("spreadCoincidentNodes(") >= 2

    def test_a_moved_pin_records_where_it_really_is(self):
        """Offsetting a marker is a display convenience; losing the true
        coordinate would make it a silent fabrication."""
        js = _src(JS)
        i = js.index("function spreadCoincident(")
        assert "spread_from" in js[i : i + 1800]


class TestStarbaseIsItsOwnSection:
    """Owner: the hub belongs above the nodes, not listed as node #1. It is the
    tier above them (Starbase > Citadel / Outpost / Starship) and the one machine
    that is not a remote node."""

    def test_starbase_heading_precedes_nodes(self):
        js = _src(JS)
        i = js.index("function renderFleetIndex")
        blk = js[i : i + 4000]
        assert blk.index("'STARBASE'") < blk.index("'NODES'")

    def test_the_hub_row_reports_its_REAL_status(self):
        """It was hardcoded `online: true`, so the hub rendered green even when
        its own remote_nodes row said otherwise. A status that cannot fail is
        not a status."""
        js = _src(JS)
        i = js.index("'STARBASE'")
        blk = js[i : i + 500]
        assert "data.hub.status" in blk
        assert "online: true" not in blk

    def test_the_nodes_heading_is_skipped_when_empty(self):
        """A lone NODES header over nothing reads as data loss."""
        js = _src(JS)
        i = js.index("if (entries.length)")
        assert "'NODES'" in js[i : i + 300]


class TestTheMeshIsTheConnectivityReference:
    """Owner: "we dont see shuttle". It could never appear — the map reads
    remote_nodes, and shuttle-kytran has no row there. Measured 2026-09-11:
    headscale had 7 members ONLINE while the tab drew 5. The invisible two were
    shuttle-kytran (100.64.0.9, a personal device) and archie-starbase-subnet
    (100.64.0.1, the archie_tailscale LAN subnet router).

    Connected and runs-work are different questions; the panel only asked one.
    """

    def test_the_payload_carries_mesh_only_members(self):
        import inspect
        from services import fleet_service

        assert '"mesh": mesh_only_members(nodes)' in inspect.getsource(fleet_service.get_fleet_map_data)

    def test_matching_uses_ip_AND_name(self, monkeypatch):
        """Both are load-bearing. The hub's row stores mesh_ip
        'host.docker.internal' — not a mesh IP at all — so IP matching alone
        lists the HUB as a stranger on its own mesh."""
        from services import fleet_service

        monkeypatch.setattr(
            fleet_service,
            "mesh_members",
            lambda: [
                {"name": "starship-246", "mesh_ip": "100.64.0.3", "online": True},
                {"name": "archie-starbase", "mesh_ip": "100.64.0.4", "online": True},
                {"name": "shuttle-kytran", "mesh_ip": "100.64.0.9", "online": True},
                {"name": "archie-starbase-subnet", "mesh_ip": "100.64.0.1", "online": True},
            ],
        )
        nodes = [
            {"name": "Starship - Defiant - USS-246", "mesh_ip": "100.64.0.3"},
            {"name": "Archie Starbase", "mesh_ip": "host.docker.internal"},
        ]
        got = sorted(m["name"] for m in fleet_service.mesh_only_members(nodes))
        assert got == ["archie-starbase-subnet", "shuttle-kytran"], got

    def test_the_subnet_router_is_not_mistaken_for_the_hub(self):
        """'archie-starbase-subnet' shares a prefix with 'archie-starbase'. A
        prefix or substring rule folds the subnet router into the hub and it
        disappears; requiring EVERY token ('subnet' included) keeps them apart."""
        from services.fleet_service import _mesh_tokens, _norm_name

        hub = _norm_name("Archie Starbase")
        assert all(t in hub for t in _mesh_tokens("archie-starbase"))
        assert not all(t in hub for t in _mesh_tokens("archie-starbase-subnet"))

    def test_it_fails_safe_when_headscale_is_unreachable(self, monkeypatch):
        """A side panel must not be able to 500 the fleet map."""
        import subprocess

        from services import fleet_service

        fleet_service._mesh_cache.update(at=0.0, rows=[])

        def boom(*a, **k):
            raise subprocess.TimeoutExpired("headscale", 10)

        monkeypatch.setattr(fleet_service.subprocess, "run", boom)
        assert fleet_service.mesh_members() == []
        assert fleet_service.mesh_only_members([{"name": "x", "mesh_ip": "1.2.3.4"}]) == []

    def test_a_failure_keeps_the_last_good_list(self, monkeypatch):
        """Better a 60s-stale mesh list than a section that blinks out whenever
        headscale is briefly busy."""
        import subprocess

        from services import fleet_service

        good = [{"name": "shuttle-kytran", "mesh_ip": "100.64.0.9", "online": True}]
        fleet_service._mesh_cache.update(at=0.0, rows=good)
        monkeypatch.setattr(
            fleet_service.subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("headscale", 10)),
        )
        assert fleet_service.mesh_members() == good

    def test_mesh_rows_are_rendered_without_a_pin(self):
        """They have no coordinates. buildIndexItem(null, null) is deliberate —
        inventing a location for a laptop would be the map's fourth fabrication
        this session."""
        js = _src(JS)
        i = js.index("fleetMeshSection")
        blk = js[i : i + 1200]
        assert "null, null" in blk
        assert "m.mesh_ip" in blk
