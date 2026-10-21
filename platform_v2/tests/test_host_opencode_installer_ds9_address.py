"""The host OpenCode installer must point at the LIVE DS9, not a retired one.

DS9's address has moved twice and the installer was left behind both times:

  * 2026-09-15 — DS9 was the Compose `omniroute` container, published on
    192.168.1.200:20128. A host process could not use 127.0.0.1:20128 (it was
    never published on loopback) and `omniroute:20128` (a compose service name)
    does not resolve on the host at all.
  * 2026-10-20 — commit cbf519c23 removed the `omniroute` service from
    docker-compose.yml and DS9 was redeployed as a HOST-NATIVE systemd service
    (deep-space-9.service, v16.3.8) listening on port 20129. The container on
    20128 survived as an orphan.

The installer's candidate list still probed only the 20128 spellings, every one of
which is dead FROM THE HOST, so it fell through to its fallback and wrote
`http://127.0.0.1:20128/v1` into the host config — a provider URL that cannot
connect. Nothing caught it: the resolution step falls back silently when nothing
answers, the written config still parses, and the verification step only re-probed
the archie-kb gateway. The breakage would surface hours later, in a different
terminal, as a model call that never completes.

These tests pin the two things that must stay true:
  1. the candidate list leads with the LIVE DS9 address, and the fallback is live;
  2. the config rewrite replaces every retired DS9 spelling, and leaves
     unrelated providers alone.

They are static checks on the script's text, not a live probe: the installer runs
on a host where DS9 may or may not be up, and a test that depends on DS9 being
running is a test that fails for the wrong reason.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install_opencode_on_host.sh"

# The live DS9 address (host-native systemd service, port 20129).
LIVE_DS9_PORT = "20129"
# Ports that have served DS9 at some point. Reaching any of them from the host
# today is wrong: 20128 was never published on loopback, and the container that
# still owns the published 192.168.1.200:20128 is an orphan.
RETIRED_DS9_PORTS = ("20128",)


def _script() -> str:
    assert SCRIPT.exists(), f"host installer not found at {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def test_candidate_list_leads_with_the_live_ds9_port():
    """The first candidate probed must be the live DS9, not a retired port."""
    src = _script()
    m = re.search(r"^OR_CANDIDATES=\"([^\"]+)\"", src, re.M)
    assert m, "OR_CANDIDATES list not found in the host installer"
    candidates = m.group(1).split()
    assert candidates, "OR_CANDIDATES is empty"

    first = candidates[0]
    assert f":{LIVE_DS9_PORT}" in first, (
        f"first DS9 candidate is {first!r}; it must lead with the live port "
        f"{LIVE_DS9_PORT} (the host-native systemd gateway)"
    )
    for port in RETIRED_DS9_PORTS:
        assert f":{port}" not in first, (
            f"first DS9 candidate {first!r} uses the retired port {port}; " "it is dead from the host"
        )


def test_fallback_base_url_is_live():
    """When nothing answers, the fallback must still be a reachable address."""
    src = _script()
    m = re.search(r'\[ -n "\$OR_URL" \] \|\| OR_URL="([^"]+)"', src)
    assert m, "OR_URL fallback not found in the host installer"
    fallback = m.group(1)
    assert f":{LIVE_DS9_PORT}" in fallback, (
        f"OR_URL fallback is {fallback!r}; it must point at the live DS9 port " f"{LIVE_DS9_PORT}, not a retired one"
    )
    for port in RETIRED_DS9_PORTS:
        assert f":{port}" not in fallback, f"OR_URL fallback {fallback!r} uses the retired port {port}"


def test_rewrite_covers_every_retired_ds9_spelling():
    """The config rewrite must catch the compose service name AND the retired port.

    The old rewrite matched only `http://omniroute:`. A config carrying a host
    address for the removed container gateway (127.0.0.1:20128, or the published
    192.168.1.200:20128) was left pointing at a dead endpoint.
    """
    src = _script()
    m = re.search(r"STALE_DS9_HOSTS\s*=\s*\(([^)]*)\)", src, re.S)
    assert m, "STALE_DS9_HOSTS tuple not found in the host installer"
    stale = m.group(1)

    assert "http://omniroute:" in stale, "STALE_DS9_HOSTS must still match the compose service name"
    for port in RETIRED_DS9_PORTS:
        assert f":{port}" in stale, (
            f"STALE_DS9_HOSTS must match the retired DS9 port {port} on the host "
            "addresses too, not only the compose service name"
        )


def test_rewrite_leaves_unrelated_providers_alone():
    """The rewrite must be anchored on the DS9 hosts, not a blanket replacement."""
    src = _script()
    block = re.search(r"STALE_DS9_HOSTS\s*=\s*\(.*?\n\)", src, re.S)
    assert block, "STALE_DS9_HOSTS block not found"
    # A blanket `opts["baseURL"] = ...` with no host test would rewrite the
    # Ollama and mesh providers too.
    assert "any(base.startswith(stale) for stale in STALE_DS9_HOSTS)" in src, (
        "the provider rewrite must be guarded by a host match, not applied " "unconditionally"
    )


def test_installer_verifies_the_ds9_endpoint_after_writing():
    """The verification step must re-probe DS9, not just the archie-kb gateway.

    This is the check whose absence let a dead provider URL ship: the config
    parses, the KB gateway answers, and the install reports success over a
    provider URL that cannot connect.
    """
    src = _script()
    verify_section = src.split('step "Verifying"', 1)
    assert len(verify_section) == 2, "Verifying step not found in the host installer"
    verify = verify_section[1]

    assert (
        'probe_http "$OR_BASE/models"' in verify
    ), "the Verifying step must probe the DS9 endpoint it wrote into the config"
    assert (
        "fail=1" in verify.split('probe_http "$OR_BASE/models"', 1)[1][:600]
    ), "a DS9 probe failure must set fail=1, not just print a warning"


def test_installer_documents_the_address_change():
    """The address history must be recorded, or the next mover repeats this."""
    src = _script()
    assert "cbf519c23" in src, (
        "the installer should cite the commit that moved DS9 off the Compose "
        "container, so the reason for the candidate list is discoverable"
    )
    assert LIVE_DS9_PORT in src, "the live DS9 port should be named in the installer"
