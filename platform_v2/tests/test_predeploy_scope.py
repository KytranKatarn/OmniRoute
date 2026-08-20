"""#5835 / ADR-009 — pre-deploy backup scope resolution + the rollback round-trip.

Two halves, and the second is the point:

1. `resolve_scope` guards — that a scope is chosen ONLY on proven containment.
2. An EXECUTABLE proof that the `rollback.sh` a module backup ships actually restores a
   tree, subdirectories included. The `("services", "ai_bridge")` exclusion in
   `_predeploy_module_scope` was explicitly held "until the scoped rung is proven there";
   this is that proof, and it runs in CI rather than being a one-off manual rehearsal.

A cheaper backup that cannot restore is strictly worse than an expensive one that can, so
these tests are the precondition for the exclusion being lifted — not paperwork after it.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.predeploy_scope import (  # noqa: E402
    default_pseudo_roots,
    normalize_module_name,
    resolve_scope,
)


class TestNormalizeModuleName(unittest.TestCase):
    def test_bracketed_label_from_real_proposals(self):
        # improvement_proposals 8721/8725/8726/8980 all carry this literal value.
        self.assertEqual(normalize_module_name("[AI_BRIDGE]"), "ai_bridge")

    def test_plain_names_pass_through(self):
        self.assertEqual(normalize_module_name("department_hq"), "department_hq")
        self.assertEqual(normalize_module_name("  services  "), "services")

    def test_rejects_unusable(self):
        for bad in (None, "", "   ", "[]", "a/b", "a b", "../etc", "[a/b]"):
            self.assertIsNone(normalize_module_name(bad), bad)


class TestResolveScope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.platform = os.path.join(self.tmp, "platform_v2")
        self.tools = os.path.join(self.platform, "tools")
        self.aib = os.path.join(self.tmp, "ai_bridge")
        os.makedirs(os.path.join(self.tools, "fitness"))
        os.makedirs(os.path.join(self.platform, "services"))
        os.makedirs(self.aib)
        self.aib_file = os.path.join(self.aib, "translation_service.py")
        open(self.aib_file, "w").close()
        self.fit_file = os.path.join(self.tools, "fitness", "routes.py")
        open(self.fit_file, "w").close()
        self.svc_file = os.path.join(self.platform, "services", "agent_service.py")
        open(self.svc_file, "w").close()
        self.roots = default_pseudo_roots(self.platform, (self.aib,))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _resolve(self, meta):
        return resolve_scope(meta, tools_root=self.tools, pseudo_roots=self.roots)

    def test_real_ai_bridge_proposal_now_scopes(self):
        """The exact metadata shape of proposal 8725, which took a FULL 2.8 GB snapshot."""
        self.assertEqual(
            self._resolve(
                {
                    "module_name": "[AI_BRIDGE]",
                    "file_path": "[AI_BRIDGE]/translation_service.py",
                    "runtime_file": self.aib_file,
                }
            ),
            "ai_bridge",
        )

    def test_services_pseudo_module_scopes(self):
        self.assertEqual(
            self._resolve(
                {
                    "module_name": "services",
                    "file_path": "[SERVICES]/agent_service.py",
                    "runtime_file": self.svc_file,
                }
            ),
            "services",
        )

    def test_ordinary_module_still_scopes(self):
        self.assertEqual(
            self._resolve(
                {
                    "module_name": "fitness",
                    "file_path": "platform_v2/tools/fitness/routes.py",
                    "runtime_file": self.fit_file,
                }
            ),
            "fitness",
        )

    # ---- everything below must fall UP to the FULL snapshot ----

    def test_runtime_file_missing_is_full(self):
        """A backup of a file that is not there protects nothing."""
        self.assertIsNone(
            self._resolve(
                {
                    "module_name": "[AI_BRIDGE]",
                    "file_path": "[AI_BRIDGE]/gone.py",
                    "runtime_file": os.path.join(self.aib, "gone.py"),
                }
            )
        )

    def test_runtime_file_outside_the_tree_is_full(self):
        outside = os.path.join(self.tmp, "outside.py")
        open(outside, "w").close()
        self.assertIsNone(
            self._resolve(
                {
                    "module_name": "[AI_BRIDGE]",
                    "file_path": "[AI_BRIDGE]/outside.py",
                    "runtime_file": outside,
                }
            )
        )

    def test_symlink_escape_is_full(self):
        """A link inside the tree pointing out of it must not read as contained."""
        outside = os.path.join(self.tmp, "secret.py")
        open(outside, "w").close()
        link = os.path.join(self.aib, "secret.py")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.assertIsNone(
            self._resolve(
                {
                    "module_name": "[AI_BRIDGE]",
                    "file_path": "[AI_BRIDGE]/secret.py",
                    "runtime_file": link,
                }
            )
        )

    def test_basename_mismatch_is_full(self):
        """file_path is synthetic, so it cannot prove containment — but it must still
        agree about WHICH file, or the metadata is not describing one change."""
        self.assertIsNone(
            self._resolve(
                {
                    "module_name": "[AI_BRIDGE]",
                    "file_path": "[AI_BRIDGE]/something_else.py",
                    "runtime_file": self.aib_file,
                }
            )
        )

    def test_traversal_is_full(self):
        self.assertIsNone(
            self._resolve(
                {
                    "module_name": "fitness",
                    "file_path": "platform_v2/tools/fitness/../../app.py",
                    "runtime_file": self.fit_file,
                }
            )
        )

    def test_containment_mismatch_is_full(self):
        """module says fitness, the runtime file lives in ai_bridge."""
        self.assertIsNone(
            self._resolve(
                {
                    "module_name": "fitness",
                    "file_path": "platform_v2/tools/fitness/translation_service.py",
                    "runtime_file": self.aib_file,
                }
            )
        )

    def test_relative_runtime_file_is_full(self):
        self.assertIsNone(
            self._resolve(
                {
                    "module_name": "fitness",
                    "file_path": "platform_v2/tools/fitness/routes.py",
                    "runtime_file": "platform_v2/tools/fitness/routes.py",
                }
            )
        )

    def test_unknown_module_outside_tools_is_full(self):
        self.assertIsNone(
            self._resolve(
                {
                    "module_name": "migrations",
                    "file_path": "database/migrations/472_x.sql",
                    "runtime_file": self.fit_file,
                }
            )
        )

    def test_garbage_metadata_is_full(self):
        for meta in (None, "not-a-dict", {}, {"module_name": "fitness"}):
            self.assertIsNone(resolve_scope(meta, tools_root=self.tools, pseudo_roots=self.roots), meta)


class TestRollbackRoundTrip(unittest.TestCase):
    """THE proof the policy exclusion was waiting for: does the generated rollback.sh
    actually put a tree back, subdirectories and all?"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rollback_restores_nested_tree(self):
        from tools.backup_manager._shared import _write_rollback_script

        live = os.path.join(self.tmp, "live", "ai_bridge")
        os.makedirs(os.path.join(live, "sub", "deeper"))
        top = os.path.join(live, "mod.py")
        nested = os.path.join(live, "sub", "deeper", "nested.py")
        with open(top, "w") as fh:
            fh.write("ORIGINAL TOP\n")
        with open(nested, "w") as fh:
            fh.write("ORIGINAL NESTED\n")

        # Take the backup exactly as backup_module() does for a pseudo-module:
        # copytree into <backup>/<rel>, restore_map [[rel, live_abs]].
        backup = os.path.join(self.tmp, "backup")
        os.makedirs(backup)
        shutil.copytree(live, os.path.join(backup, "ai_bridge"), dirs_exist_ok=True)
        restore_map = [["ai_bridge", live]]
        _write_rollback_script(backup, restore_map)

        script = os.path.join(backup, "rollback.sh")
        self.assertTrue(os.path.isfile(script), "no rollback.sh shipped")
        # Assert the MODE BITS, not os.access(X_OK): the container's /tmp is mounted
        # noexec, so access() reports False on a correctly-chmodded file. It does not
        # matter either way — auto_rollback runs `subprocess.run(["bash", script])`
        # (auto_rollback.py:233), which never consults the exec bit, and real backups
        # live on /backups (plain ext4). Testing X_OK here would fail CI over a property
        # the product does not depend on.
        self.assertEqual(stat.S_IMODE(os.stat(script).st_mode), 0o755)
        with open(script) as fh:
            self.assertTrue(fh.readline().startswith("#!"), "no shebang in rollback.sh")

        # Break BOTH depths, then roll back.
        with open(top, "w") as fh:
            fh.write("BROKEN\n")
        with open(nested, "w") as fh:
            fh.write("BROKEN\n")

        proc = subprocess.run(["bash", script], capture_output=True, text=True, cwd=backup, timeout=60)
        self.assertEqual(proc.returncode, 0, f"rollback failed: {proc.stderr}")

        with open(top) as fh:
            self.assertEqual(fh.read(), "ORIGINAL TOP\n")
        with open(nested) as fh:
            self.assertEqual(fh.read(), "ORIGINAL NESTED\n", "nested file NOT restored — scoping unsafe")

    def test_rollback_leaves_files_created_after_the_backup(self):
        """Documented, deliberate behaviour — pinned so nobody 'fixes' it by accident and
        turns a rollback into a delete."""
        from tools.backup_manager._shared import _write_rollback_script

        live = os.path.join(self.tmp, "live", "ai_bridge")
        os.makedirs(live)
        with open(os.path.join(live, "a.py"), "w") as fh:
            fh.write("A\n")
        backup = os.path.join(self.tmp, "backup")
        os.makedirs(backup)
        shutil.copytree(live, os.path.join(backup, "ai_bridge"), dirs_exist_ok=True)
        _write_rollback_script(backup, [["ai_bridge", live]])

        new_file = os.path.join(live, "added_after.py")
        with open(new_file, "w") as fh:
            fh.write("NEW\n")

        proc = subprocess.run(
            ["bash", os.path.join(backup, "rollback.sh")],
            capture_output=True,
            text=True,
            cwd=backup,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.isfile(new_file), "rollback deleted a post-backup file")


if __name__ == "__main__":
    unittest.main()
