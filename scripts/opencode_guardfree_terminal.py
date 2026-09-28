"""Build and run a guard-free opencode terminal, safely.

This file is the stable entry point and nothing more: it wires the CLI in
main() to the package it lives beside (scripts/opencode_lane/). The design
narrative and the reason the script exists at all are in that package's
__init__.py and in the spec
(docs/superpowers/specs/2026-09-27-opencode-guard-free-terminal.md).

The moved names are re-exported here on purpose: the tracked lane docs, the
handover notes and the test harness all reach them through this module, and a
split that quietly moved a name would break callers that were never part of the
refactor.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import shlex
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from opencode_lane.common import (BASE_IMAGE, DEFAULT_NAME, DEFAULT_PORT, DOCKERFILE, GF_IMAGE,
                                  HOST_CLAUDE_MOUNT, HOST_CLAUDE_SETTINGS, NETWORK,
                                  PROTECTED, SECRETS, die, run, say)
from opencode_lane.container import (run_container, stage_envfile, teardown, wait_healthy)
from opencode_lane.docs import DOCS_DIRS, check_lane_instructions, doc_files, lane_flavor
from opencode_lane.docs_install import install_lane_docs, plan_doc_install
from opencode_lane.commands import plan, repair_docs
from opencode_lane.guards import (guard_base_image, guard_name_free, guard_not_protected,
                                  guard_override_known, guard_port_free, host_file_exists)
from opencode_lane.image import build_image, verify_image
from opencode_lane.seed import remove_container, seed_clone, seed_config


def main():
    ap = argparse.ArgumentParser(
        description="Build and run a guard-free opencode terminal (alongside the others).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="build the image and run the terminal (default: dry run)")
    ap.add_argument("--verify", action="store_true",
                    help="only verify that the built image is guard-free")
    ap.add_argument("--build-only", action="store_true",
                    help="build and verify the image, but start no container")
    ap.add_argument("--teardown", action="store_true",
                    help="remove the guard-free terminal and its volumes")
    ap.add_argument("--name", default=DEFAULT_NAME, help="container name")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="host port for ttyd")
    ap.add_argument("--from-instance", default=PROTECTED[0],
                    help="container to copy config and the omniroute key from")
    ap.add_argument("--replace", action="store_true",
                    help="recreate --name if it already exists")
    ap.add_argument("--lane-name", default=None,
                    help="LANE_NAME for the container (default: 'opencode' for the "
                         "canonical lane, else 'opencode-guardfree')")
    ap.add_argument("--override-protected", metavar="NAME", default=None,
                    help="permit recreating a protected instance; must repeat NAME "
                         "exactly (e.g. --override-protected archie_opencode_terminal)")
    ap.add_argument("--repair-docs", metavar="NAME", default=None,
                    help="re-apply the tracked instruction set to an EXISTING lane. "
                         "Install-only: creates no container, replaces no image, "
                         "deletes no volume, and never overwrites a file that was "
                         "edited after seeding.")
    args = ap.parse_args()

    if args.repair_docs:
        return repair_docs(args.repair_docs, args.from_instance)

    guard_not_protected(args.name, args.override_protected)
    guard_override_known([args.override_protected])

    if args.teardown:
        return teardown(args.name)

    if args.verify:
        guard_base_image()
        return 0 if verify_image(GF_IMAGE) else 2

    lane_name = args.lane_name or (
        "opencode" if args.name == PROTECTED[0] else "opencode-guardfree")

    if args.build_only:
        guard_base_image()
        build_image()
        verify_image(GF_IMAGE)
        say("\nDONE — image {} built and verified guard-free. No container started.".format(GF_IMAGE))
        return 0

    if not args.apply:
        return plan(args.name, args.port, args.from_instance, args.replace)

    # ---- apply ----
    guard_base_image()
    build_image()
    verify_image(GF_IMAGE)          # fail-closed: never run an unverified image

    name, port = run_container(args.name, args.port, args.from_instance, args.replace, lane_name)
    if not wait_healthy(name):
        say("FAILED to come up healthy — tearing '{}' down again.".format(name))
        teardown(name)
        return 3

    seed_config(name, args.from_instance)
    wait_healthy(name)
    install_lane_docs(name, args.from_instance)
    check_lane_instructions(name, args.from_instance)

    say("\nDONE")
    say("  guard-free terminal : http://127.0.0.1:{}".format(port))
    say("  container           : {}".format(name))
    say("  rollback            : {} --teardown".format(shlex.quote(sys.argv[0])))
    for p in PROTECTED:
        st = (run(["docker", "inspect", p, "--format", "{{.State.Status}}"], check=False).stdout or "?").strip()
        say("  untouched           : {} ({})".format(p, st))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
