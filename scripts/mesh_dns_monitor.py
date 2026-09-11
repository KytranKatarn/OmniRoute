#!/usr/bin/env python3
"""Assert the mesh's DNS actually works FROM A MESH CLIENT (#6701).

Written after 2026-09-11, where headscale's `dns.nameservers.global` led with
192.168.1.200 — a LAN address unreachable from any mesh client not also on the home
LAN. Those clients silently fell through to 1.1.1.1, got the PUBLIC ip for the coder
lanes, left the tunnel, and were refused by the mesh gate while appearing fully on
the mesh. Full write-up: KB mistake #315245.

TWO THINGS MADE IT INVISIBLE, and this script exists to remove both:

  1. IT CANNOT BE SEEN FROM THE HUB. On the hub, 192.168.1.200 resolves trivially.
     Every check run there passes while every phone in the field fails. So the real
     probe runs over SSH on an OFF-LAN MESH NODE (outpost-us), and refuses to
     certify anything when it only managed to test locally.

  2. THE FAILURE IS SILENT. An unreachable nameserver raises no error anyone sees —
     it promotes the next entry, which may answer the same name differently. So this
     checks EVERY nameserver in the list, not just that resolution "works".

Exit 0 = healthy. Exit 1 = a real finding. Exit 2 = could not determine (never
reported as healthy — an UNKNOWN is not a pass).
"""

import json
import socket
import struct
import subprocess
import sys

# Citadel's mesh address — where the lane hostnames must resolve for a mesh client.
EXPECTED = "100.64.0.10"

LANE_NAMES = [
    "claude", "codex", "tui", "opencode",
    "terminal", "codex-tty", "tui-tty", "opencode-tty",
]

# The off-LAN mesh vantage. outpost-us is the only remaining node that is on the
# mesh and NOT on the home LAN, which is exactly the condition under test.
VANTAGE = "kytran@100.64.0.2"

HEADSCALE_CONFIG = "/mnt/archie_brain/headscale/config.yaml"


def _dns_query(server: str, name: str, timeout: float = 4.0) -> str:
    """Minimal A-record query. Deliberately not using the system resolver — the
    question is what a SPECIFIC server answers, and the system resolver would hide
    exactly the substitution this exists to catch."""
    pkt = b"\xab\xcd\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    for part in name.split("."):
        pkt += bytes([len(part)]) + part.encode()
    pkt += b"\x00\x00\x01\x00\x01"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(pkt, (server, 53))
        data, _ = s.recvfrom(512)
    finally:
        s.close()
    if struct.unpack("!H", data[6:8])[0] == 0:
        return ""
    i = 12
    while data[i]:
        i += data[i] + 1
    i += 5 + 2 + 8 + 2
    return socket.inet_ntoa(data[i:i + 4])


def _configured_nameservers():
    """Read the nameserver list from headscale's own config — never from memory.
    A monitor that hardcodes what it expects to find cannot report drift."""
    try:
        import yaml
    except ImportError:
        return None
    try:
        with open(HEADSCALE_CONFIG) as fh:
            cfg = yaml.safe_load(fh)
        return list(cfg["dns"]["nameservers"]["global"])
    except Exception:
        return None


def _remote(script: str):
    """Run a probe on the off-LAN vantage. Returns (ok, parsed_json_or_error)."""
    # ⚠️ Feed the script on STDIN, never as `python3 -c <script>`. ssh joins argv
    # with spaces and the REMOTE SHELL re-parses the result, so a multi-line script
    # arrives shredded — measured: "Argument expected for the -c option" followed by
    # bash trying to execute the Python. `python3 -` reads the program from stdin and
    # is immune to that.
    try:
        r = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", VANTAGE,
             "python3", "-"],
            input=script, capture_output=True, text=True, timeout=90,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "ssh failed").strip()[:300]
    line = next((l for l in r.stdout.splitlines() if l.startswith("{")), "")
    if not line:
        return False, "vantage returned no JSON"
    try:
        return True, json.loads(line)
    except Exception as exc:
        return False, f"unparseable: {exc}"


REMOTE_PROBE = r'''
import socket, struct, json
def q(server, name, timeout=4.0):
    pkt=b"\xab\xcd\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    for p in name.split("."): pkt+=bytes([len(p)])+p.encode()
    pkt+=b"\x00\x00\x01\x00\x01"
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(timeout)
    try:
        s.sendto(pkt,(server,53)); d,_=s.recvfrom(512)
    finally: s.close()
    if struct.unpack("!H",d[6:8])[0]==0: return ""
    i=12
    while d[i]: i+=d[i]+1
    i+=5+2+8+2
    return socket.inet_ntoa(d[i:i+4])

NS = __NS__
NAMES = __NAMES__
out = {"nameservers": {}, "lanes": {}}
for ns in NS:
    try: out["nameservers"][ns] = {"reachable": True, "answer": q(ns, NAMES[0] + ".kytranempowerment.com")}
    except Exception as e: out["nameservers"][ns] = {"reachable": False, "error": type(e).__name__}
first = NS[0] if NS else None
for n in NAMES:
    fq = n + ".kytranempowerment.com"
    try: out["lanes"][n] = q(first, fq) if first else ""
    except Exception as e: out["lanes"][n] = "ERR:" + type(e).__name__
print(json.dumps(out))
'''


def main() -> int:
    findings, notes = [], []

    ns_list = _configured_nameservers()
    if ns_list is None:
        print("UNKNOWN: could not read headscale nameservers from config")
        return 2
    notes.append(f"configured nameservers: {ns_list}")

    script = (REMOTE_PROBE
              .replace("__NS__", repr(ns_list))
              .replace("__NAMES__", repr(LANE_NAMES)))
    ok, result = _remote(script)
    if not ok:
        # ⚠️ NOT a pass. The whole point is that the hub cannot answer this question,
        # so failing to reach the vantage means the check did not happen.
        print(f"UNKNOWN: off-LAN mesh vantage {VANTAGE} unreachable — {result}")
        print("         This check is meaningless from the hub; not reporting healthy.")
        return 2

    # 1. EVERY nameserver must be reachable from a mesh client. An unreachable one
    #    does not fail loudly — it promotes the next, which may answer differently.
    for ns, info in result["nameservers"].items():
        if not info.get("reachable"):
            findings.append(
                f"nameserver {ns} is UNREACHABLE from the mesh ({info.get('error')}). "
                f"Clients silently fall through to the next entry, which may answer "
                f"the lane hostnames with a PUBLIC address."
            )

    # 2. The PRIMARY nameserver must answer the lane names with Citadel's MESH ip.
    for name, answer in result["lanes"].items():
        if answer != EXPECTED:
            findings.append(
                f"{name}.kytranempowerment.com resolves to {answer or '(nothing)'} "
                f"from the mesh, expected {EXPECTED}. A client following that answer "
                f"leaves the tunnel and is refused by the mesh gate."
            )

    for n in notes:
        print(f"  {n}")
    for ns, info in result["nameservers"].items():
        state = "reachable" if info.get("reachable") else f"UNREACHABLE ({info.get('error')})"
        print(f"  nameserver {ns:16} {state}  answer={info.get('answer', '-')}")

    if findings:
        print(f"\nFINDINGS ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1

    print(f"\nOK: all {len(ns_list)} nameservers reachable from {VANTAGE}; "
          f"all {len(LANE_NAMES)} lane names -> {EXPECTED}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
