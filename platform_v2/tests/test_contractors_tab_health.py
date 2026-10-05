"""Contractors tab: class badges, measured health, and the second routing switch (DS9 PR 4).

PR 1 added the columns, PR 3 measured them. Neither was visible: the tab rendered `tier_position`
— a hand-typed integer — and an Active/Inactive badge that cannot express "configured but idle".

Three contracts are pinned here, and each one exists because its absence would have been a lie:

1. **Two switches, not one.** `is_active` means CONFIGURED. `dispatchable` means "route here".
   Collapsing them makes "configured, holding a key, passing its probe, receiving nothing"
   unrepresentable — which is exactly the state a paid provider should sit in by default.

2. **An unmeasured provider reads UNKNOWN, never a number.** `health_status === null` must not
   render as 0ms. Absent is not zero; a fabricated latency becomes the ranking.

3. **An unclassified provider reads UNMEASURED, not a guessed class.** PR 1 deliberately left
   18 of 30 rows NULL. Defaulting them to `free_tier` would put unknown providers into the
   auto-eligible bucket, which is the one bucket that can spend money.

The badge and switch functions are pure and DOM-free enough to test directly; the route is
tested against a fake cursor. No browser, no network.
"""

import pathlib
import re
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, "/app")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_PATH = REPO_ROOT / "platform_v2" / "tools" / "department_hq" / "static" / "js" / "department-hq.js"
ROUTES_PATH = REPO_ROOT / "platform_v2" / "tools" / "department_hq" / "fleet_provider_routes.py"


def _js() -> str:
    if JS_PATH.exists():
        return JS_PATH.read_text(encoding="utf-8")
    # In-container the repo root is not mounted; platform_v2 is at /app.
    alt = pathlib.Path("/app/tools/department_hq/static/js/department-hq.js")
    if alt.exists():
        return alt.read_text(encoding="utf-8")
    return ""


def _css() -> str:
    for rel in (
        "platform_v2/static/css/fleet.css",
        "/app/static/css/fleet.css",
    ):
        p = pathlib.Path(rel) if rel.startswith("/") else REPO_ROOT / rel
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def _routes() -> str:
    if ROUTES_PATH.exists():
        return ROUTES_PATH.read_text(encoding="utf-8")
    alt = pathlib.Path("/app/tools/department_hq/fleet_provider_routes.py")
    if alt.exists():
        return alt.read_text(encoding="utf-8")
    return ""


class TestBadgeVocabulary(unittest.TestCase):
    """The closed vocabularies. A class no legend explains is a class nobody trusts."""

    @classmethod
    def setUpClass(cls):
        cls.js = _js()
        if not cls.js:
            raise unittest.SkipTest("department-hq.js not reachable from this layout")

    def test_class_badges_cover_every_class_the_constraint_allows(self):
        for cls_name in ("paid", "free_tier", "keyless", "image_only", "local"):
            self.assertIn(
                cls_name + ":",
                self.js,
                f"no badge defined for provider_class '{cls_name}'",
            )

    def test_health_badges_cover_every_status_the_constraint_allows(self):
        for status in (
            "ok",
            "rate_limited",
            "auth_error",
            "no_key",
            "unsupported",
            "unreachable",
            "error",
        ):
            self.assertIn(
                status + ":",
                self.js,
                f"no badge defined for health status '{status}'",
            )

    def test_paid_is_labelled_as_never_auto_dispatched(self):
        """The one class where the consequence is money."""
        m = re.search(r"paid:\s*\{[^}]*title:\s*'([^']+)'", self.js)
        self.assertIsNotNone(m, "the paid badge must carry an explanation")
        self.assertIn("Never auto-dispatched", m.group(1))

    def test_image_only_says_it_cannot_back_a_roster_agent(self):
        m = re.search(r"image_only:\s*\{[^}]*title:\s*'([^']+)'", self.js)
        self.assertIsNotNone(m)
        self.assertIn("image", m.group(1).lower())


class TestUnknownIsNotZero(unittest.TestCase):
    """The honesty rules. These are the tests that stop a plausible-looking lie."""

    @classmethod
    def setUpClass(cls):
        cls.js = _js()
        if not cls.js:
            raise unittest.SkipTest("department-hq.js not reachable from this layout")

    def test_unmeasured_health_renders_unknown_not_a_latency(self):
        body = re.search(r"function contractorHealthBadge\(p\)\s*\{(.*?)\n\}", self.js, re.S)
        self.assertIsNotNone(body, "contractorHealthBadge must exist")
        src = body.group(1)
        self.assertIn("UNKNOWN", src, "an unprobed provider must read UNKNOWN")
        # The null check must come BEFORE the latency is read, or it renders "UNKNOWN · 0ms".
        self.assertLess(
            src.index("=== null") if "=== null" in src else src.index("st === null"),
            src.index("p.health_latency_ms"),
            "the unknown check must precede the latency read",
        )

    def test_unmeasured_health_carries_an_explicit_reason(self):
        body = re.search(r"function contractorHealthBadge\(p\)\s*\{(.*?)\n\}", self.js, re.S).group(1)
        self.assertIn(
            "Unknown is not the same as fast",
            body,
            "the tooltip must say why UNKNOWN is not a fast reading",
        )

    def test_latency_suffix_is_omitted_entirely_when_absent(self):
        body = re.search(r"function contractorHealthBadge\(p\)\s*\{(.*?)\n\}", self.js, re.S).group(1)
        self.assertRegex(
            body,
            r"var suffix = \(ms !== null && ms !== undefined\) \?",
            "a latency suffix must be conditional on a real value, never defaulted to 0",
        )

    def test_unclassified_provider_reads_unmeasured_not_a_guessed_class(self):
        body = re.search(r"function contractorClassBadge\(p\)\s*\{(.*?)\n\}", self.js, re.S).group(1)
        self.assertIn("UNMEASURED", body)
        self.assertIn(
            "if (!meta)",
            body,
            "a NULL provider_class must take an explicit unknown branch, not fall through",
        )

    def test_no_default_class_is_assigned_in_the_badge(self):
        """The badge must not coerce an unknown class into free_tier or paid.

        Defaulting to free_tier puts unknown providers in the auto-eligible bucket; the whole
        point of PR 1's NULL is that unmeasured stays unmeasured.
        """
        body = re.search(r"function contractorClassBadge\(p\)\s*\{(.*?)\n\}", self.js, re.S).group(1)
        self.assertNotIn(
            "provider_class ||",
            body,
            "a falsy-coalesce on provider_class would silently assign a class",
        )


class TestTwoSwitches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = _js()
        if not cls.js:
            raise unittest.SkipTest("department-hq.js not reachable from this layout")

    def test_routing_switch_is_rendered_separately_from_the_active_toggle(self):
        self.assertIn("toggleDispatchable(", self.js)
        self.assertIn("toggleProvider(", self.js, "the existing active toggle must remain")

    def test_the_two_switches_write_different_endpoints(self):
        m = re.search(r"function toggleDispatchable\(key\)\s*\{(.*?)\n\}", self.js, re.S)
        self.assertIsNotNone(m, "toggleDispatchable must exist")
        self.assertIn("/dispatchable", m.group(1))
        # and it must NOT post to the is_active endpoint
        self.assertNotIn("/toggle", m.group(1))

    def test_routing_switch_label_reflects_the_state(self):
        self.assertIn("ROUTING ON", self.js)
        self.assertIn("ROUTING OFF", self.js)
        self.assertIn("p.dispatchable === true", self.js)

    def test_switch_tooltip_explains_the_difference_from_the_other_switch(self):
        self.assertRegex(
            self.js,
            r"Routing is OFF[^']*configured, but nothing is dispatched",
            "the routing switch must say what OFF means, since the other switch reads Active",
        )

    def test_switch_stops_propagation_so_the_row_does_not_expand(self):
        self.assertRegex(
            self.js,
            r"event\.stopPropagation\(\);toggleDispatchable\(",
            "the routing switch must call event.stopPropagation() like the other buttons, "
            "or clicking it expands the row instead of toggling",
        )


class TestRouteContract(unittest.TestCase):
    """The server side: the field is exposed and the switch is guarded.

    Static source assertions, deliberately: these read two files and assert on their shape.
    They must NOT inherit the suite's database fixture — a static check that needs a seeded
    admin user gains nothing and fails whenever the fixture's own schema drifts.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = _routes()
        if not cls.src:
            raise unittest.SkipTest("fleet_provider_routes.py not reachable from this layout")

    def test_external_providers_exposes_the_new_fields(self):
        for field in (
            '"dispatchable"',
            '"provider_class"',
            '"health_status"',
            '"health_latency_ms"',
            '"health_observed_model"',
            '"health_checked_at"',
        ):
            self.assertIn(field, self.src, f"{field} missing from the providers payload")

    def test_health_columns_are_selected(self):
        self.assertIn("dispatchable, provider_class", self.src)

    def test_the_health_read_has_a_logging_guard(self):
        """A silent guard is a bug with extra steps.

        The tab is where an operator looks when something is wrong. If the health read
        fails because its table is missing, that must be LOGGED, not swallowed — otherwise
        every row reads UNKNOWN forever with nothing in the log to explain it.

        (Whether the guard is nested inside the listing's try, which makes the request
        500 anyway, is asserted separately below.)
        """
        self.assertRegex(
            self.src,
            r"except Exception as _exc:[\s\S]{0,400}?health read unavailable",
            "the health read must be guarded and logged",
        )
        self.assertIn(
            "logger.warning",
            self.src,
            "a swallowed health read must at least be logged",
        )

    def test_the_health_guard_is_not_nested_inside_the_listings_try(self):
        """Regression, and the reason this test file exists.

        The health read was first written inside the listing's own try block. Its guard caught
        the missing table, logged `health read unavailable (UndefinedTable ...)`, and the
        enclosing handler still returned 500 — observed on the wire with zero providers
        rendered. A guard that logs and then fails the request is not a guard.

        So the guard must sit in the handler body directly, not inside the main try.
        """
        lines = self.src.split("\n")

        # The handler is nested inside a registration factory, so it is indented. Match on the
        # stripped prefix and derive the expected indent from the def, never a hardcoded
        # column — a fixed column silently passes on a differently-nested route.
        handler = next(i for i, ln in enumerate(lines) if ln.strip().startswith("def fleet_get_external_providers"))
        body_indent = len(lines[handler]) - len(lines[handler].lstrip()) + 4

        # Pair the except clause with ITS OWN log line. Searching for the phrase first would
        # match the explanatory comment above it and find no except before it.
        guard = next(
            (
                i
                for i, ln in enumerate(lines)
                if ln.strip().startswith("except Exception as _exc")
                and any("health read unavailable" in lines[j] for j in range(i + 1, min(i + 8, len(lines))))
            ),
            None,
        )
        self.assertIsNotNone(
            guard,
            "the health read must be guarded by an except clause that logs 'health read "
            "unavailable' — find the clause, then its log, not the reverse",
        )
        indent = len(lines[guard]) - len(lines[guard].lstrip())
        self.assertEqual(
            indent,
            body_indent,
            "the health guard must sit in the handler body directly, not nested inside "
            "the listing's try: nested, it logs and the outer handler still returns 500 "
            f"(expected indent {body_indent}, found {indent})",
        )
        self.assertLess(
            handler,
            guard,
            "the guard must belong to fleet_get_external_providers",
        )

    def test_latency_read_is_separate_from_the_latest_read(self):
        """The most recent row is usually a 1-token health probe.

        Its latency says nothing useful about the provider, so the latency read must be
        restricted to rows that have one — otherwise ranking picks up probe overhead.
        """
        self.assertRegex(
            self.src,
            r"WHERE latency_ms IS NOT NULL",
            "latency must come from a read restricted to sampled rows",
        )
        self.assertIn(
            "_HEALTH_LATENCY_CEILING_MS",
            self.src,
            "an outlier latency must be capped before it reaches the ranking",
        )

    def test_dispatchable_toggle_route_exists_and_is_guarded(self):
        self.assertIn("/api/providers/<provider_key>/dispatchable", self.src)
        self.assertIn(
            "provider_class is unmeasured",
            self.src,
            "enabling an unclassified provider must be refused — the class is what makes "
            "'paid' a policy rather than a label",
        )

    def test_toggle_does_not_forge_a_health_observation(self):
        """The toggle must not write to contractor_health at all.

        It did once: probe_kind='health', status='ok'. contractor_health is a history of PROBE
        OBSERVATIONS, so flipping the routing switch on a provider whose last real probe was
        `unreachable` overwrote that finding with 'ok' — a green badge and a ranking point for
        a provider that had never answered. The schema agrees it cannot be faked: probe_kind is
        CHECK-constrained to ('health','latency','full').

        The decision is not lost: it is the column itself, and the selector gate reads it.
        """
        self.assertNotIn(
            "record_observation",
            self.src,
            "the routing toggle must not write probe history — an operator decision is not "
            "an observation, and status='ok' would report a provider healthy that never "
            "answered",
        )

    def test_toggle_writes_only_the_dispatchable_column(self):
        block = re.search(
            r"def api_toggle_provider_dispatchable.*?(?=\n    # ---|\n    @bp\.route)",
            self.src,
            re.S,
        )
        self.assertIsNotNone(block, "the toggle handler must exist")
        body = block.group(0)
        self.assertIn("dispatchable", body)
        # It reads the current value and writes it back parameterised inside one transaction,
        # rather than flipping in SQL — the read is needed anyway to enforce the class guard.
        self.assertRegex(
            body,
            r"SET dispatchable = %s",
            "the routing toggle must write dispatchable, parameterised",
        )
        # and it must not be able to switch traffic on implicitly
        self.assertNotIn("SET is_active", body)


class TestNoSilentRegressions(unittest.TestCase):
    """Guard the things a rewrite of this file could plausibly break."""

    @classmethod
    def setUpClass(cls):
        cls.js = _js()
        cls.src = _routes()
        if not cls.js:
            raise unittest.SkipTest("department-hq.js not reachable from this layout")

    def test_is_active_never_reads_the_legacy_key_table(self):
        """contractor_providers.is_active is the only authority for "configured".

        This is the bug that made the tab argue with itself. The Disable button POSTs to
        /api/providers/<key>/toggle, which writes `contractor_providers.is_active`. The badge
        used to render `external_api_keys.is_active` whenever a pre-DS9 key row existed — so
        clicking Disable flipped one table while the badge kept showing the other, and the
        button appeared broken. Measured live: 4 of the 8 providers with a legacy key row
        disagreed with themselves, and cerebras read INACTIVE while its own column said
        active.

        external_api_keys is still read for what only it knows — budget, account tier, key
        hint. It must not decide whether the contractor is configured.
        """
        # Asserted as a bare absence, not as a pattern on the assignment. A pattern like
        # `is_active = db_row[...]` misses `is_active = bool(db_row[...]) if db_row else
        # False`, which is the same bug wearing a cast — verified by mutation.
        self.assertNotIn(
            'db_row["is_active"]',
            self.src,
            "is_active must not be sourced from the legacy external_api_keys row — that is "
            "the table the Disable button does NOT write",
        )
        self.assertRegex(
            self.src,
            r"is_active = bool\(cp\.get\(.is_active., False\)\)",
            "is_active must be read from contractor_providers for the non-cloud branch",
        )

    def test_the_toggle_syncs_the_legacy_key_table(self):
        """Re-enabling must actually work, not just look like it did.

        `external_providers._get_api_key` gates key material on
        `external_api_keys.is_active = TRUE`. If the toggle only wrote the authority column,
        re-enabling a provider whose legacy row said inactive would let the selector pick it
        and then find no key to call it with — a silent failure at exactly the moment an
        operator deliberately switched a contractor back on. 6 providers were in that state
        on the live roster.
        """
        block = re.search(
            r"def api_toggle_provider\(provider_key\):(.*?)(?=\n    # ---|\n    @bp\.route)",
            self.src,
            re.S,
        )
        self.assertIsNotNone(block, "the toggle handler must exist")
        body = block.group(1)
        self.assertIn("UPDATE external_api_keys", body)
        self.assertIn("SET is_active = %s", body, "it must take the value just computed")
        self.assertIn(
            'row["is_active"]',
            body,
            "the legacy row must be written from the SAME computed value, not re-derived",
        )

    def test_the_active_switch_is_strict_not_a_default(self):
        """`!== false` treats a missing field as enabled.

        If the server ever omits `is_active`, the honest reading is "we were not told", and
        defaulting that to enabled paints a green switch nobody can justify.
        """
        self.assertIn("p.is_active === true", self.js)
        self.assertNotIn("p.is_active !== false", self.js)

    def test_both_switches_carry_their_state_as_a_class(self):
        """Text alone cannot carry it: two switches, one row, both reading "off".

        The state goes on the element as `.on` / `.off`, matching the convention
        .fleet-prov-toggle.active already uses in fleet.css, and is mirrored to assistive
        tech via aria-pressed.
        """
        self.assertIn("contractor-routing-toggle ", self.js)
        self.assertIn("contractor-active-toggle ", self.js)
        for sw in ("contractor-routing-toggle", "contractor-active-toggle"):
            self.assertRegex(
                self.js,
                sw + r"\s*'\s*\+\s*\([A-Za-z_]\w*\s*\?\s*'on'\s*:\s*'off'\)",
                f"{sw} must resolve its own on/off class from state",
            )
        # BOTH switches, not one: a bare `assertIn` passed while the routing switch had lost
        # its aria-pressed, because the other button still had one. Verified by mutation.
        self.assertGreaterEqual(
            self.js.count("aria-pressed="),
            2,
            "each switch must expose its own state to assistive tech — a screen reader " "cannot see the CSS class",
        )

    def test_the_switches_are_visually_distinct_from_each_other(self):
        """The routing switch is the one that can cost money, so it gets the stronger fill."""
        css = _css()
        if not css:
            self.skipTest("fleet.css not reachable from this layout")
        # Anchored to line start so it matches the BASE dark-theme rule. Unanchored, it
        # happily matched the body.light-mode override instead and passed even with the
        # base fill deleted — verified by mutation.
        self.assertRegex(
            css,
            r"(?m)^\.contractor-routing-toggle\.on\s*\{[^}]*background:",
            "ROUTING ON needs a filled background in the base rule, not only a coloured "
            "border — it is the switch that spends money and must read as live at a glance",
        )
        self.assertIn(".contractor-routing-toggle.off", css)
        self.assertIn(".contractor-active-toggle.on", css)
        self.assertIn(".contractor-active-toggle.off", css)

    def test_the_existing_active_toggle_is_untouched(self):
        """It writes is_active. If that were rewritten to dispatchable the two would merge."""
        block = re.search(
            r"def api_toggle_provider\(provider_key\):(.*?)(?=\n    # ---|\n    @bp\.route)",
            self.src,
            re.S,
        )
        self.assertIsNotNone(block)
        self.assertIn("SET is_active = NOT is_active", block.group(1))
        self.assertNotIn("dispatchable", block.group(1))

    def test_escape_html_is_used_on_every_interpolated_probe_field(self):
        """health_observed_model and detail come from an upstream response body.

        That body is attacker-influenced text rendered into a title attribute.
        """
        m = re.search(r"function contractorHealthBadge\(p\)\s*\{(.*?)\n\}", self.js, re.S)
        src = m.group(1)
        self.assertIn("escapeHtml(title)", src, "the health tooltip must be escaped")
        self.assertIn(
            "escapeHtml(meta.title)",
            self.js,
            "class-badge titles must be escaped too",
        )

    def test_the_probe_still_cannot_write_is_active_or_dispatchable(self):
        """The probe OBSERVES. If it could toggle, one timeout could take the fleet offline."""
        svc_paths = [
            REPO_ROOT / "platform_v2" / "services" / "contractor_health_service.py",
            pathlib.Path("/app/services/contractor_health_service.py"),
        ]
        for p in svc_paths:
            if p.exists():
                body = p.read_text(encoding="utf-8")
                self.assertNotIn(
                    "UPDATE contractor_providers",
                    body,
                    "the probe must never write to contractor_providers",
                )
                break
        else:
            self.skipTest("contractor_health_service.py not reachable from this layout")


if __name__ == "__main__":
    unittest.main()
