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
SVC_PATH = REPO_ROOT / "platform_v2" / "services" / "contractor_health_service.py"
CSS_PATH = REPO_ROOT / "platform_v2" / "static" / "css" / "fleet.css"
JOBS_PATH = REPO_ROOT / "platform_v2" / "tools" / "department_hq" / "jobs.py"


def _read(path: pathlib.Path, container_rel: str) -> str:
    """Read a repo file, falling back to the in-container location.

    The repo root is not mounted into the container; platform_v2 lives at /app there.
    """
    if path.exists():
        return path.read_text(encoding="utf-8")
    alt = pathlib.Path("/app") / container_rel
    return alt.read_text(encoding="utf-8") if alt.exists() else ""


def _js() -> str:
    if JS_PATH.exists():
        return JS_PATH.read_text(encoding="utf-8")
    # In-container the repo root is not mounted; platform_v2 is at /app.
    alt = pathlib.Path("/app/tools/department_hq/static/js/department-hq.js")
    if alt.exists():
        return alt.read_text(encoding="utf-8")
    return ""


def _called_names(src: str) -> set:
    """Function names actually CALLED in `src`, via the AST.

    Text scanning cannot answer "is record_observation used here" because the module's own
    docstrings name it while explaining why it is NOT used — which produced both a false
    failure and, one revision earlier, a false pass. The AST sees calls, not prose.
    """
    import ast as _ast

    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return set()
    names = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            f = node.func
            if isinstance(f, _ast.Name):
                names.add(f.id)
            elif isinstance(f, _ast.Attribute):
                names.add(f.attr)
    return names


def _switch_names_recorded(src: str) -> set:
    """The switch_name literal passed to each `_record_switch(...)` call.

    Matching this by regex fails in a way that looks like a pass: the call's own arguments
    include `row["dispatchable"]` and `row["is_active"]`, so a pattern for the switch name
    matches the DICT KEY instead, and renaming the switch to "dispatchable_x" goes unnoticed.
    Only the AST can tell which string is the switch and which is a column name.
    """
    import ast as _ast

    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return set()
    found = set()
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, _ast.Name) else getattr(fn, "attr", None)
        if name != "_record_switch":
            continue
        args = node.args
        # signature: (cur, provider_key, switch_name, from_value, to_value)
        if len(args) >= 3 and isinstance(args[2], _ast.Constant):
            found.add(args[2].value)
    return found


def _migration(name: str) -> str:
    """Locate a migration file from either the repo checkout or inside the container.

    The bind-mounted repo is listed explicitly because in-container `parents[2]` of the test
    file resolves to "/", so the repo-relative path silently misses — and a test that quietly
    skips protects nothing. Verified by running the suite in-container, where this path is
    the only one that resolves.
    """
    for rel in (
        f"database/migrations/{name}",
        f"/mnt/archie_brain/database/migrations/{name}",
    ):
        p = pathlib.Path(rel) if rel.startswith("/") else REPO_ROOT / rel
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def _css() -> str:
    for rel in (
        "platform_v2/static/css/fleet.css",
        "/app/static/css/fleet.css",
        "/mnt/archie_brain/platform_v2/static/css/fleet.css",
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


class TestOperatorSwitchAudit(unittest.TestCase):
    """An operator decision is not a probe observation, and must be recorded as one.

    #3653 removed a fabricated `contractor_health` write (probe_kind='health', status='ok')
    that the routing toggle used to "record" its decision — it made a broken provider look
    healthy to the badge and the ranking. That left the decision itself unrecorded. This is the
    honest home it needed: a separate table, written by the toggle, readable from the tab.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = _routes()
        if not cls.src:
            raise unittest.SkipTest("fleet_provider_routes.py not reachable from this layout")

    def test_the_migration_exists_and_separates_decisions_from_observations(self):
        sql = _migration("488_contractor_switch_audit.sql")
        if not sql:
            self.skipTest("migration 488 not reachable from this layout")
        self.assertIn("CREATE TABLE IF NOT EXISTS contractor_switch_audit", sql)
        self.assertIn("switch_name", sql)
        # a closed vocabulary, for the same reason contractor_health constrains its own:
        # an unconstrained column eventually carries a typo and becomes a third thing
        self.assertRegex(sql, r"CHECK\s*\(switch_name IN \('is_active', 'dispatchable'\)\)")
        self.assertIn("actor", sql)

    def test_both_switches_are_recorded(self):
        recorded = _switch_names_recorded(self.src)
        for switch in ("is_active", "dispatchable"):
            self.assertIn(
                switch,
                recorded,
                f"the {switch} switch must pass its own name to _record_switch; "
                f"recorded so far: {sorted(recorded)}",
            )

    def test_the_record_carries_the_before_and_after_values(self):
        """A log of "something changed" cannot answer "what did it change from"."""
        block = re.search(r"def api_toggle_provider_dispatchable.*?(?=\n    @bp\.route)", self.src, re.S)
        self.assertIsNotNone(block)
        self.assertIn('row["dispatchable"]', block.group(0), "the pre-toggle value is required")
        self.assertIn('updated["dispatchable"]', block.group(0), "and the post-toggle value")

    def test_it_still_never_writes_to_contractor_health(self):
        """The fix from #3653 must not creep back while the audit table is added."""
        self.assertNotIn(
            "record_observation",
            _called_names(self.src),
            "an operator decision must never be recorded as a probe observation",
        )

    def test_a_failed_audit_write_cannot_roll_back_the_decision(self):
        """Losing the flip because the record failed is worse than losing the record."""
        helper = re.search(r"def _record_switch\(.*?\n(?=    @bp\.route)", self.src, re.S)
        self.assertIsNotNone(helper, "the recorder must exist")
        self.assertIn("except Exception", helper.group(0))
        self.assertIn("logger.warning", helper.group(0))

    def test_the_history_is_readable_somewhere(self):
        """A write-only audit table answers nothing."""
        self.assertIn("/api/providers/<provider_key>/switch-history", self.src)
        self.assertIn("SELECT switch_name, from_value, to_value, actor", self.src)
        self.assertIn("ORDER BY created_at DESC", self.src)


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
            _called_names(self.src),
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


class TestSwitchHistoryUI(unittest.TestCase):
    """The switch audit trail, finally visible.

    #3659 made both switches write `contractor_switch_audit`. #3662 made it readable. Nothing
    rendered it, so "who turned routing on for this paid provider, and when" was answerable only
    by curling an endpoint an operator has to know exists.
    """

    def setUp(self):
        self.src = _js()
        self.routes = _routes()

    def _js_block(self, start_marker: str, end_marker: str) -> str:
        i = self.src.index(start_marker)
        return self.src[i : self.src.index(end_marker, i)]

    # ---- the payload contract -------------------------------------------------

    def test_a_degraded_read_is_distinguishable_from_a_genuine_empty_one(self):
        """THE point of this PR.

        The endpoint's failure path returns `success: True` with an empty list. Without a
        separate flag, "the audit table could not be read" and "this provider has never been
        switched" are byte-identical payloads — and the UI would confidently print "no changes
        recorded yet" about the exact thing the operator opened the panel to find out.
        """
        self.assertIn('"degraded": True', self.routes)

    def test_the_success_path_never_says_degraded(self):
        """A real read must not be able to look degraded, or the panel cries wolf."""
        i = self.routes.index("def api_provider_switch_history")
        body = self.routes[i : self.routes.index("@bp.route", i + 10)]
        self.assertNotIn("degraded", body.split('"events": [')[0], "success payload must not set degraded")

    # ---- the panel must not lie ----------------------------------------------

    def test_the_panel_distinguishes_degraded_from_empty(self):
        block = self._js_block("async function toggleSwitchHistory", "// The second switch.")
        self.assertIn("if (data.degraded)", block)
        self.assertIn("temporarily unavailable", block)
        # and the honest-empty string must be a SEPARATE branch
        self.assertIn("No switch changes recorded yet.", block)

    def test_a_degraded_read_never_renders_the_empty_message(self):
        """The two branches must not be reachable from each other."""
        block = self._js_block("async function toggleSwitchHistory", "// The second switch.")
        deg = block.index("if (data.degraded)")
        emp = block.index("No switch changes recorded yet.")
        self.assertGreater(deg, 0, "degraded branch missing")
        self.assertGreater(emp, deg, "the empty-state message must come AFTER the degraded early-return")
        self.assertLess(block.index("return", deg), emp)

    def test_a_failed_fetch_is_reported_not_swallowed(self):
        """Must check the CATCH block's own text.

        A mutation that emptied the catch body left the panel stuck on "Loading…", but this test
        still passed: the string "Could not load switch history" also appears in the !res.ok
        branch above. It was proving the message exists somewhere in the function, not that the
        network-failure path produces it.
        """
        block = self._js_block("async function toggleSwitchHistory", "// The second switch.")
        self.assertIn("} catch (e) {", block)
        catch = block[block.index("} catch (e) {") :][:260]
        self.assertIn(
            "Could not load switch history",
            catch,
            "the catch block must replace the panel, not leave it on the loading text",
        )

    def test_a_non_ok_response_surfaces_the_server_error(self):
        block = self._js_block("async function toggleSwitchHistory", "// The second switch.")
        self.assertIn("if (!res.ok || data.success === false)", block)

    # ---- reading the two switches correctly -----------------------------------

    def test_both_switches_have_distinct_meaningful_labels(self):
        """`is_active` and `dispatchable` both rendering as bare ON/OFF is the ambiguity
        #3653 was written to remove. The history must not reintroduce it."""
        block = self._js_block("var SWITCH_LABELS", "function switchHistoryRow")
        self.assertIn("Configured", block)
        self.assertIn("Routing", block)

    def test_an_unrecognised_switch_name_still_renders(self):
        """A new switch column must not make the whole panel blank."""
        self.assertIn("|| { label: ev.switch, on: 'on', off: 'off' }", self.src)

    def test_a_null_actor_does_not_render_the_word_null(self):
        self.assertIn("ev.actor || 'unknown'", self.src)

    def test_the_destination_colour_carries_the_meaning(self):
        """A switch turning ON is the event being hunted for."""
        block = self._js_block("function switchHistoryRow", "async function toggleSwitchHistory")
        self.assertIn("toOn ? '#22c55e'", block)

    def test_timestamps_go_through_the_tabs_existing_helper(self):
        """Never raw UTC. `fmtTime` already parses offset-bearing ISO and renders browser-local
        (EDT for the owner), so reusing it is both correct and consistent."""
        block = self._js_block("function switchHistoryRow", "async function toggleSwitchHistory")
        self.assertIn("fmtTime(ev.at)", block)
        self.assertNotIn("ev.at", block.split("fmtTime")[0])

    # ---- escaping --------------------------------------------------------------

    def test_actor_is_escaped(self):
        """`actor` is operator-supplied text from the auth layer."""
        block = self._js_block("function switchHistoryRow", "async function toggleSwitchHistory")
        self.assertIn("escapeHtml(ev.actor", block)

    def test_the_switch_name_is_escaped(self):
        block = self._js_block("function switchHistoryRow", "async function toggleSwitchHistory")
        self.assertIn("escapeHtml(meta.label)", block)

    def test_the_request_path_is_uri_encoded(self):
        block = self._js_block("async function toggleSwitchHistory", "// The second switch.")
        self.assertIn("encodeURIComponent(key)", block)

    # ---- the control itself ----------------------------------------------------

    def test_the_button_stops_the_row_from_opening_the_edit_modal(self):
        """Check THIS button's own markup, not a character window.

        The original version searched 120 chars before / 320 after the marker, which happily
        picked up the Edit button's `event.stopPropagation()` a few characters away. Deleting the
        history button's own call left the assertion green.
        """
        # The button is built by ONE `html += '<button ...'` statement that spans several lines, so
        # take that whole statement (marker to its closing </button>), not a single line.
        i = self.src.index('<button class="contractor-btn-history"')
        statement = self.src[i : self.src.index("</button>", i)]
        self.assertIn("onclick=", statement)
        self.assertIn("event.stopPropagation()", statement)

    def test_the_button_is_an_action_not_a_bare_badge(self):
        """It lives with Edit, because opening a log is an action. #3669 puts a refresh button
        beside the health badge; this is deliberately not there — two adjacent icon buttons with
        different meanings is its own ambiguity."""
        i = self.src.index("contractor-firm-actions")
        block = self.src[i : i + 700]
        self.assertIn("contractor-btn-history", block)

    def test_clicking_twice_closes_the_panel(self):
        block = self._js_block("async function toggleSwitchHistory", "// The second switch.")
        self.assertIn("panel.remove()", block)

    def test_the_panel_id_is_namespaced_by_provider(self):
        """Two providers on screen must not share a panel.

        Asserts the getElementById CALL specifically, not the substring: the assignment
        `panel.id = 'history-' + key` also contains it, so a mutation that hardcoded the lookup
        to a shared id still satisfied a plain `assertIn`.
        """
        block = self._js_block("async function toggleSwitchHistory", "// The second switch.")
        self.assertIn("document.getElementById('history-' + key)", block)
        self.assertIn("panel.id = 'history-' + key;", block)

    def test_the_history_read_is_authenticated(self):
        i = self.routes.index('@bp.route("/api/providers/<provider_key>/switch-history")')
        self.assertIn("@auth_decorator", self.routes[i : i + 200])

    def test_the_css_does_not_reuse_the_purple_of_edit(self):
        css = _css()
        i = css.index(".contractor-btn-history {")
        block = css[i : css.index("}", i)]
        self.assertNotIn("#a855f7", block)


class TestProbeNowControl(unittest.TestCase):
    """The operator's escape hatch from the backoff window.

    Backoff (#3668) stops the scheduler re-probing failures that re-probing cannot fix. But a
    `no_key` provider can only be fixed BY a person, and the 120-minute window would otherwise
    be the operator's only refresh — so they paste a key, reload, see the old `no_key`, and
    conclude the fix failed.
    """

    def setUp(self):
        self.src = _read(JS_PATH, "tools/department_hq/static/js/department-hq.js")
        self.routes = _read(ROUTES_PATH, "tools/department_hq/fleet_provider_routes.py")
        self.svc = _read(SVC_PATH, "services/contractor_health_service.py")

    def _route_body(self) -> str:
        """The probe route's source, from `def` to the next route decorator.

        A fixed character window silently rots the moment the handler grows — which it did, and
        the assertion failed for the wrong reason. Slice to the next decorator instead.
        """
        i = self.routes.index("def api_probe_provider_now")
        rest = self.routes[i:]
        j = rest.find("@bp.route(", 1)
        return rest if j == -1 else rest[:j]

    def test_the_endpoint_exists_and_is_post_only(self):
        self.assertIn('@bp.route("/api/providers/<provider_key>/probe", methods=["POST"])', self.routes)

    def test_the_endpoint_is_authenticated(self):
        """An unauthenticated probe endpoint hands anyone with a session the ability to make
        the platform spend money against paid keys. Every sibling route uses @auth_decorator."""
        i = self.routes.index('@bp.route("/api/providers/<provider_key>/probe", methods=["POST"])')
        self.assertIn("@auth_decorator", self.routes[i : i + 300])

    def test_unknown_provider_is_a_404_not_a_silent_success(self):
        """Probing a key that does not exist must not report 'success' with no provider."""
        i = self.routes.index("def api_probe_provider_now")
        block = self.routes[i : i + 2600]
        self.assertIn("Provider not found", block)
        self.assertIn("404", block)

    def test_kind_is_validated_rather_than_trusted(self):
        i = self.routes.index("def api_probe_provider_now")
        self.assertIn('kind not in ("health", "latency", "full")', self.routes[i : i + 2600])

    def test_force_bypasses_the_backoff_window(self):
        """The whole point. If force did nothing, the button would just re-run the scheduler."""
        self.assertIn("def scan(", self.svc)
        i = self.svc.index("def scan(")
        block = self.svc[i : i + 3000]
        self.assertIn("force: bool = False", block)
        self.assertIn("if not probe_now and not force:", block)

    def test_force_is_not_reachable_from_the_scheduler(self):
        """The scheduler must keep its hands off; only the operator route may pass force.

        Scoped to `scan(` on purpose. `jobs.py` has an unrelated `force=True` at line ~4269 —
        that is A.R.C.H.I.E.'s own dispatch throttle, a different function's parameter. Asserting
        the bare string flagged a false positive, so this checks the CALL, not the word.
        """
        jobs = _read(JOBS_PATH, "tools/department_hq/jobs.py")
        for m in re.finditer(r"scan\((?:[^()\n]|\n)*?\)", jobs):
            self.assertNotIn("force=", m.group(0), f"scheduler bypasses backoff: {m.group(0)[:80]}")

    def test_every_exception_path_in_the_probe_route_returns_an_error_status(self):
        """No `except` in this route may return 2xx.

        An earlier version asserted the literal `"error": str(e)}), 500` appears in the route —
        and a mutation swapping the *scan* handler for a 200 still passed, because the identical
        string also appears on the earlier DB-lookup handler. The test proved the route contained
        that line somewhere, which is not the same claim at all.

        So: split on every `except` and check the status code each one returns.
        """
        body = self._route_body()
        paths = [m.group(1) for m in re.finditer(r"except[^\n]*:\n\s*return jsonify\(.*?\) ?, ?(\d{3})", body, re.S)]
        self.assertGreaterEqual(len(paths), 3, f"expected several guarded paths in the probe route, saw {len(paths)}")
        for status in paths:
            self.assertGreaterEqual(int(status), 400, f"an exception path returns HTTP {status}")

    def test_a_broken_health_service_is_reported_as_unavailable(self):
        """Import failure is a 503, not a 500 — the service is down, not the request."""
        self.assertIn('"error": f"health service unavailable', self._route_body())

    def test_the_button_sits_beside_the_reading_it_refreshes(self):
        """Not buried in the action group: the reason to press it is the stale badge."""
        i = self.src.index("contractorHealthBadge(p);")
        after = self.src[i : i + 700]
        self.assertIn("contractor-btn-probe", after)

    def test_the_button_stops_the_row_from_opening_the_edit_modal(self):
        """Every other control in this row calls event.stopPropagation() for exactly this."""
        i = self.src.index("contractor-btn-probe")
        self.assertIn("event.stopPropagation()", self.src[i - 200 : i + 400])

    def test_the_button_shows_progress_and_always_re_enables(self):
        js = self.src[self.src.index("async function probeProviderNow") :][:2400]
        self.assertIn("btn.disabled = true", js)
        self.assertIn("btn.disabled = false", js)
        self.assertIn("finally", js)

    def test_the_toast_reports_the_actual_status_not_a_generic_success(self):
        js = self.src[self.src.index("async function probeProviderNow") :][:2400]
        self.assertIn("data.result && data.result.status", js)

    def test_the_provider_key_is_uri_encoded_in_the_request(self):
        """Provider keys are operator-supplied free text."""
        js = self.src[self.src.index("async function probeProviderNow") :][:2400]
        self.assertIn("encodeURIComponent(key)", js)

    def test_the_css_does_not_reuse_green(self):
        """Green means "routing on" everywhere else in this row. This button is not routing."""
        css = _read(CSS_PATH, "static/css/fleet.css")
        i = css.index(".contractor-btn-probe {")
        block = css[i : css.index("}", i)]
        self.assertNotIn("#10b981", block)
        self.assertNotIn("#22c55e", block)
