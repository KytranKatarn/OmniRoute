---
description: Print the canonical cluster architecture (mesh + DHQ + module pattern) and run a live consciousness search to surface anything new
---

# Canonical Cluster Architecture — recall on demand

Run this any time the user mentions infra, modules, deployment, dispatch, fleet, or you're about to touch a `BRIDGE_URL`, Caddyfile, docker-compose, or anything routing-related.

Steps:

1. **Print the canonical architecture** (mesh + DHQ + VPS deploy + fleet tiers) verbatim from the `cluster-architecture` skill above.

2. **Run a live consciousness pass** to catch anything that changed since the skill was written:

```
mcp__archie__search_knowledge(query="<topic in user message>", types=["vault_note"], limit=10)
mcp__archie__search_knowledge(query="<topic in user message>", types=["mistake_learned"], limit=5)
```

3. **Surface the top hits** — title + KB id + 1-line summary per hit.

4. **State the action** you're about to take and which architectural rule(s) it follows.

5. **If anything contradicts the canonical architecture**, STOP and tell the user. Do not silently work around.

## Hard rules to recite (the user has heard these too many times)

- Mesh-only for inter-cluster. Public hostname = architectural defeat.
- Every dispatch through DHQ. No direct Ollama. No bypass.
- Same architecture for every module — don't re-ask, reference KB.
- Read before edit. `search_knowledge` BEFORE any infra change.
- 2 failures → STOP and ask. Don't spiral. Don't declare victory on a single probe.
