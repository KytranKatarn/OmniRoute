"""A generated patch must be executable before it can become a PR (#6770 / #6771).

THE INCIDENT: on 2026-09-15, 33 of 33 sampled auto-fix PRs were broken or no-ops, and
FOUR carried a stored F.O.R.G.E. **APPROVE**. The four review-integrity gates (grounding /
polarity / claim / severity, ADR-001 #947) all ask whether a FINDING is grounded in the
diff. None of them ask whether the PATCH RUNS. That is the gap this closes.

Each check below is named for the real PR it was derived from, so a future reader can go
look at the original failure rather than trust this docstring.

⚠️ THE FALSE-REJECT DIRECTION IS THE DANGEROUS ONE. A gate that refuses everything would
"pass" every negative test here while quietly killing the whole self-heal loop, so the
happy-path cases are not filler — they are the half that keeps the gate honest.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.patch_sanity import module_resolves, validate_patch  # noqa: E402


# Load the real ship gate without importing the Repair Bay blueprint, whose
# initialization opens production database connections.
import pytest  # noqa: E402
import importlib.util  # noqa: E402
from types import ModuleType  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_forge_gate(monkeypatch):
    base = Path(__file__).parents[1] / "tools/repair_bay/services"
    for name in ("tools.repair_bay", "tools.repair_bay.services"):
        package = ModuleType(name)
        package.__path__ = [str(base.parent if name == "tools.repair_bay" else base)]
        monkeypatch.setitem(sys.modules, name, package)
    name = "tools.repair_bay.services.forge_pipeline"
    spec = importlib.util.spec_from_file_location(name, base / "forge_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)


class TestRejectsTheRealFailures(unittest.TestCase):
    def test_syntax_error_is_refused(self):
        """#3362 — malformed try/except indentation."""
        r = validate_patch(
            "def f():\n    try:\n        return 1\n    except Exception:\n        return 0\n",
            "def f():\n    try:\n    return 1\n      except Exception:\n        return 0\n",
        )
        self.assertFalse(r["ok"])
        self.assertTrue(any("syntax" in f for f in r["failures"]))

    def test_invented_module_is_refused(self):
        """#3366 — `core.database` does not exist.

        ⚠️ The regression guard that matters: `core` DOES exist in this container
        (/app/core/__init__.py), so a root-only import probe PASSES this patch. It must be
        resolved to full depth.
        """
        r = validate_patch(
            "def f():\n    return 1\n",
            "from core.database import get_db\n\n\ndef f():\n    return get_db()\n",
        )
        self.assertFalse(r["ok"])
        self.assertTrue(any("unresolvable" in f for f in r["failures"]))

    def test_removed_import_still_used_is_refused(self):
        """#3375 — drops `Dict` from the typing import while `Dict` is used 9x -> NameError."""
        r = validate_patch(
            "from typing import Dict, List\n\n\ndef f(x: Dict) -> List:\n    return list(x)\n",
            "from typing import List\n\n\ndef f(x: Dict) -> List:\n    return list(x)\n",
        )
        self.assertFalse(r["ok"])
        self.assertTrue(any("still used" in f for f in r["failures"]))

    def test_unrelated_deletion_is_refused(self):
        """#3355 / #3357 — claimed an import fix while deleting live code."""
        r = validate_patch(
            "def connect_chaplain():\n    return 1\n\n\ndef other():\n    return 2\n",
            "def other():\n    return 2\n",
        )
        self.assertFalse(r["ok"])
        self.assertTrue(any("deleted" in f for f in r["failures"]))

    def test_new_undefined_name_is_refused(self):
        """#3348 — the patch uses a name it never imported."""
        r = validate_patch(
            "def f():\n    return 1\n",
            "def f():\n    return os.getcwd()\n",
        )
        self.assertFalse(r["ok"])

    def test_partially_repointed_import_is_refused(self):
        """#3364 — re-points an import but leaves other call sites on the old module.

        The bare-name case is `removed_import_still_used`; this is the DOTTED case, where
        the old path survives inside an attribute chain the Name walk never sees.
        """
        r = validate_patch(
            "import sqlalchemy\n\n\ndef f():\n    return sqlalchemy.create_engine('x')\n",
            "import json\n\n\ndef f():\n    return sqlalchemy.create_engine('x')\n",
        )
        self.assertFalse(r["ok"])

    def test_formatting_only_change_is_refused(self):
        """#3371 — a patch that parses to identical code still costs a branch and a review."""
        r = validate_patch(
            "def f():\n    return 1\n",
            "def f():\n    # a new comment that changes nothing\n    return 1\n",
        )
        self.assertFalse(r["ok"])
        self.assertTrue(any("no-op" in f for f in r["failures"]))

    def test_no_op_is_refused(self):
        """A patch that changes nothing is not a fix; shipping it burns a review cycle."""
        src = "import os\n\n\ndef f():\n    return os.getcwd()\n"
        self.assertFalse(validate_patch(src, src)["ok"])


class TestAllowsGoodPatches(unittest.TestCase):
    """The half that stops this from becoming a gate that refuses everything."""

    def test_removing_a_genuinely_unused_import_passes(self):
        r = validate_patch(
            "import os\nimport json\n\n\ndef f():\n    return os.getcwd()\n",
            "import os\n\n\ndef f():\n    return os.getcwd()\n",
        )
        self.assertTrue(r["ok"], r["failures"])

    def test_adding_a_resolvable_import_passes(self):
        r = validate_patch(
            "def f():\n    return 1\n",
            "import json\n\n\ndef f():\n    return json.dumps(1)\n",
        )
        self.assertTrue(r["ok"], r["failures"])

    def test_adding_a_function_passes(self):
        r = validate_patch(
            "def a():\n    return 1\n",
            "def a():\n    return 1\n\n\ndef b():\n    return 2\n",
        )
        self.assertTrue(r["ok"], r["failures"])

    def test_preexisting_findings_are_not_this_patchs_fault(self):
        """Only NEW static findings fail. A file that already had an unused import must
        still accept an unrelated correct fix, or the gate blocks work it did not break."""
        before = "import json\n\n\ndef f():\n    return 1\n"  # json already unused
        after = "import json\n\n\ndef f():\n    return 2\n"
        self.assertTrue(validate_patch(before, after)["ok"])


class TestModuleResolution(unittest.TestCase):
    def test_real_modules_resolve(self):
        for m in ("os", "json", "sys"):
            self.assertTrue(module_resolves(m), m)

    def test_aliased_submodule_resolves(self):
        """`os.path` is an ALIAS assigned at import — there is no os/path.py on disk, so a
        filesystem-only walk reports False. That is a FALSE REJECT, the costly direction."""
        self.assertTrue(module_resolves("os.path"))

    def test_invented_modules_do_not_resolve(self):
        for m in ("agent_clarification", "core.database", "app_core.tools.database"):
            self.assertFalse(module_resolves(m), m)

    def test_empty_is_not_resolvable(self):
        self.assertFalse(module_resolves(""))
        self.assertFalse(module_resolves(None))


class TestDegradesVisibly(unittest.TestCase):
    """A skipped check must SAY it was skipped (F.O.R.G.E. review of #3390).

    check_no_new_pyflakes_findings returns ok=True when pyflakes cannot run — it has to,
    because failing closed on a missing linter would block every patch the moment the
    dependency went away. But a gate that quietly drops a check is how "it passed" stops
    meaning anything, so the skip is reported in the check's detail.
    """

    def test_skip_is_announced_not_silent(self):
        from services.patch_sanity import check_no_new_pyflakes_findings

        ok, detail = check_no_new_pyflakes_findings("def (:\n", "def f():\n    return 1\n")
        self.assertTrue(ok)
        self.assertIn("SKIPPED", detail)

    def test_a_skip_does_not_fail_a_good_patch(self):
        """The detail is informational — it must not leak into `failures`."""
        r = validate_patch(
            "import os\nimport json\n\n\ndef f():\n    return os.getcwd()\n",
            "import os\n\n\ndef f():\n    return os.getcwd()\n",
        )
        self.assertTrue(r["ok"], r["failures"])
        self.assertEqual(r["failures"], [])


class TestFailsClosed(unittest.TestCase):
    def test_unparseable_original_does_not_crash(self):
        """The gate must return a verdict, never raise into the caller."""
        r = validate_patch("def (:\n", "def f():\n    return 1\n")
        self.assertIn("ok", r)
        self.assertIsInstance(r["failures"], list)


if __name__ == "__main__":
    unittest.main()


class TestGateNeverRaisesIntoTheShipPath(unittest.TestCase):
    """_patch_sanity_ok must be TOTAL (F.O.R.G.E. review of #3390, [CRITICAL]).

    It sits on the ship path. An escaping exception surfaces upstream as some unrelated
    failure — that has bitten this file before, where _patched_content's ImportError was
    reported as "proposal has no code_diff". A gate that crashes is worse than one that
    refuses, because the refusal at least names itself.
    """

    def test_hostile_file_paths_do_not_raise(self):
        from tools.repair_bay.services.forge_pipeline import _patch_sanity_ok

        for bad in (None, 123, "", [], {}):
            ok, reasons = _patch_sanity_ok(bad, "x = 1\n")
            self.assertIsInstance(ok, bool, bad)
            self.assertIsInstance(reasons, list, bad)

    def test_a_real_bad_patch_is_still_refused(self):
        """NON-VACUITY: totality must not have turned the gate into a rubber stamp."""
        from tools.repair_bay.services.forge_pipeline import _patch_sanity_ok

        ok, _ = _patch_sanity_ok("platform_v2/services/patch_sanity.py", "def broken(:\n")
        self.assertFalse(ok)


class TestDisabledGateIsLoud(unittest.TestCase):
    """`off` must never be silent (#3405 [CRITICAL]).

    The finding was right that `off` disables the gate. `off` is a legitimate operator
    lever; the risk is that it gets set during an incident and SILENTLY stays set. `warn`
    already logged — `off` was the only quiet state.
    """

    @staticmethod
    def _fp():
        import importlib

        return importlib.import_module("tools.repair_bay.services.forge_pipeline")

    def test_off_announces_itself_and_still_passes(self):
        fp = self._fp()
        seen = []
        orig_mode, orig_warn = fp._patch_sanity_mode, fp._warn_sanity_disabled
        fp._patch_sanity_mode = lambda: "off"
        fp._warn_sanity_disabled = lambda p: seen.append(p)
        try:
            ok, reasons = fp._patch_sanity_ok("platform_v2/whatever.py", "x = 1\n")
        finally:
            fp._patch_sanity_mode, fp._warn_sanity_disabled = orig_mode, orig_warn

        self.assertTrue(ok, "off must still pass the patch through — it is a killswitch")
        self.assertEqual(reasons, [])
        self.assertEqual(seen, ["platform_v2/whatever.py"], "a disabled gate shipped a patch SILENTLY")

    def test_a_non_python_file_does_NOT_raise_the_alarm(self):
        """Ordering matters: folding the two skips would alarm on every .md in a diff."""
        fp = self._fp()
        seen = []
        orig_mode, orig_warn = fp._patch_sanity_mode, fp._warn_sanity_disabled
        fp._patch_sanity_mode = lambda: "enforce"
        fp._warn_sanity_disabled = lambda p: seen.append(p)
        try:
            ok, _ = fp._patch_sanity_ok("docs/README.md", "hello")
        finally:
            fp._patch_sanity_mode, fp._warn_sanity_disabled = orig_mode, orig_warn

        self.assertTrue(ok)
        self.assertEqual(seen, [], "a non-Python skip was reported as a disabled gate")

    def test_the_notifier_never_raises(self):
        """It sits on the ship path — a notification failure must not block a merge."""
        fp = self._fp()
        try:
            fp._warn_sanity_disabled("platform_v2/anything.py")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"_warn_sanity_disabled raised {type(exc).__name__}: {exc}")


class TestBlueprintRegistrationImports(unittest.TestCase):
    source = 'from flask import Blueprint\nimport json\nbp = Blueprint("example", __name__)\nfrom . import routes\n'
    path = "platform_v2/tools/example/__init__.py"

    def test_commenting_registration_import_is_refused(self):
        result = validate_patch(
            self.source, self.source.replace("from . import routes", "# from . import routes"), self.path
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["registration_imports"]["ok"])

    def test_deleting_registration_import_is_refused(self):
        result = validate_patch(self.source, self.source.replace("from . import routes\n", ""), self.path)
        self.assertFalse(result["checks"]["registration_imports"]["ok"])

    def test_blueprint_constructor_alias_is_protected(self):
        source = self.source.replace("import Blueprint", "import Blueprint as BP").replace("= Blueprint(", "= BP(")
        result = validate_patch(source, source.replace("from . import routes", "# from . import routes"), self.path)
        self.assertFalse(result["checks"]["registration_imports"]["ok"])

    def test_module_blueprint_constructor_is_protected(self):
        source = self.source.replace("from flask import Blueprint", "import flask as web").replace(
            "= Blueprint(", "= web.Blueprint("
        )
        result = validate_patch(source, source.replace("from . import routes", "# from . import routes"), self.path)
        self.assertFalse(result["checks"]["registration_imports"]["ok"])

    def test_unused_standard_library_import_can_still_be_removed(self):
        result = validate_patch(self.source, self.source.replace("import json\n", ""), self.path)
        self.assertTrue(result["ok"], result["failures"])

    def test_equivalent_relative_registration_import_is_retained(self):
        from services.patch_sanity import check_registration_imports

        patched = self.source.replace("from . import routes", "from .routes import register")
        self.assertTrue(check_registration_imports(self.source, patched, self.path)[0])

    def test_non_blueprint_package_keeps_normal_import_cleanup(self):
        source = "from . import utils\nvalue = 1\n"
        result = validate_patch(source, "value = 1\n", self.path)
        self.assertTrue(result["ok"], result["failures"])
