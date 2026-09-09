"""ONE answer to "did these tokens leave the cluster?" (owner requirement 2026-09-09).

WHY THIS MODULE EXISTS

The Consciousness → Token Economy tab had TWO definitions of "cloud", and they
disagreed on live rows:

  * the Cloud Impact totals / tokens-over-time series keyed on ``provider``
    (a hardcoded tuple of eleven provider names plus an ``ILIKE '%cloud%'``
    heuristic);
  * the "Where Every Token Goes" buckets panel keyed on ``worker_type='contract'``.

Measured over 90 days, the rows the two rules disagreed on:

    provider      worker_type   runs   tokens   totals said   buckets said
    ollama_cloud  internal       665  637,900   external      agent (local)
    ollama        contract         4   11,093   local         cloud
    groq          internal         1      116   external      agent (local)

``ollama_cloud`` is Ollama's hosted inference — 637,900 tokens that left the
cluster and were being drawn in the *agent-local* bucket, on the very panel
built to make token accounting honest (#2188/#2189). An accounting panel that
disagrees with the panel above it certifies nothing.

THE RULE

An allowlist of providers that are PROVABLY LOCAL; everything else is cloud.
That direction is deliberate: a provider registered later (``omniroute``,
whatever comes after it) is counted as cloud the moment it produces a row,
rather than being silently local until someone remembers to extend a tuple.
For accounting, over-counting cloud is the recoverable error; under-counting it
is the one the owner asked us never to make.

⚠️ The cost of that direction is that EVERY local write site must be on the
list. The first cut of this module missed three and flipped them to cloud —
``ollama_vision`` (the local moondream path, dispatcher:4331 /
archie_bridge:1291 / portrait_service:1121), ``comfyui_deferred``
(dispatcher:3651), and the prefix-shaped ``starship:<node_id>`` fleet-routing
tag (dispatcher:4535), which an exact-match tuple can never admit. Caught by
adversarial review before merge. Before adding a provider string anywhere,
grep every ``provider=`` / ``"provider":`` write site.

Precedence inside the CASE, in order:

  1. NULL provider → local BY POLICY: nothing was recorded leaving the cluster.
     In the current 90 days these are all 0-token orchestration markers; over
     the 365-day window they also include ~868k ESTIMATED backfill tokens from
     agent_loop (May–Jun 2026), which the estimated-token exclusion below
     handles separately. Do not read this branch as "NULL means zero tokens".
  2. ``NEVER_DISPATCHED`` placeholders → local. ``cloud_pending`` is written by
     the approval gate BEFORE any cloud call is made; it is a bookkeeping row.
  3. Hosted-model tag on the MODEL (``:cloud`` / ``-cloud``) → external. This
     must run BEFORE the local allowlist because Ollama proxies its hosted
     models through the local daemon — the provider column can read
     ``ollama`` for a request that was served in Ollama's cloud. Ollama's
     catalogue uses both spellings (``qwen3-coder-next:cloud``,
     ``gpt-oss:120b-cloud``); only ``:cloud`` is pulled here today.
  4. provider in ``LOCAL_PROVIDERS`` → local.
  5. provider starts with a ``LOCAL_PREFIXES`` entry → local.
  6. anything else → external. (A ``position('cloud' in provider)`` branch
     sits just before this ELSE as defence-in-depth; it is REDUNDANT with the
     ELSE today and exists only so a future local provider whose name contains
     "cloud" fails loud in the truth table rather than silently local.)

``worker_type`` is not consulted at all. It describes the AGENT (ai / internal /
contract), not where the inference ran: a contract-typed agent can be served by
the hub's own Ollama (the 4 ``ollama/contract`` rows above), and an internal
agent can be served by a cloud provider. Provider is the truth.

NO ``%`` IN THE SQL, deliberately. The two consumers pass psycopg2 params, where a
literal ``%`` must be written ``%%``; a future consumer without params would then
match the literal string ``%cloud%``. ``position()`` / ``left()`` / ``right()``
sidestep the escaping question entirely, so the same string is correct in both
contexts.

ESTIMATED TOKENS are a separate axis from cloud/local. ``ESTIMATED_SQL`` is the
one definition of "this row's token count is a backfill estimate, not a
measurement"; BOTH Token Economy panels must exclude those rows from the live
cloud/local split (and the buckets panel shows them as their own bucket), or the
ALL-range numbers diverge — measured 10,102,978 tokens apart before this was
shared.

Consumers: ``tools/consciousness/code_health_routes.py`` (both endpoints).
``services/creed_accounting_audit.py`` still uses ``worker_type='contract'`` for
the carbon exclusion — a separate ledger with a separate question, tracked as
#6656; adopt this helper there only after checking what "cloud" means for CO2
attribution.
"""

from __future__ import annotations

# Providers whose inference demonstrably ran on our own hardware. Extend this
# ONLY for a provider that is genuinely local; never add a cloud provider here
# to "fix" a number. Every entry is a real write-site value — see the docstring.
LOCAL_PROVIDERS: tuple[str, ...] = (
    "ollama",  # the hub's host Ollama service
    "fleet_node",  # a Starship / outpost Ollama over the mesh
    "local",  # legacy marker rows
    "llamacpp",  # archie_llamacpp container
    "comfyui",  # local image generation
    "ollama_vision",  # local moondream / vision path (dispatcher:4331, archie_bridge:1291)
    "comfyui_deferred",  # local image gen deferred on capacity (dispatcher:3651)
)

# Provider PREFIXES that denote local hardware. The dispatcher tags fleet-node
# routing as provider=f"starship:{node_id}" (dispatcher:4535) — one value per
# node, so it cannot live in an exact-match tuple.
LOCAL_PREFIXES: tuple[str, ...] = ("starship:",)

# Bookkeeping rows written BEFORE any call is made. Nothing left the cluster.
NEVER_DISPATCHED: tuple[str, ...] = ("cloud_pending",)  # approval-gated placeholder (dispatcher:3565)

# Ollama's hosted-model tag, both spellings the catalogue uses.
CLOUD_MODEL_SUFFIXES: tuple[str, ...] = (":cloud", "-cloud")

# ONE definition of "this token count is an estimate, not a measurement".
# COALESCE so NULL metadata reads as 'not estimated' — NOT(NULL) = NULL would
# silently drop every real row from a NOT-{est} sum.
ESTIMATED_SQL = "(COALESCE(request_metadata->>'token_source','') IN ('estimated', 'estimated_historical'))"


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def cloud_classifier_sql(provider_col: str = "provider", model_col: str = "model_used") -> str:
    """Return a SQL CASE expression yielding ``'external'`` or ``'local'``.

    Drop it straight into a SELECT list or wrap it: ``({expr})='external'``.
    Safe to use with or without psycopg2 parameters (no ``%`` inside).
    Precedence is documented at module level; change it in :func:`is_cloud_row` too.
    """
    p = f"lower({provider_col})"
    m = f"lower(COALESCE({model_col}, ''))"
    suffix_checks = " OR ".join(f"right({m}, {len(s)}) = '{s}'" for s in CLOUD_MODEL_SUFFIXES)
    prefix_checks = " OR ".join(f"left({p}, {len(x)}) = '{x}'" for x in LOCAL_PREFIXES)
    return (
        f"CASE WHEN {provider_col} IS NULL THEN 'local' "
        f"WHEN {p} IN ({_sql_list(NEVER_DISPATCHED)}) THEN 'local' "
        f"WHEN {suffix_checks} THEN 'external' "
        f"WHEN {p} IN ({_sql_list(LOCAL_PROVIDERS)}) THEN 'local' "
        f"WHEN {prefix_checks} THEN 'local' "
        f"WHEN position('cloud' in {p}) > 0 THEN 'external' "
        f"ELSE 'external' END"
    )


def is_cloud_row(provider: str | None, model_used: str | None) -> bool:
    """Python twin of :func:`cloud_classifier_sql`, identical precedence.

    Pinned to the SQL by ``tests/test_token_provenance.py`` — both against a
    truth table AND against every distinct (provider, model_used) pair in the
    live window — so a change to one without the other is a red test.
    """
    if provider is None:
        return False
    p = provider.lower()
    if p in NEVER_DISPATCHED:
        return False
    if (model_used or "").lower().endswith(CLOUD_MODEL_SUFFIXES):
        return True
    if p in LOCAL_PROVIDERS:
        return False
    if p.startswith(LOCAL_PREFIXES):
        return False
    if "cloud" in p:
        return True
    return True
