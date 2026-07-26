"""Skills registry + the append-only change feed (task #5230, phases 3-4).

THE CHANGE FEED IS THE POINT. A registry holding only current state answers
"what exists?" but never "what changed?" — and every incident this session began
with a transition nobody observed: a bulk DNS rewrite that swept in `mesh.`, a
node control URL pointing at a dead tunnel for a month, three weeks of backups
not reaching Drive. The state was observable each time; the CHANGE was not.

SCOPE HONESTY (phase 3). The first run of collect_skills() returned 0 commands
and reported success — the container's bind-mount exposes .claude/rules and
.claude/skills but NOT .claude/commands, so 18 real commands silently read as
"none". A missing source root is now an UNCOLLECTED SCOPE that reports itself
and refuses to mark its own rows absent.
"""

import pytest

pytest.importorskip("psycopg2")

from tests.dbguard import db_or_skip, import_or_skip  # noqa: E402

try:
    from database import get_db_cursor
    from services import platform_registry_service as prs
except Exception as exc:  # pragma: no cover
    import_or_skip(exc, "platform_registry_service")

_KEY = "skill:zz_test_skill_5230"


@pytest.fixture()
def registry():
    try:
        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute("SELECT to_regclass('public.platform_registry_skill') AS t")
            row = cur.fetchone()
            if (row["t"] if isinstance(row, dict) else row[0]) is None:
                pytest.skip("migration 467 not applied to this database")
            cur.execute("DELETE FROM platform_registry_skill WHERE skill_key = %s", (_KEY,))
            cur.execute("DELETE FROM platform_registry_change WHERE entity_key = %s", (_KEY,))
        yield
    except pytest.skip.Exception:
        raise
    except Exception as exc:
        db_or_skip(exc)
    finally:
        try:
            with get_db_cursor(commit=True) as (_c, cur):
                cur.execute("DELETE FROM platform_registry_skill WHERE skill_key = %s", (_KEY,))
                cur.execute("DELETE FROM platform_registry_change WHERE entity_key = %s", (_KEY,))
        except Exception:  # pragma: no cover
            pass


def _synth(**over):
    base = {
        "skill_key": _KEY,
        "kind": "skill",
        "name": "zz_test_skill_5230",
        "description": "original description",
        "source_path": ".claude/skills/zz/SKILL.md",
        "department": None,
    }
    base.update(over)
    return base


def _changes(key=_KEY):
    with get_db_cursor() as (_c, cur):
        cur.execute(
            "SELECT change_type, field, old_value, new_value FROM platform_registry_change "
            "WHERE entity_key = %s ORDER BY id",
            (key,),
        )
        return [dict(r) for r in cur.fetchall()]


# ------------------------------------------------------------- change feed ---
def test_appearance_is_recorded(registry):
    live = prs.collect_skills()
    prs.reconcile_skills(live + [_synth()])
    assert [c["change_type"] for c in _changes()] == ["appeared"]


def test_vanishing_is_recorded(registry):
    """The event nobody notices and everybody needs."""
    live = prs.collect_skills()
    prs.reconcile_skills(live + [_synth()])
    prs.reconcile_skills(live)
    assert "vanished" in [c["change_type"] for c in _changes()]


def test_reappearance_is_recorded(registry):
    live = prs.collect_skills()
    prs.reconcile_skills(live + [_synth()])
    prs.reconcile_skills(live)
    prs.reconcile_skills(live + [_synth()])
    assert "reappeared" in [c["change_type"] for c in _changes()]


def test_field_change_records_old_and_new(registry):
    live = prs.collect_skills()
    prs.reconcile_skills(live + [_synth()])
    prs.reconcile_skills(live + [_synth(description="a new description")])

    changed = [c for c in _changes() if c["change_type"] == "changed"]
    assert changed, "a tracked field changed but no row was written"
    c = changed[-1]
    assert c["field"] == "description"
    assert c["old_value"] == "original description"
    assert c["new_value"] == "a new description"


def test_unchanged_run_emits_nothing(registry):
    """Otherwise the feed drowns in its own exhaust and nobody reads it."""
    live = prs.collect_skills()
    prs.reconcile_skills(live + [_synth()])
    before = len(_changes())
    prs.reconcile_skills(live + [_synth()])
    assert len(_changes()) == before, "an identical collection produced change rows"


def test_untracked_field_churn_is_not_recorded(registry):
    """collected_at moves every run — recording it would bury the signal."""
    assert "collected_at" not in prs._TRACKED_FIELDS["skill"]
    assert "started_at" not in prs._TRACKED_FIELDS["service"]


def test_feed_is_append_only_in_practice(registry):
    """Two transitions must leave TWO rows — the second must not overwrite."""
    live = prs.collect_skills()
    prs.reconcile_skills(live + [_synth()])
    prs.reconcile_skills(live)
    prs.reconcile_skills(live + [_synth()])
    assert len(_changes()) >= 3


# ------------------------------------------------------------ scope honesty ---
def test_missing_command_root_is_an_uncollected_scope(registry, monkeypatch, tmp_path):
    """THE REGRESSION. 0 commands must not read as 'there are no commands'."""
    (tmp_path / ".claude" / "skills" / "x").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "x" / "SKILL.md").write_text("---\nname: x\ndescription: d\n---\n")
    monkeypatch.setattr(prs, "_REPO_ROOT", str(tmp_path))

    prs.collect_skills()
    scopes = getattr(prs.collect_skills, "scopes", {})
    assert scopes["skill"] is True
    assert scopes["command"] is False, "a missing .claude/commands root reported as collected"


def test_uncollected_scope_does_not_mark_its_rows_absent(registry, monkeypatch, tmp_path):
    """18 real commands must survive a bad mount."""
    live = prs.collect_skills()
    cmd = _synth(skill_key="command:zz_cmd_5230", kind="command", name="zz_cmd_5230")
    prs.reconcile_skills(live + [cmd])

    # Now collect from a tree that has skills but NO commands.
    (tmp_path / ".claude" / "skills" / "x").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "x" / "SKILL.md").write_text("---\nname: x\ndescription: d\n---\n")
    monkeypatch.setattr(prs, "_REPO_ROOT", str(tmp_path))
    prs.reconcile_skills()

    with get_db_cursor(commit=True) as (_c, cur):
        cur.execute("SELECT status FROM platform_registry_skill WHERE skill_key='command:zz_cmd_5230'")
        row = cur.fetchone()
        status = (row["status"] if isinstance(row, dict) else row[0]) if row else None
        cur.execute("DELETE FROM platform_registry_skill WHERE skill_key='command:zz_cmd_5230'")
        cur.execute("DELETE FROM platform_registry_change WHERE entity_key='command:zz_cmd_5230'")
    assert status == "present", "an uncollected scope marked its rows absent — a bad mount would erase 18 commands"


def test_empty_skill_set_is_refused(registry):
    with pytest.raises(ValueError, match="empty skill set"):
        prs.reconcile_skills([])


# ------------------------------------------------------------------- alarm ---
def test_collection_alarms_only_on_vanish(registry, monkeypatch):
    """Appearances are normal churn. A disappearance is the finding."""
    sent = []
    monkeypatch.setattr(prs, "_alert_vanished", lambda v: sent.append(v))
    monkeypatch.setattr(prs, "reconcile", lambda: {"collected": 0})
    monkeypatch.setattr(prs, "reconcile_services", lambda with_provenance=False: {"collected": 0})
    monkeypatch.setattr(prs, "reconcile_skills", lambda: {"collected": 0})
    monkeypatch.setattr(prs, "recent_changes", lambda **kw: [{"change_type": "appeared", "entity_key": "x"}])

    prs.run_registry_collection()
    assert not sent, "alarmed on an appearance"

    monkeypatch.setattr(
        prs, "recent_changes", lambda **kw: [{"change_type": "vanished", "entity_type": "module", "entity_key": "x"}]
    )
    prs.run_registry_collection()
    assert sent, "did NOT alarm on a disappearance"


def test_one_bad_scope_does_not_abort_the_others(registry, monkeypatch):
    """Unattended job: a broken docker socket must not also stop skills."""
    monkeypatch.setattr(prs, "reconcile", lambda: (_ for _ in ()).throw(RuntimeError("modules boom")))
    monkeypatch.setattr(prs, "reconcile_services", lambda with_provenance=False: {"collected": 7})
    monkeypatch.setattr(prs, "reconcile_skills", lambda: {"collected": 5})
    monkeypatch.setattr(prs, "recent_changes", lambda **kw: [])

    res = prs.run_registry_collection()
    assert res["ok"] is False
    assert "modules" in res["errors"]
    assert res["scopes"]["services"]["collected"] == 7
    assert res["scopes"]["skills"]["collected"] == 5


def test_work_control_can_disable_the_job(registry, monkeypatch):
    import services.work_control_service as wcs

    monkeypatch.setattr(wcs, "is_enabled", lambda key, default=True: False)
    res = prs.run_registry_collection()
    assert "skipped" in res
