#!/usr/bin/env python3
"""Write durable knowledge cards into `knowledge_base`.

WHY THIS SCRIPT EXISTS
----------------------
DS9 acceptance criterion 6 -- "knowledge captured, so the next session finds this by search" --
had failed twice. Both times the cause was the same and it is not a discipline problem: the
knowledge MCP tools are READ-ONLY. There is no create/update tool, so an agent following the
tools could not write a KB entry at all, and the criterion was unreachable no matter how careful
the session was.

This is the missing sanctioned path. It is a thin, well-commented wrapper over the writer the
platform already has -- `save_knowledge_card()` in ai_bridge/knowledge_cards.py -- not a new
ingestion route. Writing straight to the table instead would land rows that never enter semantic
search, which is the exact failure being fixed.

TWO NON-OBVIOUS REQUIREMENTS, both learned the hard way
-------------------------------------------------------
1. **The embedding is not optional.** `search_knowledge` is semantic. A card written without a
   768-dim vector is reachable by full-text search only, so it would satisfy "a row exists" and
   still fail "the next session finds this".
2. **Ollama is on the HOST, not in the container.** From inside the container `localhost:11434`
   is the container and the connection is refused; the LAN address, `host.docker.internal` and
   the docker bridge gateway are probed in turn.

Run:
    docker exec -i archie_platform python3 - < platform_v2/scripts/write_knowledge_cards.py

Upserts on `title`, so re-running refreshes a card in place rather than duplicating it.

Verified 2026-10-06: three DS9/OmniRoute cards written and each returned as the top hit for its
subject with ~1.36 relevance.

Why this route and not a direct INSERT: `save_knowledge_card()` in ai_bridge/knowledge_cards.py is
the sanctioned writer — it upserts on title, builds the metadata/ai_analysis JSON the reader
expects, and sets `embedding_generated_at`. A hand-rolled INSERT would land a row that never
appears in semantic search, which is the exact failure C6 is complaining about.

Embedding is not optional. `search_knowledge` is semantic, so a card without a 768-dim vector is
invisible to it even though `search_knowledge_brief` (FTS) can still find it.

Cards carry only what was expensive to learn and cheap to get wrong. Anything derivable from the
code or git history is deliberately left out — the KB is for facts a future session would otherwise
re-derive or assume.
"""
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

EMBED_MODEL = "arctic-embed-cpu:latest"

# Ollama runs on the HOST. From inside the container, localhost is the container, so the
# original `http://localhost:11434` fails with Connection refused. Candidates are probed in
# order and the first that answers /api/tags wins.
EMBED_HOSTS = [
    "http://192.168.1.200:11434",  # host LAN address
    "http://host.docker.internal:11434",
    "http://172.17.0.1:11434",  # default docker bridge
    "http://localhost:11434",  # if this ever runs ON the host
]


def _resolve_embed_base() -> str:
    for base in EMBED_HOSTS:
        try:
            with urllib.request.urlopen(base + "/api/tags", timeout=8):
                return base
        except Exception:
            continue
    raise RuntimeError("no reachable Ollama endpoint; tried %s" % ", ".join(EMBED_HOSTS))


def embed(text: str):
    body = json.dumps({"model": EMBED_MODEL, "input": text}).encode()
    req = urllib.request.Request(
        _resolve_embed_base() + "/api/embed",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    vec = data.get("embeddings", [None])[0]
    if not vec or len(vec) != 768:
        raise RuntimeError(f"expected a 768-dim embedding, got {len(vec) if vec else None}")
    return vec


CARDS = [
    {
        "title": "OmniRoute gateway — addressing, dynamic aliases, and why five contractor rows fail differently",
        "card_type": "reference",
        "summary": (
            "OmniRoute is an OpenAI-compatible gateway. Reached at http://omniroute:20128/v1 from "
            "inside the Docker network (container DNS); host processes must use "
            "http://192.168.1.200:20128/v1. It serves ~540 models. Its auto/* aliases are DYNAMIC "
            "routers: the alias always exists, but the upstream model it selects changes, so a "
            "failure is a statement about this moment's route, never about the configuration."
        ),
        "detailed": (
            "ADDRESSING\n"
            "  container -> http://omniroute:20128/v1   (Docker DNS)\n"
            "  host      -> http://192.168.1.200:20128/v1\n"
            "  Earlier `~/.config/opencode/opencode.json` had baseURL http://127.0.0.1:20128/v1,\n"
            "  which is wrong in BOTH contexts: 127.0.0.1 inside the container is the container.\n\n"
            "THE GATEWAY IS UP\n"
            "  GET /v1/models -> HTTP 200, 540 models (verified 2026-10-06).\n\n"
            "WHY THE FIVE OMNIROUTE CONTRACTOR ROWS ALL FAIL, AND DIFFERENTLY\n"
            "  omniroute_coding        auto/coding      -> 402 requires an opencode API key\n"
            "  omniroute_coding_free   auto/coding:free -> 402 requires an opencode API key\n"
            "  omniroute_best_free     auto/best-free   -> 400 Model is unavailable\n"
            "  omniroute_reasoning     auto/reasoning   -> 400 Model is unavailable\n"
            "  omniroute               (client-bound)   -> 403 free tier only usable inside OpenCode\n"
            "  The first two were mislabelled free_tier and are now `paid`. The 400s are upstream\n"
            "  models withdrawn; they may resolve again. The 403 is a CLIENT restriction, not a\n"
            "  cost fact — that row really is free.\n\n"
            "THE TRAP THAT COST THE MOST TIME\n"
            "  Treating these rows as 'dead, models retired' and proposing to delete them. The\n"
            "  aliases all exist. Retiring a row whose alias is valid because the model behind it\n"
            "  is unavailable this afternoon is the same category error as deleting a provider\n"
            "  because it is merely down. Verify with GET /v1/models before proposing removal.\n\n"
            "COST CLASS IS OPERATOR-ASSIGNED, NEVER INFERRED\n"
            "  classify_provider_class() deliberately CANNOT return `paid`. Its docstring records\n"
            '  that it used to end in `return "paid" if is_cloud_proxy else "free_tier"`, which\n'
            "  asserted cost from a flag describing how a provider is REACHED, stamping free_tier\n"
            "  on 13 of 18 unmeasured contractors. A probe sees a 402; it cannot prove the price.\n"
            "  Use a migration to assign `paid`, guarded on the previous value."
        ),
        "topics": ["omniroute", "ds9", "contractor", "gateway", "routing", "cost-class", "paid"],
        "technologies": ["ollama", "openai-compatible-api", "postgresql"],
        "difficulty": "intermediate",
        "confidence": 0.95,
        "source_type": "platform_docs",
        "source_ref": "docs/superpowers/specs/2026-10-06-ds9-criterion-4-rename-scope.md",
    },
    {
        "title": "DS9 contractor health — the three probe cadences, the backoff policy, and absent-vs-zero",
        "card_type": "concept",
        "summary": (
            "Contractor health uses three deliberately distinct probe cadences, and a status-based "
            "backoff that exists mostly to be polite rather than to save money. The governing rule "
            "throughout is absent-vs-zero: a value that was not measured must never render as a "
            "measured value, in the badge, the response payload, or a row's timestamp."
        ),
        "detailed": (
            "THE THREE CADENCES (migration 487's comment is the spec)\n"
            "  health   15 min  one 1-token completion — does it answer at all\n"
            "  latency  hourly   a 32-token completion — includes decoding, not just first byte\n"
            "  full     daily     enumerates models AND verifies with a completion\n"
            "  `full` existed as a second copy of `health` for a while: 30 wasted requests/day, and\n"
            "  a 'latency' number that was really time-to-first-byte. Fixing which rows COUNT was\n"
            "  not enough; the remaining rows had to be worth counting.\n\n"
            "  In `full` the ORDER IS THE DESIGN. The completion decides the verdict; the model\n"
            "  list only annotates. All five OmniRoute rows return 200 on /v1/models while three\n"
            "  403 or 502 a completion — a `full` that trusted enumeration would rank the dead\n"
            "  rows first. Enumeration NEVER writes to contractor_providers: drift is reported,\n"
            "  not applied, because a probe rewriting the model list changes what dispatch routes to.\n\n"
            "THE BACKOFF POLICY (not about money — a 1-token probe costs a fraction of a cent)\n"
            "  ok, unreachable             -> every cycle\n"
            "  error, rate_limited         -> 60 min\n"
            "  no_key, auth_error, unsupported -> 120 min\n"
            "  rate_limited backing off is CORRECTNESS, not thrift: a 429 means the upstream asked\n"
            "  us to slow down, and hammering a free tier is how access gets withdrawn.\n"
            "  120 not 360 for config failures because there is no manual probe endpoint — that\n"
            "  window IS the operator's refresh, and 6h reads as 'my fix did not work'.\n\n"
            "A SKIP WRITES NO ROW. Deliberately: the row's created_at is what the tab renders as\n"
            "'last checked', so a skipped provider shows an OLD timestamp rather than a\n"
            "fresh-looking stale reading. If the lookup feeding the decision fails it returns {},\n"
            "so everything is probed — failing toward less traffic is the dangerous direction.\n\n"
            "ABSENT vs ZERO, in force everywhere\n"
            "  health_status === null renders UNKNOWN, never 0ms. A provider with NULL\n"
            "  provider_class cannot be enabled at all: the toggle returns HTTP 409.\n"
            "  The switch-history endpoint returns degraded:true when its read fails, because\n"
            "  otherwise 'could not read' and 'never switched' are byte-identical payloads and the\n"
            "  UI confidently prints 'no changes recorded' about the thing you opened it to find.\n\n"
            "TWO SWITCHES, NOT ONE\n"
            "  is_active    = CONFIGURED (has credentials, is set up)\n"
            "  dispatchable = ROUTE HERE (may send traffic and spend)\n"
            "  Media cloud generation ignored `dispatchable` entirely until #3675: the Media\n"
            "  Studio path checked the master toggle, the capability allowlist and the weekly\n"
            "  budget, then walked past the per-provider switch. A provider with NO contractor row\n"
            "  is deliberately not gated (local_tts is local and free)."
        ),
        "topics": ["ds9", "contractor", "health", "probe", "cadence", "backoff", "dispatchable"],
        "technologies": ["postgresql", "flask", "psycopg2"],
        "difficulty": "advanced",
        "confidence": 0.95,
        "source_type": "platform_docs",
        "source_ref": "platform_v2/services/contractor_health_service.py",
    },
    {
        "title": "Migration hazard — the node image replays all 413 migrations on every boot",
        "card_type": "problem-solution",
        "summary": (
            "platform_v2/entrypoint.node.sh re-applies every repository migration on every boot of "
            "a node image, because its applied-check reads a column that does not exist and its "
            "error fallback is '0', which the shell reads as 'not applied'. The hub is unaffected. "
            "Open as Dev HQ task #7118; it needs the codex lane or the owner because the fix is in "
            "deploy/infra."
        ),
        "detailed": (
            "THE CHAIN (all verified against the live hub, 2026-10-06)\n"
            "  1. Dockerfile.node:19 COPY database/migrations/ -> /app/db_init/migrations/\n"
            "     so all 413 repo migrations sit where the entrypoint looks.\n"
            "  2. The entrypoint creates schema_migrations (id, filename, applied_at) — but the\n"
            "     table ALREADY exists as (version, description, applied_at), and CREATE TABLE IF\n"
            "     NOT EXISTS silently no-ops. The `filename` column never appears.\n"
            "  3. Its applied-check `SELECT COUNT(*) ... WHERE filename=...` raises\n"
            '     ERROR: column "filename" does not exist.\n'
            '  4. That query is wrapped `2>/dev/null || echo "0"`, so a FAILURE becomes the value\n'
            "     0 — which the script reads as 'not applied'.\n"
            "  5. psql -f therefore runs all 413, every boot; per-file failures are swallowed by\n"
            "     `|| echo WARNING`.\n"
            "  6. The recorder INSERT fails identically, so nothing is ever recorded.\n\n"
            "  Step 4 is the defect: a query ERROR being interpreted as a VERDICT. It explains BOTH\n"
            "  symptoms — the empty ledger and the replay. They are one bug, not two.\n\n"
            "BLAST RADIUS\n"
            "  HUB SAFE. platform_v2/Dockerfile has zero db_init copies; only Dockerfile.node uses\n"
            "  this entrypoint, and the hub has no /app/db_init so the loop iterates zero times.\n"
            "  NODES NOT SAFE. Any node boot replays 413 files. Non-idempotent DDL fails silently;\n"
            "  5 of the migrations contain DROP/TRUNCATE and those statements would execute.\n\n"
            "WHY ADDING A `filename` COLUMN IS NOT THE FIX\n"
            "  It makes the loop function — and 413 files replaying per boot is still wrong, because\n"
            "  the runner assumes idempotent migrations and most of these are not idempotent. The\n"
            "  real question is whether a node should run migrations at all, or receive a schema\n"
            "  dump and never carry a runner.\n\n"
            "RELATED HYGIENE (do not fix blindly)\n"
            "  THREE migration trees: database/migrations (413), platform_v2/migrations (35),\n"
            "  platform_v2/database/migrations (80). Only 16 of 413 ever recorded themselves;\n"
            "  recording is opt-in per file. Version prefixes COLLIDE — 007, 031, 050, 051, 052,\n"
            "  053 each have 2+ files — and schema_migrations.version is the PRIMARY KEY, so any\n"
            "  backfill from filenames would silently DROP rows."
        ),
        "topics": ["migration", "infrastructure", "hazard", "entrypoint", "schema", "node-image"],
        "technologies": ["postgresql", "docker", "bash"],
        "difficulty": "advanced",
        "confidence": 0.95,
        "source_type": "platform_docs",
        "source_ref": "Dev HQ task #7118",
    },
]


def main() -> int:
    # knowledge_cards.py does a FLAT `from db import get_db`, which only resolves when
    # ai_bridge/ itself is on the path — not when the package is imported as `ai_bridge.*`.
    # That is why this script exists rather than a one-liner.
    for root in ("/mnt/archie_brain", "/app"):
        if pathlib.Path(root, "ai_bridge", "db.py").exists():
            sys.path.insert(0, root)
            sys.path.insert(0, os.path.join(root, "ai_bridge"))
            break
    from ai_bridge.knowledge_analyzer import KnowledgeCard
    from ai_bridge.knowledge_cards import save_knowledge_card

    # Embed the text a future session would plausibly search for: title + summary + topics.
    for i, spec in enumerate(CARDS, 1):
        card = KnowledgeCard(
            title=spec["title"],
            card_type=spec["card_type"],
            summary=spec["summary"],
            detailed=spec["detailed"],
            code_examples=[],
            topics=spec["topics"],
            technologies=spec["technologies"],
            difficulty=spec["difficulty"],
            confidence=spec["confidence"],
            source_type=spec["source_type"],
            source_ref=spec["source_ref"],
        )
        embed_text = " ".join([card.title, card.summary, " ".join(card.topics)])
        vec = embed(embed_text)
        card_id = save_knowledge_card(card, vec)
        print(f"  [{i}] {'SAVED id=%s' % card_id if card_id else 'FAILED'}  {card.title[:62]}")
        if not card_id:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
