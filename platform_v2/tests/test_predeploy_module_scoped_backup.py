"""#5279 / ADR-009 — pre-deploy snapshots scope to the MODULE, not the whole platform.

MEASURED (task #5279): 77 pre-deploy FULL backups in 7 days — 2.3 GB / 16 min EACH
(179 GB + 20.5 h) — to protect single-line lint fixes, while the module-tier backups
of the same day were 0-2 MB and instant. Worse, the full backup starved its own
W.A.R.D.E.N. gate: approvals 5472-5474 were denied for "backup age 8.2h exceeds
medium limit" because keeping the full snapshot fresh costs 16 minutes a time.

Owner direction (2026-07-27): reuse the existing Backup Manager MODULES machinery
(backup_module() → /backups/modules/, Modules tab, prune_modules() bound #5143)
instead of inventing a new snapshot layout. ADR-009's own words: "roll back via a
FRESH module backup; full snapshots become the safety net, not the per-fix default."

This suite pins:
  * backup_module() ships a generated rollback.sh + restore_map — making module
    backups the FIRST pre-deploy artifact auto_rollback can actually execute
    (full backups never ship rollback.sh, so auto-restore always fell to manual).
  * The rollback round-trip genuinely restores a mutated file (task item 5: a
    cheaper backup that cannot restore is strictly worse than an expensive one
    that can).
  * backup_module() is WIDENED to the ai_bridge / services pseudo-modules
    (task item 1 — the 68/172 coverage gap) — groundwork; POLICY still sends
    those to full snapshots (task item 4: wide blast radius).
  * The scope decision: only a fix contained in platform_v2/tools/<module>/ with
    an existing runtime file scopes down; migrations, services/, ai_bridge/,
    containment mismatches, and unresolvable paths stay FULL.
  * The W.A.R.D.E.N. gate: a scoped deploy converts a stale-age HARD denial into
    a soft advisory (the fresh module copy IS the restore point for the change);
    a full-scope deploy keeps today's hard gate; NO successful backup ever still
    denies even scoped. The age limits themselves are untouched.

DB writes are stubbed; filesystem work runs in tmp trees.
"""

import os
import subprocess
import sys
from contextlib import contextmanager

# Pin THIS tree's platform_v2 to the front of sys.path and bind `tools.*` BEFORE the
# services imports: importing services.backup_governance_service first pulls in modules
# that manipulate sys.path, which can resolve `tools.backup_manager._shared` from the
# MAIN checkout instead of the tree under test — the exact wrong-code-under-test trap
# (KB #283933). Import order here is deliberate, not cosmetic.
_TREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TREE_ROOT not in sys.path:
    sys.path.insert(0, _TREE_ROOT)

import tools.backup_manager._shared as bshared  # noqa: E402  — must bind this tree first

import services.backup_governance_service as bgov  # noqa: E402
import services.proposal_service as psvc  # noqa: E402


@contextmanager
def _noop_cursor(*_a, **_k):
    class _Cur:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return None

    yield None, _Cur()


class _RecordingCursorFactory:
    """Capture backup_log INSERT params without touching the real DB."""

    def __init__(self):
        self.executed = []

    @contextmanager
    def __call__(self, *_a, **_k):
        factory = self

        class _Cur:
            def execute(self, sql, params=None):
                factory.executed.append((sql, params))

            def fetchone(self):
                return None

        yield None, _Cur()


def _module_env(tmp_path, monkeypatch):
    """Build a fake PLATFORM_DIR + BACKUP_DIR and point _shared at them."""
    platform = tmp_path / "app"
    (platform / "tools" / "fakemod").mkdir(parents=True)
    (platform / "tools" / "fakemod" / "routes.py").write_text("ORIGINAL CONTENT\n")
    (platform / "templates" / "tools").mkdir(parents=True)
    (platform / "templates" / "tools" / "fakemod.html").write_text("<html>ORIGINAL</html>\n")
    (platform / "services").mkdir(parents=True)
    (platform / "services" / "helper.py").write_text("SERVICE ORIGINAL\n")
    backups = tmp_path / "backups"
    backups.mkdir()
    monkeypatch.setattr(bshared, "PLATFORM_DIR", str(platform))
    monkeypatch.setattr(bshared, "BACKUP_DIR", str(backups))
    monkeypatch.setattr(bshared, "get_backup_db_cursor", _noop_cursor)
    return platform, backups


class TestModuleBackupRollback:
    def test_module_backup_ships_rollback_script(self, tmp_path, monkeypatch):
        _module_env(tmp_path, monkeypatch)
        res = bshared.backup_module("fakemod")
        assert res["success"] is True
        script = os.path.join(res["backup_path"], "rollback.sh")
        assert os.path.isfile(script)
        import json

        with open(os.path.join(res["backup_path"], "metadata.json")) as f:
            meta = json.load(f)
        assert meta.get("restore_map"), "restore_map missing from metadata"

    def test_rollback_round_trip_restores_mutated_file(self, tmp_path, monkeypatch):
        """Task item 5 — the restore must be PROVEN, not assumed."""
        platform, _ = _module_env(tmp_path, monkeypatch)
        res = bshared.backup_module("fakemod")
        target = platform / "tools" / "fakemod" / "routes.py"
        target.write_text("MUTATED BY A BAD DEPLOY\n")
        proc = subprocess.run(
            ["bash", os.path.join(res["backup_path"], "rollback.sh")],
            capture_output=True,
            text=True,
            cwd=res["backup_path"],
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        assert target.read_text() == "ORIGINAL CONTENT\n"

    def test_widened_services_pseudo_module(self, tmp_path, monkeypatch):
        """Task item 1 — platform_v2/services/ is now coverable by the module primitive."""
        platform, _ = _module_env(tmp_path, monkeypatch)
        res = bshared.backup_module("services")
        assert res["success"] is True
        saved = os.path.join(res["backup_path"], "services", "helper.py")
        assert os.path.isfile(saved)
        target = platform / "services" / "helper.py"
        target.write_text("BROKEN\n")
        proc = subprocess.run(
            ["bash", os.path.join(res["backup_path"], "rollback.sh")],
            capture_output=True,
            text=True,
            cwd=res["backup_path"],
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        assert target.read_text() == "SERVICE ORIGINAL\n"

    def test_widened_ai_bridge_pseudo_module(self, tmp_path, monkeypatch):
        _module_env(tmp_path, monkeypatch)
        bridge = tmp_path / "ai_bridge"
        bridge.mkdir()
        (bridge / "comfyui_service.py").write_text("BRIDGE ORIGINAL\n")
        monkeypatch.setattr(bshared, "_AI_BRIDGE_ROOTS", (str(bridge),))
        res = bshared.backup_module("ai_bridge")
        assert res["success"] is True
        assert os.path.isfile(os.path.join(res["backup_path"], "ai_bridge", "comfyui_service.py"))

    def test_predeploy_flag_stamps_ephemeral_notes(self, tmp_path, monkeypatch):
        _module_env(tmp_path, monkeypatch)
        rec = _RecordingCursorFactory()
        monkeypatch.setattr(bshared, "get_backup_db_cursor", rec)
        res = bshared.backup_module("fakemod", proposal_id=999, predeploy=True)
        assert res["success"] is True
        inserts = [p for (_sql, p) in rec.executed if p]
        assert inserts, "no backup_log INSERT captured"
        notes = [str(v) for v in inserts[-1] if isinstance(v, str) and "Pre-deploy snapshot" in str(v)]
        assert notes, f"notes must start with 'Pre-deploy snapshot' for ephemeral classification: {inserts[-1]}"

    def test_invalid_module_name_refused(self, tmp_path, monkeypatch):
        _module_env(tmp_path, monkeypatch)
        res = bshared.backup_module("evil/../../etc")
        assert res["success"] is False


class TestPredeployScopeDecision:
    def _proposal(self, tmp_path, **meta_overrides):
        runtime = tmp_path / "app" / "tools" / "fakemod" / "routes.py"
        meta = {
            "module_name": "fakemod",
            "file_path": "platform_v2/tools/fakemod/routes.py",
            "runtime_file": str(runtime),
        }
        meta.update(meta_overrides)
        return {"id": 1, "metadata": meta}

    def test_contained_tools_fix_scopes_to_module(self, tmp_path, monkeypatch):
        _module_env(tmp_path, monkeypatch)
        p = self._proposal(tmp_path)
        assert psvc._predeploy_module_scope(p) == "fakemod"

    def test_services_and_ai_bridge_stay_full(self, tmp_path, monkeypatch):
        _module_env(tmp_path, monkeypatch)
        p = self._proposal(
            tmp_path,
            module_name="services",
            file_path="platform_v2/services/agent_service.py",
        )
        assert psvc._predeploy_module_scope(p) is None
        p = self._proposal(tmp_path, module_name="ai_bridge", file_path="ai_bridge/comfyui_service.py")
        assert psvc._predeploy_module_scope(p) is None

    def test_migrations_stay_full(self, tmp_path, monkeypatch):
        _module_env(tmp_path, monkeypatch)
        p = self._proposal(tmp_path, file_path="database/migrations/462_x.sql")
        assert psvc._predeploy_module_scope(p) is None

    def test_containment_mismatch_stays_full(self, tmp_path, monkeypatch):
        """A backup only protects what it contains — file outside tools/<module>/ -> FULL."""
        _module_env(tmp_path, monkeypatch)
        p = self._proposal(tmp_path, file_path="platform_v2/tools/othermod/routes.py")
        assert psvc._predeploy_module_scope(p) is None

    def test_missing_or_absent_runtime_file_stays_full(self, tmp_path, monkeypatch):
        _module_env(tmp_path, monkeypatch)
        p = self._proposal(tmp_path, runtime_file="")
        assert psvc._predeploy_module_scope(p) is None
        p = self._proposal(tmp_path, runtime_file=str(tmp_path / "nope.py"))
        assert psvc._predeploy_module_scope(p) is None

    def test_module_backup_ref_prefixes_modules_dir(self):
        """improvement_deployments stores 'modules/<name>' so snapshot_exists + auto_rollback
        (both join BACKUP_DIR + backup_name) resolve the module subdir."""
        ref = psvc._module_backup_ref({"backup_name": "20260727_1_module_fakemod"})
        assert ref == "modules/20260727_1_module_fakemod"


class TestScopedClearanceGate:
    def _arm(self, monkeypatch, age_hours):
        monkeypatch.setattr(
            bgov,
            "get_health_summary",
            lambda: {"tier_health": {"primary": {"last_success_age_hours": age_hours}}},
        )
        monkeypatch.setattr(bgov, "snapshot_module", lambda **_k: {"success": True, "snapshot_id": 1, "error": None})
        monkeypatch.setattr(bgov, "_notify_denial", lambda *a, **k: None)
        monkeypatch.setattr(
            bgov,
            "_load_gate_config",
            lambda: {
                "critical": {"max_age_hours": 48, "gate_type": "soft", "override": "none"},
                "high": {"max_age_hours": 12, "gate_type": "soft", "override": "telegram_approval"},
                "medium": {"max_age_hours": 6, "gate_type": "hard", "override": "kytran_approval"},
                "low": {"max_age_hours": 24, "gate_type": "hard", "override": "kytran_approval"},
            },
        )

    def test_scoped_deploy_softens_stale_age_denial(self, monkeypatch):
        """The 8.2h denial that blocked approvals 5472-5474: scoped -> advisory, not a block."""
        self._arm(monkeypatch, age_hours=8.2)
        r = bgov.request_deploy_clearance("fakemod", "medium", proposal_id=1, deploy_scope="scoped")
        assert r["approved"] is True
        assert r["gate_level"] == "soft"
        assert "scoped" in r["reason"].lower()

    def test_full_deploy_keeps_hard_gate(self, monkeypatch):
        self._arm(monkeypatch, age_hours=8.2)
        r = bgov.request_deploy_clearance("fakemod", "medium", proposal_id=1, deploy_scope="full")
        assert r["approved"] is False

    def test_scoped_with_no_successful_backup_ever_still_denies(self, monkeypatch):
        """A scoped file copy can roll back the change but is NOT a platform restore point."""
        self._arm(monkeypatch, age_hours=None)
        r = bgov.request_deploy_clearance("fakemod", "medium", proposal_id=1, deploy_scope="scoped")
        assert r["approved"] is False
