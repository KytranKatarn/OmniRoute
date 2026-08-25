"""Beacon selective upstream flipping — scripts/dr/beacon_flip.sh (task #5214).

These tests EXECUTE the real shell helper against the repo's real Beacon
Caddyfile. That is deliberate: the defect being fixed (a blanket
``sed 's|100.64.0.4|100.64.0.10|g'``) is invisible to any test that merely
asserts on source text — it only shows up when the substitution actually runs
over a file with ~20 upstreams. KB #283579 / #283933: a check that does not
exercise the changed code path proves nothing.

``ssh``/``caddy``/``systemctl`` are stubbed so the helper's remote command runs
locally against a temp copy of the Caddyfile.
"""

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from tests.repo_root import repo_root

_MARKER = Path("scripts") / "dr" / "beacon_flip.sh"


def _find_repo():
    """Locate the repo root.

    Cannot assume a fixed depth: on the host the tests live at
    <repo>/platform_v2/tests/, but INSIDE the container platform_v2 is mounted
    as /app and the repo root as /mnt/archie_brain, so parents[2] is '/'.
    """
    for base in list(Path(__file__).resolve().parents) + [Path("/mnt/archie_brain")]:
        if (base / _MARKER).exists():
            return base
    return repo_root()


REPO = _find_repo()
BEACON_FLIP = REPO / "scripts" / "dr" / "beacon_flip.sh"
BEACON_CADDYFILE = REPO / "scripts" / "beacon" / "Caddyfile"

HUB = "100.64.0.4"
DR = "100.64.0.10"

pytestmark = pytest.mark.skipif(
    not BEACON_FLIP.exists() or not BEACON_CADDYFILE.exists(),
    reason="DR helper or Beacon Caddyfile not present in this checkout",
)


def _run_flip(tmp_path, args, caddy_validate_ok=True):
    """Run beacon_flip_ports against a temp copy of the Beacon Caddyfile.

    Returns (returncode, stdout, text_of_caddyfile_after).
    """
    workdir = tmp_path
    caddyfile = workdir / "Caddyfile"
    shutil.copy(BEACON_CADDYFILE, caddyfile)

    # Stub the two remote binaries the helper shells out to.
    bindir = workdir / "bin"
    bindir.mkdir()
    (bindir / "caddy").write_text("#!/bin/bash\nexit %d\n" % (0 if caddy_validate_ok else 1))
    (bindir / "systemctl").write_text("#!/bin/bash\nexit 0\n")
    for stub in ("caddy", "systemctl"):
        (bindir / stub).chmod(0o755)

    driver = workdir / "driver.sh"
    driver.write_text(
        textwrap.dedent(
            f"""
            set -uo pipefail
            export PATH="{bindir}:$PATH"
            export BEACON_CADDYFILE="{caddyfile}"
            export FLEET_KEY="{workdir}/fake_key"
            touch "$FLEET_KEY"
            . "{BEACON_FLIP}"
            # Run the helper's "remote" command locally instead of over ssh.
            _beacon_ssh() {{ bash -c "$1"; }}
            beacon_flip_ports {args}
            """
        ).strip()
    )

    proc = subprocess.run(["bash", str(driver)], capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout + proc.stderr, caddyfile.read_text()


def _upstream_ports(text, ip):
    """Ports currently proxied to `ip` via a reverse_proxy directive."""
    ports = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("reverse_proxy") and f"http://{ip}:" in stripped:
            ports.append(stripped.split(f"http://{ip}:")[1].split()[0])
    return sorted(ports)


def test_platform_flip_moves_only_port_3000(tmp_path):
    """A failover must move the platform upstream and NOTHING else.

    This is the regression that took ~20 healthy hub-only services offline on
    2026-07-25: KSO was 'Up (healthy)' on the hub the whole time while
    server.kytranempowerment.com returned nothing.
    """
    before = BEACON_CADDYFILE.read_text()
    hub_ports_before = _upstream_ports(before, HUB)
    assert "3000" in hub_ports_before, "fixture should proxy the platform to the hub"

    rc, out, after = _run_flip(tmp_path, f"{HUB} {DR} platform 3000")
    assert rc == 0, out

    # The platform moved...
    assert _upstream_ports(after, DR) == ["3000"]
    # ...and every other hub upstream stayed on the hub.
    expected_remaining = [p for p in hub_ports_before if p != "3000"]
    assert _upstream_ports(after, HUB) == expected_remaining
    assert expected_remaining, "fixture must contain hub-only services to protect"


def test_hub_only_services_are_never_flipped(tmp_path):
    """Named hub-only services must survive a platform failover."""
    _, _, after = _run_flip(tmp_path, f"{HUB} {DR} platform 3000")
    survivors = _upstream_ports(after, HUB)
    # KSO :8085, KBS :8091, Media Hub :8105, archie_comms :3002 have no
    # boston-2 counterpart. mesh :8095 and creed :8086 are flipped ONLY by
    # their own steps, after the counterpart is confirmed listening.
    for port in ("8085", "8091", "8105", "3002", "8095", "8086"):
        assert port in survivors, f"port {port} must not be flipped by 4c"


def test_substitution_never_rewrites_comments(tmp_path):
    """The blanket sed rewrote documentation as well as upstreams.

    Beacon's live Caddyfile header still reads "DR (boston-2) mesh IP:
    100.64.0.4" because a previous blanket revert rewrote its own comment. The
    matcher is anchored on `reverse_proxy http://` so this cannot recur.
    """
    before = BEACON_CADDYFILE.read_text().splitlines()
    _, _, after_text = _run_flip(tmp_path, f"{HUB} {DR} platform 3000")
    after = after_text.splitlines()

    assert len(before) == len(after)
    for old, new in zip(before, after):
        if old.strip().startswith("#"):
            assert old == new, f"comment line was rewritten: {old!r} -> {new!r}"


def test_reverting_all_dr_ports_is_idempotent(tmp_path):
    """Failback reverts every DR-capable port; ports never flipped are no-ops."""
    _, _, after_flip = _run_flip(tmp_path, f"{HUB} {DR} platform 3000")
    assert _upstream_ports(after_flip, DR) == ["3000"]

    # Reverting all three DR-capable ports restores the original file exactly,
    # even though creed/headscale were never flipped.
    workdir = tmp_path / "revert"
    workdir.mkdir()
    shutil.copy(BEACON_CADDYFILE, workdir / "orig")
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text(after_flip)

    bindir = tmp_path / "bin"
    driver = tmp_path / "revert.sh"
    driver.write_text(
        textwrap.dedent(
            f"""
            set -uo pipefail
            export PATH="{bindir}:$PATH"
            export BEACON_CADDYFILE="{caddyfile}"
            export FLEET_KEY="{tmp_path}/fake_key"
            . "{BEACON_FLIP}"
            _beacon_ssh() {{ bash -c "$1"; }}
            beacon_flip_ports {DR} {HUB} revert "${{BEACON_DR_PORTS_ALL[@]}}"
            """
        ).strip()
    )
    proc = subprocess.run(["bash", str(driver)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert caddyfile.read_text() == BEACON_CADDYFILE.read_text()


def test_invalid_config_rolls_back_and_reports(tmp_path):
    """A failed `caddy validate` must restore the file, not leave it broken.

    The old chain (`sed && validate && reload`) left a MODIFIED but invalid
    Caddyfile on disk and merely skipped the reload — a latent trap that
    detonates on the next unrelated reload.
    """
    original = BEACON_CADDYFILE.read_text()
    rc, out, after = _run_flip(tmp_path, f"{HUB} {DR} platform 3000", caddy_validate_ok=False)
    assert rc != 0
    assert after == original, "Caddyfile must be rolled back when validate fails"
    assert "ROLLED BACK" in out
