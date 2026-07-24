"""Ad-hoc dispatcher routing diagnostic (see .claude/skills/archie-dispatch-debug).

Usage:
    docker exec archie_platform bash -c '
      cd /app
      PYTHONPATH=/app:/mnt/archie_brain:/mnt/archie_brain/ai_bridge \
      python3 /mnt/archie_brain/scripts/dispatch_debug.py <capability> "<department>"'
"""

import sys

from services.agent_service import get_agent_cache, match_capability
from services.department_coordinator import get_coordinator

CAP = sys.argv[1] if len(sys.argv) > 1 else "documentation"
DEPT = sys.argv[2] if len(sys.argv) > 2 else "Documentation & Knowledge"


def main():
    cands = match_capability(CAP)
    print("match_capability(%s) -> %d skilled candidates" % (CAP, len(cands)))
    for c in cands[:10]:
        print(
            "   %-14s prof=%s state=%s dept=%s"
            % (
                c.get("name"),
                c.get("proficiency_level"),
                c.get("shift_state"),
                c.get("department"),
            )
        )

    cache = get_agent_cache()
    print("\nagent_cache size: %d" % len(cache))

    for nm in ("C.O.D.E.X.", "G.A.V.E.L.", "Amina", "E.M.B.E.R."):
        info = cache.get(nm)
        if not info:
            print("\n%-14s NOT IN CACHE" % nm)
            continue
        sk = info.get("skills")
        kind = type(sk).__name__
        if isinstance(sk, dict):
            has = CAP in sk
            sample = list(sk)[:8]
        elif isinstance(sk, (list, tuple, set)):
            has = CAP in sk
            sample = list(sk)[:8]
        else:
            has = None
            sample = sk
        print("\n%-14s dept=%s state=%s" % (nm, info.get("department"), info.get("shift_state")))
        print("   skills kind=%s n=%s has_%s=%s" % (kind, len(sk) if sk is not None else 0, CAP, has))
        print("   sample=%s" % (sample,))
        try:
            print("   score_agent -> %s" % (coord_score(nm, info),))
        except Exception as e:
            print("   score_agent ERROR: %s: %s" % (type(e).__name__, e))


def coord_score(nm, info):
    return get_coordinator().score_agent(nm, info, CAP, DEPT)


if __name__ == "__main__":
    main()
