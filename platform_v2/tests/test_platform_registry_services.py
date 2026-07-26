"""Living Platform Registry — services (task #5230, Phase 2).

Three properties carry this phase, and all three fail SILENTLY if broken:

1. **The transient filter.** `docker ps -a` on this host also returns throwaway
   `--rm` containers — the test suite spawns them constantly. Recording those
   creates rows marked absent seconds later, burying real disappearances in
   noise. The rule is "compose-managed OR has a restart policy", and BOTH halves
   are load-bearing: `archie_hub_caddy` and `media_samba` run via plain
   `docker run` with `restart=unless-stopped`, so filtering on the compose label
   alone would silently drop two live services.

2. **Scoped absence.** Docker and the product list are collected independently
   and either can fail. A scope that failed to collect must NOT mark its rows
   absent — "I could not look" is not "it is gone". Marking every container
   absent because the socket was missing would manufacture a fleet-wide outage
   out of a permissions problem.

3. **fail_open is an UNKNOWN, not a fault.** check_products() reports fail_open
   when a product is unreachable or has no resolvable expected SHA. Rendering
   that as drift is how alert fatigue starts, and 4 of 9 products are currently
   fail_open (no /version endpoint yet, or the hub-hairpin).
"""

import pytest

pytest.importorskip("psycopg2")

from tests.dbguard import db_or_skip, import_or_skip  # noqa: E402

try:
    from database import get_db_cursor
    from services import platform_registry_service as prs
except Exception as exc:  # pragma: no cover - import/env dependent
    import_or_skip(exc, "platform_registry_service")

_KEY = "zz_test_service_5230"


@pytest.fixture()
def registry():
    try:
        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute("SELECT to_regclass('public.platform_registry_service') AS t")
            row = cur.fetchone()
            if (row["t"] if isinstance(row, dict) else row[0]) is None:
                pytest.skip("migration 466 not applied to this database")
            cur.execute("DELETE FROM platform_registry_service WHERE service_key = %s", (_KEY,))
        yield
    except pytest.skip.Exception:
        raise
    except Exception as exc:
        db_or_skip(exc)
    finally:
        try:
            with get_db_cursor(commit=True) as (_c, cur):
                cur.execute("DELETE FROM platform_registry_service WHERE service_key = %s", (_KEY,))
        except Exception:  # pragma: no cover
            pass


def _synthetic(**over):
    base = {
        "service_key": _KEY,
        "kind": "container",
        "host": "hub",
        "container_name": _KEY,
        "image": "alpine:latest",
        "container_state": "running",
        "restart_policy": "unless-stopped",
        "compose_project": "zz",
        "compose_service": "zz",
        "ports": [],
        "started_at": None,
        "version_url": None,
    }
    base.update(over)
    return base


def _row(key=_KEY):
    with get_db_cursor() as (_c, cur):
        cur.execute("SELECT * FROM platform_registry_service WHERE service_key=%s", (key,))
        r = cur.fetchone()
        return dict(r) if r else None


# --------------------------------------------------------- transient filter ---
def test_transient_container_is_not_a_service(registry, monkeypatch):
    """A `docker run --rm` container has no compose label and restart=no."""

    class _FakeImage:
        tags = ["alpine:latest"]
        id = "sha256:deadbeef"

    class _FakeContainer:
        def __init__(self, name, labels, policy):
            self.name, self.labels, self.status = name, labels, "running"
            self.image = _FakeImage()
            self.attrs = {
                "HostConfig": {"RestartPolicy": {"Name": policy}},
                "NetworkSettings": {"Ports": {}},
                "State": {"StartedAt": None},
            }

    fake = [
        _FakeContainer("real_compose", {"com.docker.compose.project": "archie_brain"}, "no"),
        _FakeContainer("real_bare_caddy", {}, "unless-stopped"),  # the archie_hub_caddy case
        _FakeContainer("zz_throwaway", {}, "no"),  # the pytest case
    ]

    class _FakeClient:
        class containers:
            @staticmethod
            def list(all=False):
                return fake

    monkeypatch.setattr(prs, "docker", type("m", (), {"from_env": staticmethod(lambda: _FakeClient)}), raising=False)
    import sys

    monkeypatch.setitem(sys.modules, "docker", type("m", (), {"from_env": staticmethod(lambda: _FakeClient)}))

    names = {c["service_key"] for c in prs.collect_containers()}
    assert "real_compose" in names, "compose-managed service was dropped"
    assert "real_bare_caddy" in names, (
        "a service with a restart policy but NO compose label was dropped — that is "
        "archie_hub_caddy and media_samba, both live"
    )
    assert "zz_throwaway" not in names, "a throwaway --rm container was recorded as a service"


# ----------------------------------------------------------- scoped absence ---
def test_failed_docker_scope_does_not_mark_containers_absent(registry, monkeypatch):
    """THE ONE THAT MATTERS. 'I could not look' is not 'it is gone'."""
    prs.reconcile_services(with_provenance=False)  # seed a real baseline

    def boom():
        raise RuntimeError("docker socket unavailable (simulated)")

    monkeypatch.setattr(prs, "collect_containers", boom)
    summary = prs.reconcile_services(with_provenance=False)

    assert summary["scopes"]["container"] is False
    assert summary["scopes"]["product"] is True
    assert summary["absent"] == 0, "a failed scope marked its rows absent — manufactures a fake outage"

    with get_db_cursor() as (_c, cur):
        cur.execute("SELECT count(*) AS n FROM platform_registry_service WHERE kind='container' AND status='absent'")
        r = cur.fetchone()
        assert (r["n"] if isinstance(r, dict) else r[0]) == 0


def test_all_scopes_failing_raises(registry, monkeypatch):
    """Refuse to reconcile nothing rather than silently no-op."""
    monkeypatch.setattr(prs, "collect_containers", lambda: (_ for _ in ()).throw(RuntimeError("no docker")))
    monkeypatch.setattr(prs, "collect_products", lambda with_provenance=False: [])
    with pytest.raises(RuntimeError, match="no service scope"):
        prs.reconcile_services()


# ------------------------------------------------------------ never deletes ---
def test_vanished_service_marked_absent_not_deleted(registry, monkeypatch):
    real = prs.collect_containers()
    monkeypatch.setattr(prs, "collect_containers", lambda: real + [_synthetic()])
    prs.reconcile_services(with_provenance=False)
    assert _row()["status"] == "present"

    monkeypatch.setattr(prs, "collect_containers", lambda: real)
    prs.reconcile_services(with_provenance=False)

    r = _row()
    assert r is not None, "row DELETED — the disappearance evidence is gone"
    assert r["status"] == "absent"


def test_absent_service_freezes_last_seen_at(registry, monkeypatch):
    real = prs.collect_containers()
    monkeypatch.setattr(prs, "collect_containers", lambda: real + [_synthetic()])
    prs.reconcile_services(with_provenance=False)
    when = _row()["last_seen_at"]

    monkeypatch.setattr(prs, "collect_containers", lambda: real)
    prs.reconcile_services(with_provenance=False)
    assert _row()["last_seen_at"] == when, "last_seen_at moved after the service vanished"


# ------------------------------------------------------------ notes safety ----
def test_collector_never_overwrites_service_notes(registry, monkeypatch):
    real = prs.collect_containers()
    monkeypatch.setattr(prs, "collect_containers", lambda: real + [_synthetic()])
    prs.reconcile_services(with_provenance=False)
    assert prs.set_service_notes(_KEY, "edit sabnzbd.ini directly, set_config is unreliable")

    monkeypatch.setattr(prs, "collect_containers", lambda: real + [_synthetic(image="alpine:3.20")])
    prs.reconcile_services(with_provenance=False)

    r = _row()
    assert r["image"] == "alpine:3.20", "collected fields must refresh"
    assert r["notes"] == "edit sabnzbd.ini directly, set_config is unreliable"


def test_notes_not_in_collected_column_sets():
    assert "notes" not in prs._SERVICE_COLLECTED
    assert "notes" not in prs._PROVENANCE_COLLECTED


# -------------------------------------------------------------- provenance ---
def test_cheap_run_does_not_stamp_provenance(registry, monkeypatch):
    """A container-only collection must leave a real drift reading ALONE — and
    must not date it as if it were re-measured."""
    real = prs.collect_containers()
    monkeypatch.setattr(
        prs,
        "collect_products",
        lambda with_provenance=False: [
            _synthetic(
                kind="product",
                container_name=None,
                **(
                    {"baked_sha": "abc123", "expected_sha": "abc123", "drift_status": "in_sync", "provenance_at": None}
                    if with_provenance
                    else {}
                ),
            )
        ],
    )
    monkeypatch.setattr(prs, "collect_containers", lambda: real)

    prs.reconcile_services(with_provenance=True)
    prs.reconcile_services(with_provenance=False)  # cheap run

    r = _row()
    assert r["drift_status"] == "in_sync", "a cheap run wiped a real provenance reading"


def test_fail_open_is_a_valid_status_not_drift():
    """fail_open means unreachable / unresolvable — an UNKNOWN. It must survive
    into the table verbatim so nothing downstream can render it as a fault."""
    with get_db_cursor() as (_c, cur):
        cur.execute(
            "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint "
            "WHERE conname LIKE '%%drift_status%%' AND conrelid = 'platform_registry_service'::regclass"
        )
        row = cur.fetchone()
    assert row, "drift_status CHECK constraint missing"
    d = row["d"] if isinstance(row, dict) else row[0]
    for s in ("in_sync", "drift", "fail_open"):
        assert s in d
