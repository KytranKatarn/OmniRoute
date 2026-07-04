#!/usr/bin/env python3
"""Generate agent portraits — run from host or inside Docker."""

import sys

sys.path.insert(0, "/mnt/archie_brain")

from ai_bridge.portrait_generator import generate_all_portraits

if __name__ == "__main__":
    force = "--force" in sys.argv
    results = generate_all_portraits(force=force)
    print(
        f"Success: {len(results['success'])} | "
        f"Failed: {len(results['failed'])} | "
        f"Skipped: {len(results['skipped'])}"
    )
    if results["failed"]:
        print(f"Failed agents: {', '.join(results['failed'])}")
