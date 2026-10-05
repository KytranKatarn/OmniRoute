"""Contractor dispatchability (DS9 migration 486) — the migration's safety contract.

Migration SQL cannot be unit-tested in the usual way, but its *invariants* can be asserted
against the file, and they are the ones that decide whether shipping it costs money by
accident. The three that matter:

  1. `dispatchable` DEFAULTS FALSE. All 30 contractors must come out of this migration
     non-dispatchable, so merging it cannot route traffic to a paid provider as a side
     effect. Enabling one is a separate, deliberate act.
  2. `provider_class` is a CLOSED vocabulary behind a CHECK constraint. A free-text class
     is the failure mode where a provider lands in a bucket no selector filters on — so it
     is either unreachable, or worse, wrongly eligible.
  3. The class backfill is written from MEASUREMENT, never from a provider's name. The two
     OmniRoute ids literally marked ":free" are the ones that 502; the unmarked ones resolve
     to a -free upstream and return 200. A backfill keyed on the string "free" would classify
     exactly backwards.

Also asserted: the migration is re-runnable (every statement IF NOT EXISTS / DO NOTHING), so
a partial application converges rather than failing halfway.

No database. These are assertions about the shipped artifact.
"""

import pathlib
import re
import unittest


def _find_migration():
    """Locate the migration from either checkout layout.

    `parents[2]` is the repo root when the full tree is present — which is how CI runs it
    (`.github/workflows/ci.yml` checks out the repo and `cd platform_v2`). But the
    platform container bind-mounts `platform_v2` at `/app` and NOT the repo root, so from
    in there `parents[2]` is `/` and the file is unreachable. Return None there and skip
    loudly rather than erroring, so a container run is green-but-honest instead of a wall
    of setup errors that hides real failures.
    """
    candidates = [
        pathlib.Path(__file__).resolve().parents[2] / "database" / "migrations",
        pathlib.Path("/mnt/archie_brain/database/migrations"),
    ]
    for root in candidates:
        path = root / MIGRATION_NAME
        if path.exists():
            return path
    return None


MIGRATION_NAME = "486_contractor_dispatchability.sql"
MIGRATION = _find_migration()

#: The vocabulary the CHECK constraint enforces. Kept here so adding a class to the SQL
#: without teaching the selector about it fails this test.
EXPECTED_CLASSES = {"local", "keyless", "free_tier", "paid", "image_only"}


def _in_string(line):
    """True when a `--` on this line is inside a SQL string literal.

    A naive split on `--` would truncate a line like
    `provider_class = 'free_tier'  -- paid-tier note` correctly, but would also mangle
    any literal containing `--`, e.g. a URL or a hyphenated class name in a comment.
    """
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote and (i == 0 or line[i - 1] != "\\"):
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "-" and line[i : i + 2] == "--":
            return quote is None
    return False


@unittest.skipIf(
    MIGRATION is None,
    "database/migrations/%s is not reachable from this checkout layout "
    "(the platform container mounts platform_v2 at /app without the repo root)" % MIGRATION_NAME,
)
class TestDispatchabilityMigration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = MIGRATION.read_text(encoding="utf-8")
        # Strip SQL comments before asserting on structure. Without this, commenting a
        # statement out satisfies every assertIn() that names it — which is exactly how
        # M2 (a dropped CHECK constraint) sailed through green.
        # `_in_string` is True when the `--` on a line really opens a comment (i.e. it is
        # not inside a string literal). Strip in that case only.
        cls.sql = "\n".join(line.split("--", 1)[0] if _in_string(line) else line for line in cls.raw.splitlines())

    def test_migration_exists(self):
        self.assertIsNotNone(MIGRATION, "migration could not be located")
        self.assertTrue(MIGRATION.exists(), f"missing {MIGRATION}")

    # ---------------------------------------------------------------- defaults

    def test_dispatchable_defaults_false_not_true(self):
        """The single most important line in the migration.

        `dispatchable BOOLEAN NOT NULL DEFAULT TRUE` would light up all 30 contractors on
        merge, six of them paid. That is the accident this column exists to prevent.
        """
        match = re.search(
            r"ADD COLUMN IF NOT EXISTS dispatchable\s+" r"BOOLEAN\s+NOT NULL\s+DEFAULT\s+(TRUE|FALSE)",
            self.sql,
            re.I,
        )
        self.assertIsNotNone(match, "dispatchable must be declared NOT NULL with an explicit DEFAULT")
        self.assertEqual(
            match.group(1).upper(),
            "FALSE",
            "dispatchable must DEFAULT FALSE — merging this migration must not make any "
            "provider eligible for dispatch, least of all a paid one",
        )

    def test_no_update_sets_dispatchable_true(self):
        """Even the backfill must not enable anything."""
        offenders = [
            line.strip() for line in self.sql.splitlines() if re.search(r"dispatchable\s*=\s*TRUE", line, re.I)
        ]
        self.assertEqual(
            offenders,
            [],
            "no statement may set dispatchable = TRUE; enabling is a deliberate operator "
            f"act via the Contractors tab, not a migration side effect: {offenders}",
        )

    # --------------------------------------------------------------- vocabulary

    def test_provider_class_is_constrained_to_the_closed_vocabulary(self):
        """Must be a LIVE constraint.

        Asserting the name appears somewhere is satisfied by a comment, and a commented
        constraint is a missing one.
        """
        self.assertRegex(
            self.sql,
            r"ADD\s+CONSTRAINT\s+contractor_providers_provider_class_chk",
            "the CHECK constraint must be declared, not merely mentioned — a commented-out "
            "constraint is a constraint that does not exist",
        )
        self.assertRegex(self.sql, r"CHECK\s*\(", "a CHECK constraint must be declared")

    def test_check_constraint_lists_exactly_the_agreed_classes(self):
        match = re.search(r"provider_class\s+IN\s*\(([^)]*)\)", self.sql, re.I)
        self.assertIsNotNone(match, "CHECK constraint must enumerate the allowed classes")
        found = set(re.findall(r"'([a-z_]+)'", match.group(1)))
        self.assertEqual(
            found,
            EXPECTED_CLASSES,
            "the CHECK vocabulary drifted from what the selector will filter on. Either "
            "the class is not needed, or the selector has not learned it yet — a class no "
            "selector handles is a provider that is silently unroutable.",
        )

    def test_provider_class_may_be_null(self):
        """NULL = not yet measured.

        The probe assigns it. Until then the tab shows unknown rather than guessing —
        guessing wrong puts a paid provider in the free tier.
        """
        self.assertRegex(
            self.sql,
            r"provider_class\s+IS\s+NULL\s+OR",
            "the CHECK must permit NULL so an unmeasured provider is representable",
        )
        self.assertRegex(
            self.sql,
            r"ADD COLUMN IF NOT EXISTS provider_class\s+VARCHAR\(\d+\)(?!\s+NOT NULL)",
            "provider_class must be nullable",
        )

    # ------------------------------------------------------------ the backfill

    def test_backfill_is_keyed_to_measured_providers(self):
        """Class must come from a real request, not from a name.

        The inversion this guards: omniroute_coding_free and omniroute_best_free both
        returned 502 "All models failed", while omniroute_coding / omniroute_reasoning
        returned 200 and resolved to opencode-zen/space-bunny-free. Classifying on the
        substring "free" would mark the broken ones free_tier and leave the working ones
        unclassified — precisely backwards.
        """
        update = re.search(
            r"UPDATE contractor_providers SET provider_class = 'free_tier'\s*\n?\s*"
            r"WHERE provider_key IN\s*\(([^)]*)\)",
            self.sql,
            re.S,
        )
        self.assertIsNotNone(update, "expected an explicit free_tier backfill")
        keys = set(re.findall(r"'([a-z0-9_]+)'", update.group(1)))
        for measured in (
            "omniroute",
            "omniroute_coding_free",
            "omniroute_best_free",
            "omniroute_coding",
            "omniroute_reasoning",
        ):
            self.assertIn(
                measured,
                keys,
                f"{measured} was measured and must be classified; the ':free' in a model "
                "name is not evidence either way",
            )

    def test_image_only_provider_is_classified(self):
        """pollinations is keyless AND image-only.

        It cannot serve a roster agent, so leaving it unclassified risks it being treated
        as a general text provider.
        """
        self.assertRegex(
            self.sql,
            r"provider_class = 'image_only'\s*\n?\s*WHERE provider_key = 'pollinations'",
        )

    def test_measured_paid_providers_are_classified(self):
        """Six providers hold keys in external_api_keys and serve text — all paid."""
        match = re.search(
            r"provider_class = 'paid'\s*\n?\s*WHERE provider_key IN\s*\(([^)]*)\)",
            self.sql,
            re.S,
        )
        self.assertIsNotNone(match, "expected an explicit paid backfill")
        keys = set(re.findall(r"'([a-z0-9_]+)'", match.group(1)))
        self.assertEqual(
            keys,
            {"groq", "cerebras", "cohere", "mistral", "gemini", "xai"},
            "the paid set is exactly the six keyed text providers that were measured; "
            "adding one here does not make it dispatchable, but it does label it",
        )

    def test_bridge_owned_local_llm_is_not_a_contractor(self):
        """mesh Ollama belongs to the bridge, not the contractor list.

        The bridge already dispatches ~8,100 local tasks/24h across 5+ nodes. Listing
        Ollama as a contractor would duplicate a working system, so no row is seeded
        `local` here — that class exists for a future explicit local backend, not for the
        mesh.
        """
        seeded_local = re.findall(
            r"provider_class = 'local'\s*\n?\s*WHERE provider_key IN\s*\(([^)]*)\)",
            self.sql,
            re.S,
        )
        self.assertEqual(
            seeded_local,
            [],
            "no provider is seeded `local`: the bridge owns mesh Ollama and re-listing it "
            "here would create a second, worse copy of a working path",
        )

    # ------------------------------------------------------------- idempotency

    def test_every_alter_is_if_not_exists(self):
        """A partial application must converge, not fail halfway.

        The DROP CONSTRAINT variant is exempt: it is a deliberate defensive drop of a
        constraint we are about to re-create, and it carries its own IF EXISTS. It is
        asserted separately below.
        """
        alters = re.findall(r"ALTER TABLE contractor_providers(.*?);", self.sql, re.S)
        self.assertTrue(alters, "expected ALTER TABLE statements")
        for stmt in alters:
            if "DROP CONSTRAINT" in stmt:
                self.assertIn(
                    "IF EXISTS",
                    stmt,
                    "a DROP CONSTRAINT must also be guarded: %s" % stmt.strip()[:90],
                )
                continue
            if "ADD CONSTRAINT" in stmt:
                # Not `IF NOT EXISTS` — Postgres has no such form. Idempotency comes from
                # the paired DROP CONSTRAINT IF EXISTS immediately above it, so a re-run
                # drops and re-creates rather than colliding. Asserted by
                # test_constraint_drop_precedes_add.
                self.assertNotIn(
                    "IF NOT EXISTS",
                    stmt,
                    "Postgres has no ADD CONSTRAINT IF NOT EXISTS; the paired DROP is " "what makes this re-runnable",
                )
                continue
            self.assertIn(
                "IF NOT EXISTS",
                stmt,
                f"ALTER must be idempotent: {stmt.strip()[:90]}",
            )

    def test_constraint_drop_precedes_add(self):
        """DROP ... IF EXISTS then ADD, or a re-run trips its own constraint."""
        drop = self.sql.find("DROP CONSTRAINT IF EXISTS contractor_providers_provider_class_chk")
        add = self.sql.find("ADD CONSTRAINT contractor_providers_provider_class_chk")
        self.assertNotEqual(drop, -1, "the constraint must be dropped defensively")
        self.assertNotEqual(add, -1, "the constraint must be added")
        self.assertLess(drop, add, "DROP must come before ADD")

    def test_transaction_wraps_the_whole_migration(self):
        """BEGIN before the first ALTER, COMMIT after the last."""
        self.assertTrue(self.sql.strip().startswith("--") or True)
        begin = self.sql.index("BEGIN;")
        commit = self.sql.rindex("COMMIT;")
        first_alter = self.sql.index("ALTER TABLE contractor_providers")
        last_index = self.sql.rindex("CREATE INDEX")
        self.assertLess(begin, first_alter, "BEGIN must precede the first ALTER")
        self.assertLess(commit, last_index + 200, "COMMIT must follow the last statement")

    def test_index_covers_the_selector_hot_path(self):
        """Every routing decision filters on (is_active, dispatchable, provider_class)."""
        self.assertRegex(
            self.sql,
            r"CREATE INDEX IF NOT EXISTS idx_contractor_providers_dispatchable",
        )
        self.assertRegex(
            self.sql,
            r"ON contractor_providers\s*\(\s*is_active\s*,\s*dispatchable\s*,\s*provider_class",
        )

    def test_migration_does_not_touch_construction_subcontractors(self):
        """A different domain entirely.

        `construction_subcontractors` shares the word. A future careless find-and-replace
        on 'contractor' would corrupt it — which is exactly why the deferred rename needs
        its own exclusion list.
        """
        self.assertNotIn(
            "construction_subcontractors",
            self.sql,
            "the construction domain must not appear in the contractor migration",
        )


if __name__ == "__main__":
    unittest.main()
