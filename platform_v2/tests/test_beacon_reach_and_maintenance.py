"""Beacon-side reachability probe (#5222) and the maintenance splash (#5226).

#5222 — ask the machine that actually has to connect.
    dr_service_listening() runs on boston-2 and proves a service is bound beyond
    loopback. It CANNOT prove Beacon can traverse UFW to reach it, and Beacon is
    the machine doing the reaching. That gap is not theoretical: on 2026-07-26
    derper listened on *:8443 while Beacon's UFW (policy DROP, only 22/80/443)
    dropped every external client. A local probe says "fine"; Beacon says no.

    Three-state on purpose. 0=reached, 1=refused, 2=INDETERMINATE. Collapsing 2
    into 1 would strand a healthy service whenever Beacon itself is unreachable —
    turning a measurement outage into a service outage.

#5226 — ADR-012's third outcome.
    Before it, an out-of-scope hostname during failover had two options, both
    bad: point at a dead hub (opaque error) or point at a host that cannot serve
    it (worse — ADR-009). The splash is the honest third: 503 + Retry-After.
    NOT 200 — a maintenance page returning 200 tells every monitor the service
    is healthy.

Both drive the REAL beacon_flip.sh with _beacon_ssh stubbed, rather than
reimplementing the logic.
"""

import re
import subprocess
import textwrap
from pathlib import Path

import pytest
from tests.repo_root import repo_root

_MARKER = Path("scripts") / "dr" / "beacon_flip.sh"


def _find_repo():
    for base in list(Path(__file__).resolve().parents) + [Path("/mnt/archie_brain")]:
        if (base / _MARKER).exists():
            return base
    return repo_root()


REPO = _find_repo()
HELPER = REPO / _MARKER

pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="beacon_flip.sh not present in this checkout")


def _run(body, ssh_reply="", ssh_rc=0, have_key=True):
    """Source the real helper with _beacon_ssh stubbed, then run `body`."""
    key = "$WORK/fake_key"
    script = textwrap.dedent(
        f"""
        set -uo pipefail
        WORK=$(mktemp -d)
        export FLEET_KEY="{key}"
        {"touch $FLEET_KEY" if have_key else ""}
        export BEACON_CADDYFILE="$WORK/Caddyfile"
        printf 'example.com {{\\n  respond "real" 200\\n}}\\n' > "$BEACON_CADDYFILE"
        . "{HELPER}"
        # Stub the remote hop. Real ssh is never invoked in tests.
        _beacon_ssh() {{ printf '%s' '{ssh_reply}'; return {ssh_rc}; }}
        {body}
        """
    ).strip()
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


# ------------------------------------------------------------------ #5222 ----
def test_beacon_reached_it_returns_zero():
    rc, out = _run('beacon_can_reach 100.64.0.10 8095; echo "RC=$?"', ssh_reply="REACH_OK")
    assert "RC=0" in out, out


def test_beacon_refused_returns_one_and_says_why():
    """The derper/UFW case: bound locally, unreachable from Beacon."""
    rc, out = _run('beacon_can_reach 2.25.170.252 8443; echo "RC=$?"', ssh_reply="REACH_NO")
    assert "RC=1" in out, out
    assert "CANNOT reach" in out
    assert "firewall" in out.lower(), "must name the likely cause, not just fail"


def test_beacon_unreachable_is_INDETERMINATE_not_failure():
    """THE IMPORTANT ONE. rc 2, never 1 — otherwise a measurement outage
    becomes a service outage: we would refuse to flip a perfectly healthy
    service just because Beacon happened to be unreachable."""
    rc, out = _run('beacon_can_reach 100.64.0.10 3000; echo "RC=$?"', ssh_reply="", ssh_rc=255)
    assert "RC=2" in out, out
    assert "cannot measure" in out.lower()


def test_missing_fleet_key_is_also_indeterminate():
    rc, out = _run('beacon_can_reach 100.64.0.10 3000; echo "RC=$?"', have_key=False)
    assert "RC=2" in out, out


def test_unparseable_reply_is_indeterminate_not_success():
    """Fail toward 'I don't know', never toward 'yes'."""
    rc, out = _run('beacon_can_reach 1.2.3.4 80; echo "RC=$?"', ssh_reply="garbage")
    assert "RC=2" in out, out


# ------------------------------------------------------------------ #5226 ----
def test_maintenance_on_reports_success():
    rc, out = _run(
        'beacon_maintenance_mode on server.kytranempowerment.com media.kytranempowerment.com; echo "RC=$?"',
        ssh_reply="MAINT_ON_OK",
    )
    assert "RC=0" in out, out
    assert "maintenance splash ON" in out
    assert "503" in out, "the operator must see it is a 503, not a 200"


def test_maintenance_off_reports_restore():
    rc, out = _run('beacon_maintenance_mode off server.kytranempowerment.com; echo "RC=$?"', ssh_reply="MAINT_OFF_OK")
    assert "RC=0" in out, out
    assert "cleared" in out


def test_maintenance_rollback_is_reported_as_failure():
    """If caddy validate rejects it, the Caddyfile is restored and we must NOT
    report success — the front door for ~20 hostnames rides on that file."""
    rc, out = _run('beacon_maintenance_mode on x.example.com; echo "RC=$?"', ssh_reply="MAINT_ON_FAIL")
    assert "RC=1" in out, out
    assert "rolled back" in out.lower()
    assert "front door untouched" in out.lower()


def test_maintenance_with_no_hostnames_is_a_noop():
    rc, out = _run('beacon_maintenance_mode on; echo "RC=$?"')
    assert "RC=0" in out, out
    assert "no hostnames" in out.lower()


def test_maintenance_without_fleet_key_fails_loudly():
    rc, out = _run('beacon_maintenance_mode on a.example.com; echo "RC=$?"', have_key=False)
    assert "RC=1" in out, out
    assert "fleet key" in out.lower()


def test_splash_markup_is_self_contained():
    """The hub is down by definition when this runs — the page cannot fetch
    assets from it."""
    src = HELPER.read_text()
    block = re.search(r"beacon_maintenance_mode\(\) \{.*?\n\}", src, re.S)
    assert block, "function not found"
    body = block.group(0)
    assert "Services are down or under maintenance" in body
    assert "503" in body and "Retry-After" in body
    assert "http://" not in body.split("respond")[1][:400], "splash must not fetch remote assets"
