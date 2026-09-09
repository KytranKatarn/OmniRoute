"""All cloud tokens count as cloud on the Token Economy tab — one classifier.

THE DEFECT (measured 2026-09-09, owner requirement the same day):

Token Economy had two definitions of "cloud" that disagreed on live rows —
the totals/series keyed on ``provider``, the Buckets panel on
``worker_type='contract'``. 637,900 ``ollama_cloud`` tokens (665 runs) that left
the cluster were drawn in the AGENT-LOCAL bucket. The fix routes both panels
through ``services.token_provenance`` — ONE classifier (an allowlist of
provably-local providers, everything else cloud) and ONE estimated-token
definition, both computed once per row.

WHAT AN ADVERSARIAL REVIEW OF THE FIRST DRAFT FOUND, and what this file now pins
(three refuters, wf_84c69a32-77c):

  * the "exact reconciliation" test was an ALGEBRAIC IDENTITY — it held for a
    classifier that said "Ollama is cloud". Deleted. Never assert an equation
    whose terms are defined in terms of each other.
  * the "only leaves the bucket when provably local" test compared
    LOCAL_PROVIDERS to itself, so poisoning the allowlist with ``anthropic``
    passed every test. The expected sets are now FROZEN here, not imported.
  * the source-scanning tests were fooled by a comment, an IN-list, or a
    one-line triple-quoted string. They are AST-based now.
  * three provably-local providers were missing from the allowlist and flipped
    to cloud (``ollama_vision``, ``comfyui_deferred``, ``starship:<node>``).
  * the two panels still disagreed on range=365 by 10,102,978 tokens because
    only one of them excluded ESTIMATED backfill rows. Both share ESTIMATED_SQL
    now; the buckets panel shows them as their own bucket.
  * the legend shipped to the browser still said "worker_type=contract".

WHERE THE DATA COMES FROM — READ THIS BEFORE "FIXING" A SKIP:

Under pytest, conftest FORCES the isolated ``archie_test`` database and
``database._get_pool`` refuses production outright (KB #274942 — a test once
wrote "mock" into 1,166 live rows). ``archie_test`` is a schema clone with NO
rows, so a "live data" assertion run under pytest is vacuous by construction —
which is exactly how the first version of this file passed 77/77 on the host
while checking nothing. Two sources now, both non-vacuous:

  * ``seeded`` — a committed, tagged population (SEED below) INSERTed into
    ``archie_test`` for the module and deleted after. Deterministic, runs
    anywhere the schema exists (host + container), and it is what the Flask
    agreement test reads through the real endpoints.
  * ``prod_ro`` — a READ-ONLY session on production (``default_transaction_read_only``
    is set at connection time, so an INSERT/UPDATE raises inside Postgres — it is
    not a convention). Used ONLY for the drift pins that need the real
    (provider, model_used) population. SKIPS, with the reason, when prod is not
    reachable (no DB_HOST / wrong host); it never falls back to the test DB.

Run (host, repo checkout — the prod_ro pins are OPT-IN, read-only, and need DB_HOST):
    ARCHIE_PROD_RO_PINS=1 DB_HOST=192.168.1.200 DB_PASSWORD=... python3 -m pytest tests/test_token_provenance.py -v
The Flask agreement test needs /app/app.py (the container); on the host it SKIPS:
    docker exec -i archie_platform python3 -m pytest tests/test_token_provenance.py -k agree -v
"""

import ast
import os
import sys
from pathlib import Path

import psycopg2
import pytest

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from services.token_provenance import (  # noqa: E402
    CLOUD_MODEL_SUFFIXES,
    ESTIMATED_SQL,
    LOCAL_PREFIXES,
    LOCAL_PROVIDERS,
    NEVER_DISPATCHED,
    cloud_classifier_sql,
    is_cloud_row,
)

_ROUTES = _HERE.parents[1] / "tools" / "consciousness" / "code_health_routes.py"

# ── FROZEN expectations. Deliberately NOT imported from the module: the module is
# the thing under test, and a test that reads its expectations from the code it
# checks can only ever agree with it (that is exactly how the first draft let a
# poisoned allowlist through). Change these ON PURPOSE, in the same commit as the
# module, with a reason in the message.
EXPECTED_LOCAL = ("ollama", "fleet_node", "local", "llamacpp", "comfyui", "ollama_vision", "comfyui_deferred")
EXPECTED_LOCAL_PREFIXES = ("starship:",)
EXPECTED_NEVER_DISPATCHED = ("cloud_pending",)
EXPECTED_CLOUD_SUFFIXES = (":cloud", "-cloud")

# Every cloud provider this platform knows about: contractor_providers.provider_key
# (minus the two LOCAL entries in that table, comfyui and ollama_diffuser), plus
# the names the pre-fix hardcoded tuple carried, plus the ones that write rows
# today. Adding ANY of these to the local allowlist must be a red test.
CLOUD_REGISTRY = (
    "cerebras",
    "claude",
    "cloudflare_ai",
    "cohere",
    "deepseek",
    "elevenlabs",
    "fal_ai",
    "gemini",
    "groq",
    "huggingface",
    "minimax_cloud",
    "mistral",
    "openai",
    "openrouter",
    "perplexity",
    "pollinations",
    "qwen3_cloud",
    "replicate",
    "replicate_audio",
    "stability_ai",
    "stability_audio",
    "together",
    "xai",
    "minimax",
    "cloudflare",
    "anthropic",
    "ollama_cloud",
    "omniroute",
)

# (provider, model_used, expected) — every live disagreement the old rules produced,
# every miss the refuters found, and the future-provider case.
TRUTH = [
    ("ollama_cloud", "gemma3:12b", "external"),  # 665 runs / 637,900 tok mis-bucketed as local
    ("groq", "llama-3.1-8b", "external"),  # logged with worker_type=internal
    ("ollama", "qwen2.5:7b", "local"),  # worker_type=contract on 4 rows — provider wins
    ("ollama", "minimax-m2.5:cloud", "external"),  # hosted model proxied through the local daemon (live rows)
    ("ollama", "gpt-oss:120b-cloud", "external"),  # Ollama's OTHER hosted-tag spelling
    ("fleet_node", "qwen2.5:7b", "local"),
    ("llamacpp", "x", "local"),
    ("comfyui", "sd_xl", "local"),
    ("ollama_vision", "moondream", "local"),  # refuter: local moondream path, was flipped to cloud
    ("comfyui_deferred", "sd_xl", "local"),  # refuter: local, deferred on capacity
    ("starship:node_7e33e91ba868d446", "qwen2.5:7b", "local"),  # refuter: prefix-shaped fleet tag
    ("cloud_pending", "x", "local"),  # refuter: written BEFORE any call; nothing left
    ("cloud_pending", "x:cloud", "local"),  # never-dispatched beats the model suffix
    (None, "bridge-managed", "local"),  # 0-token markers / legacy
    ("OLLAMA", "qwen2.5:1.5b", "local"),  # case-insensitive
    ("Starship:NODE_X", "m", "local"),  # prefix, case-insensitive
    ("anthropic", "claude", "external"),
    ("openai", "gpt", "external"),
    ("omniroute", "auto", "external"),  # ⚠ NOT in any tuple — cloud BY DEFAULT
    ("some-provider-nobody-registered", "m", "external"),  # fail-safe direction
]


# Per-run tag: two runs of this file overlap in the SHARED archie_test DB (the
# sandbox Test Bay, parallel reviewers) and a fixed tag let one run DELETE the
# other's population mid-module (measured: `assert 0 == 17`). Each run seeds and
# removes only its own rows; a foreign run's rows are just "other rows" below.
SEED_TAG = f"__token_provenance_seed__{os.getpid()}_{__import__('uuid').uuid4().hex[:8]}"

# (provider, model_used, worker_type, tokens, module_source, token_source, expected)
# worker_type is CHECK-constrained to internal|contract|NULL on task_execution_log.
# Every row the two old rules disagreed on is here, plus every refuter miss, plus
# the estimated-backfill axis, so the Flask endpoints exercise every bucket.
SEED = [
    ("ollama_cloud", "gemma3:12b", "internal", 637, "agent_loop", None, "external"),
    ("groq", "llama-3.1-8b", "internal", 116, "agent_loop", None, "external"),
    ("ollama", "qwen2.5:7b", "contract", 11093, "agent_loop", None, "local"),
    ("ollama", "minimax-m2.5:cloud", "internal", 500, "agent_loop", None, "external"),
    ("ollama", "gpt-oss:120b-cloud", "internal", 300, "agent_loop", None, "external"),
    ("fleet_node", "qwen2.5:7b", "internal", 700, "agent_loop", None, "local"),
    ("ollama_vision", "moondream", "internal", 90, "agent_loop", None, "local"),
    ("comfyui_deferred", "sd_xl", "internal", 0, "agent_loop", None, "local"),
    ("starship:node_7e33e91ba868d446", "qwen2.5:7b", "internal", 400, "agent_loop", None, "local"),
    ("cloud_pending", "x:cloud", "contract", 0, "agent_loop", None, "local"),
    (None, "bridge-managed", None, 0, "agent_loop", None, "local"),
    ("anthropic", "claude", "contract", 2000, "claude_cli", None, "external"),
    ("openai", "gpt", "contract", 1500, "codex_cli", None, "external"),
    ("omniroute", "auto", "contract", 250, "agent_loop", None, "external"),
    ("ollama", "qwen2.5:1.5b", "internal", 50, "fleet_warmup", None, "local"),
    (None, None, "internal", 868000, "agent_loop", "estimated", "local"),
    ("ollama", "qwen2.5:7b", "internal", 5000, "agent_loop", "estimated_historical", "local"),
    # ESTIMATED *and* EXTERNAL — the exact shape of the 10,102,978-token ALL-range
    # divergence (anthropic/contract backfill). Without this row a swap of the
    # is_est/is_cloud order in bucket_case, or dropping NOT is_est from the cloud
    # sum, leaves every seeded number unchanged (refuter finding).
    ("anthropic", "claude", "contract", 10000, "claude_cli", "estimated_historical", "external"),
]
SEED_CLOUD_TOKENS = sum(r[3] for r in SEED if r[6] == "external" and r[5] is None)  # 5303
SEED_EST_TOKENS = sum(r[3] for r in SEED if r[5] is not None)  # 883000
SEED_LIVE_LOCAL_TOKENS = sum(r[3] for r in SEED if r[6] == "local" and r[5] is None)  # 12333


@pytest.fixture(scope="module")
def seeded():
    """Commit the SEED population into the (forced) test DB; remove it after.

    Committed, not rolled back, because the Flask endpoints read through their own
    pool connection and must see the rows. Guarded by asking the CONNECTION which
    database it is on — DB_NAME can be clobbered by another module at import."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_conn, c):
        c.execute("SELECT current_database()")
        assert _one(c.fetchone()) != "archie", "refusing to seed rows into production"
        c.execute("DELETE FROM task_execution_log WHERE agent_name = %s", (SEED_TAG,))
        for provider, model, wt, tokens, module_source, token_source, _exp in SEED:
            meta = {"token_source": token_source} if token_source else {}
            c.execute(
                "INSERT INTO task_execution_log (agent_name, provider, model_used, worker_type, tokens_used,"
                " module_source, request_metadata, success, task_type, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, true, 'test', now() - interval '1 hour')",
                (SEED_TAG, provider, model, wt, tokens, module_source, __import__("json").dumps(meta)),
            )
    yield SEED
    with get_db_cursor(commit=True) as (_conn, c):
        c.execute("DELETE FROM task_execution_log WHERE agent_name = %s", (SEED_TAG,))


@pytest.fixture(scope="module")
def cur(seeded):
    from database import get_db_cursor

    with get_db_cursor() as (_conn, c):
        yield c


@pytest.fixture(scope="module")
def prod_ro():
    """READ-ONLY session on production for the drift pins. OPT-IN and enforced.

    Opt-in (`ARCHIE_PROD_RO_PINS=1`): a plain pytest run — the sandbox Test Bay, a
    full in-container run where DB_HOST=archie_database would otherwise reach prod
    — must never touch production by default (KB #274942). The pins are an operator
    action; the documented host command sets the flag.
    Enforced: `set_session(readonly=True)` makes psycopg2 open EVERY transaction as
    `BEGIN READ ONLY`, which a `SET default_transaction_read_only=off` inside the
    session cannot undo (the connect-time GUC alone could be flipped — refuter
    finding). Postgres raises on any write."""
    import database

    if os.environ.get("ARCHIE_PROD_RO_PINS") != "1":
        pytest.skip("prod_ro: set ARCHIE_PROD_RO_PINS=1 (and DB_HOST) to run the live drift pins against production")
    host = os.environ.get("DB_HOST", "")
    if not host or host in ("localhost", "127.0.0.1"):
        pytest.skip("prod_ro: set DB_HOST=192.168.1.200 to run the live drift pins (test DB has no history)")
    try:
        conn = psycopg2.connect(
            host=host,
            port=os.environ.get("DB_PORT", "5432"),
            user=os.environ.get("DB_USER", "archie"),
            password=database._get_db_password(),
            dbname="archie",
            connect_timeout=4,
            options="-c default_transaction_read_only=on",
        )
    except Exception as exc:  # pragma: no cover - host without prod reach
        pytest.skip(f"prod_ro: production not reachable from here ({type(exc).__name__}: {exc})")
    conn.set_session(readonly=True, autocommit=False)
    with conn.cursor() as c:
        c.execute("SELECT current_setting('transaction_read_only')")
        assert c.fetchone()[0] == "on", "prod_ro transaction is not read-only — refusing to continue"
        yield c
    conn.rollback()
    conn.close()


@pytest.fixture(scope="module", params=["seeded_test_db", "prod_readonly"])
def anycur(request):
    """The population-level pins run on BOTH sources: the deterministic seed and the
    real history. A source that is not available skips with its reason."""
    return request.getfixturevalue("cur" if request.param == "seeded_test_db" else "prod_ro")


def _one(row):
    return row[0] if not isinstance(row, dict) else list(row.values())[0]


def _cols(row, *names):
    return tuple(row[i] for i in range(len(names))) if not isinstance(row, dict) else tuple(row[n] for n in names)


# ── behaviour: SQL truth table, Python twin, and the LIVE drift pin ──────────


@pytest.mark.parametrize("provider,model,expected", TRUTH)
def test_sql_classifier_truth_table(cur, provider, model, expected):
    cur.execute(f"SELECT {cloud_classifier_sql('p', 'm')} FROM (SELECT %s::text p, %s::text m) t", (provider, model))
    got = _one(cur.fetchone())
    assert got == expected, f"SQL: ({provider!r}, {model!r}) -> {got!r}, expected {expected!r}"


@pytest.mark.parametrize("provider,model,expected", TRUTH)
def test_python_twin_matches_truth_table(provider, model, expected):
    assert is_cloud_row(provider, model) is (expected == "external")


def test_python_twin_matches_sql_on_every_live_pair(anycur):
    """THE drift pin the module docstring promises. The truth-table test above
    compares the twin to a hand-written column; this compares it to the SQL, on
    every distinct (provider, model_used) the table actually holds — the seeded
    population here, the real 180-day history on prod_ro."""
    cur = anycur
    cur.execute(
        f"SELECT DISTINCT provider, model_used, {cloud_classifier_sql()} AS c "
        "FROM task_execution_log WHERE created_at > now() - interval '180 days'"
    )
    rows = cur.fetchall()
    assert len(rows) > 0, "no live pairs — the window is empty, the test is vacuous"
    bad = []
    for r in rows:
        provider, model, c = _cols(r, "provider", "model_used", "c")
        if is_cloud_row(provider, model) is not (c == "external"):
            bad.append((provider, model, c))
    assert not bad, f"SQL and Python twin disagree on {len(bad)} live pair(s): {bad[:8]}"


def test_classifier_sql_is_valid_against_schema(cur):
    """Schema smoke test ONLY — a phantom column raises here. Not classifier coverage."""
    cur.execute(
        f"SELECT {cloud_classifier_sql()} AS c, {ESTIMATED_SQL} AS e, count(*) FROM task_execution_log "
        "WHERE created_at > now() - interval '1 day' GROUP BY 1, 2"
    )
    cur.fetchall()


def test_no_percent_sign_in_the_sql():
    """Both consumers pass psycopg2 params (``%`` must be ``%%``); a future consumer
    without params would then match the literal ``%cloud%``. Neither helper emits one."""
    assert "%" not in cloud_classifier_sql()
    assert "%" not in ESTIMATED_SQL


# ── the allowlists are exactly what we froze — a poisoned list is a red test ─


def test_allowlists_are_exactly_the_frozen_sets():
    assert (
        tuple(LOCAL_PROVIDERS) == EXPECTED_LOCAL
    ), f"LOCAL_PROVIDERS changed: {LOCAL_PROVIDERS}. If deliberate, update EXPECTED_LOCAL in the same commit and say why."
    assert tuple(LOCAL_PREFIXES) == EXPECTED_LOCAL_PREFIXES
    assert tuple(NEVER_DISPATCHED) == EXPECTED_NEVER_DISPATCHED
    assert tuple(CLOUD_MODEL_SUFFIXES) == EXPECTED_CLOUD_SUFFIXES


@pytest.mark.parametrize("cloud", CLOUD_REGISTRY)
def test_every_registered_cloud_provider_classifies_external(cur, cloud):
    """Behavioural, not containment: each registered cloud key must come back
    'external' from the SQL, and must not appear in any local set."""
    assert cloud not in LOCAL_PROVIDERS and cloud not in NEVER_DISPATCHED
    assert not cloud.startswith(LOCAL_PREFIXES)
    cur.execute(f"SELECT {cloud_classifier_sql('p', 'm')} FROM (SELECT %s::text p, 'x'::text m) t", (cloud,))
    assert _one(cur.fetchone()) == "external"


# ── the live invariants the owner asked for ──────────────────────────────────


def test_seeded_population_classifies_exactly(cur):
    """Every seeded row, through the REAL table (types, NULLs, JSONB), lands where
    SEED says. This is the truth table again but on task_execution_log rows, not
    a `SELECT %s::text` — a column-type surprise shows up here first."""
    cur.execute(
        f"SELECT provider, model_used, COALESCE(request_metadata->>'token_source','') ts, "
        f"{cloud_classifier_sql()} AS c, {ESTIMATED_SQL} AS e "
        "FROM task_execution_log WHERE agent_name=%s ORDER BY id",
        (SEED_TAG,),
    )
    rows = cur.fetchall()
    assert len(rows) == len(SEED)
    for row, (provider, model, _wt, _tok, _ms, token_source, expected) in zip(rows, SEED):
        p, m, ts, c, e = _cols(row, "provider", "model_used", "ts", "c", "e")
        assert (p, m) == (provider, model)
        assert c == expected, f"seed ({provider!r}, {model!r}) -> {c!r}, expected {expected!r}"
        assert e is (token_source is not None), f"seed ({provider!r}, {model!r}) estimated flag wrong"


def test_ollama_cloud_rows_are_counted_as_cloud_live(anycur):
    """The exact population the old Buckets rule put in the agent-local bucket.
    Non-vacuous: total must be > 0 on both sources (the seed carries one; prod
    held 9,833 at authoring)."""
    cur = anycur
    cur.execute(
        f"SELECT count(*) FILTER (WHERE ({cloud_classifier_sql()})<>'external') AS wrong, count(*) AS total "
        "FROM task_execution_log WHERE provider='ollama_cloud' AND created_at > now() - interval '365 days'"
    )
    wrong, total = _cols(cur.fetchone(), "wrong", "total")
    assert total > 0, "no ollama_cloud rows in 365d — this assertion has nothing to check"
    assert wrong == 0, f"{wrong} of {total} ollama_cloud rows still classify as local"


def test_tokens_only_leave_the_cloud_bucket_when_provably_local(anycur):
    """THE safety property, window-independent: every row the new rule demotes
    from cloud (old said contract, new says local) has a provider in the FROZEN
    local sets — never the module's own (possibly poisoned) list."""
    cur = anycur
    local_list = ", ".join(f"'{p}'" for p in EXPECTED_LOCAL + EXPECTED_NEVER_DISPATCHED)
    prefix_ok = " OR ".join(f"left(lower(provider), {len(x)}) = '{x}'" for x in EXPECTED_LOCAL_PREFIXES)
    cur.execute(
        f"SELECT count(*) FROM task_execution_log "
        f"WHERE created_at > now() - interval '365 days' AND worker_type='contract' "
        f"AND ({cloud_classifier_sql()})='local' "
        f"AND provider IS NOT NULL AND lower(provider) NOT IN ({local_list}) AND NOT ({prefix_ok})"
    )
    n = _one(cur.fetchone())
    assert n == 0, f"{n} row(s) left the cloud bucket without a frozen-local provider"
    # NULL provider is "local BY POLICY" (nothing recorded leaving) — that policy is
    # only safe while no contract-typed row carries real live tokens under it.
    cur.execute(
        f"SELECT count(*) FROM task_execution_log WHERE created_at > now() - interval '365 days' "
        f"AND worker_type='contract' AND provider IS NULL AND COALESCE(tokens_used,0) > 0 AND NOT {ESTIMATED_SQL}"
    )
    n = _one(cur.fetchone())
    assert n == 0, f"{n} contract row(s) with real tokens and NO provider would leave the cloud bucket by policy"


def test_rows_entering_the_cloud_bucket_are_the_known_migration_set(anycur):
    """The population the new rule ADDS to cloud (external now, not contract before)
    is a known set. A new internal-typed provider appearing here is not wrong —
    but it must be a conscious addition to this tuple, not a silent one.
    The seed carries exactly the three (ollama_cloud, groq, ollama:*cloud)."""
    cur = anycur
    cur.execute(
        f"SELECT DISTINCT provider FROM task_execution_log "
        f"WHERE created_at > now() - interval '365 days' AND worker_type IS DISTINCT FROM 'contract' "
        f"AND ({cloud_classifier_sql()})='external' AND provider IS NOT NULL"
    )
    got = sorted(_one(r) for r in cur.fetchall())
    expected = {"ollama_cloud", "groq", "ollama"}  # ollama = hosted :cloud models via the local daemon
    unexpected = [p for p in got if p not in expected]
    assert not unexpected, f"new provider(s) entering the cloud bucket outside the known set: {unexpected}"


# ── structural (AST, not regex): both panels use the helpers; nothing keys on worker_type ─


def _route_funcs(tree):
    """{function_name: FunctionDef} for every def in the module, nested included."""
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _calls_named(fn, name):
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name):
                return True
    return False


def _names_used(fn, name):
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(fn))


def test_both_endpoints_use_the_shared_helpers_ast():
    tree = ast.parse(_ROUTES.read_text(encoding="utf-8"))
    fns = _route_funcs(tree)
    for fname in ("code_health_token_buckets", "code_health_token_usage"):
        assert fname in fns, f"{fname} is gone — did the routes get renamed?"
        assert _calls_named(fns[fname], "cloud_classifier_sql"), f"{fname} no longer calls cloud_classifier_sql()"
        assert _names_used(fns[fname], "ESTIMATED_SQL"), f"{fname} no longer uses the shared ESTIMATED_SQL"


def test_no_string_constant_classifies_by_worker_type_ast():
    """A comment cannot fool this: it walks real string CONSTANTS in the module.

    TRIPWIRE, not the pin: an f-string, concatenation or a split literal evades it
    (refuter measured 2 of 10 spellings caught). The behavioural pin is
    test_both_panels_agree_on_every_range, whose expected numbers come from a
    test-local FROZEN oracle, so a worker_type-keyed reintroduction is red there."""
    tree = ast.parse(_ROUTES.read_text(encoding="utf-8"))
    offenders = [
        n.value[:80]
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and "worker_type" in n.value
        and "contract" in n.value
    ]
    assert not offenders, "a string constant still keys cloud on worker_type=contract:\n" + "\n".join(offenders)


def test_no_legacy_inline_cloud_detector_ast():
    """The pre-fix ILIKE '%%cloud%%' / hardcoded provider tuple must not come back
    under a comment that mentions the helper."""
    tree = ast.parse(_ROUTES.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            assert "ILIKE '%%cloud%%'" not in n.value, "legacy ILIKE cloud detector is back"
            assert "provider IN ('openai'" not in n.value, "legacy hardcoded provider tuple is back"


def test_cloud_bucket_legend_does_not_describe_the_old_rule():
    """The desc is rendered verbatim in the browser (consciousness.js)."""
    src = _ROUTES.read_text(encoding="utf-8")
    assert "worker_type=contract · agentless by design" not in src


# ── the panels agree, through the real Flask routes, on every range incl. ALL ─


@pytest.fixture(scope="module")
def admin_client(seeded):
    """conftest's Flask loader (module-scoped here so the app is built once), logged
    in as a seeded test admin. Skips on a host without /app/app.py."""
    app_py = os.environ.get("ARCHIE_APP_PY", "/app/app.py")
    if not os.path.exists(app_py):
        pytest.skip(f"Flask app not present at {app_py}; run inside archie_platform for the agreement test")
    from tests.conftest import _TEST_ADMIN_IDS, _load_flask_app

    flask_app = _load_flask_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        with c.session_transaction() as s:
            s["_user_id"] = str(_TEST_ADMIN_IDS[0])
            s["_fresh"] = True
        yield c


def _frozen_is_cloud(provider, model):
    """Test-LOCAL oracle built from the FROZEN sets — deliberately not is_cloud_row(),
    so the expected numbers cannot be produced by the code under test."""
    if provider is None:
        return False
    p = provider.lower()
    if p in EXPECTED_NEVER_DISPATCHED:
        return False
    if (model or "").lower().endswith(EXPECTED_CLOUD_SUFFIXES):
        return True
    if p in EXPECTED_LOCAL or p.startswith(EXPECTED_LOCAL_PREFIXES):
        return False
    return True


_FROZEN_ESTIMATED = ("estimated", "estimated_historical")
_RANGE_INTERVAL = {"7": "7 days", "30": "30 days", "90": "90 days", "365": "365 days"}


def _expected_split(interval):
    """(cloud, estimated, live_local) over EVERY row in the window — the seed plus
    whatever else the shared test DB holds — via the frozen oracle."""
    from database import get_db_cursor

    cloud = est = local = 0
    with get_db_cursor() as (_conn, c):
        c.execute(
            "SELECT provider, model_used, COALESCE(tokens_used,0) t, COALESCE(request_metadata->>'token_source','') ts "
            "FROM task_execution_log WHERE created_at > now() - %s::interval",
            (interval,),
        )
        for r in c.fetchall():
            provider, model, t, ts = _cols(r, "provider", "model_used", "t", "ts")
            if ts in _FROZEN_ESTIMATED:
                est += t
            elif _frozen_is_cloud(provider, model):
                cloud += t
            else:
                local += t
    return cloud, est, local


@pytest.mark.parametrize("rng", ["7", "30", "90", "365"])
def test_both_panels_agree_on_every_range(admin_client, rng):
    """range=365 is the UI's ALL button — the one the first draft got wrong by
    10,102,978 tokens. A 302 here means the session is wrong, not that it passed.

    EXACT numbers from the frozen oracle, not floors. The refuters showed floors are
    blind: with BOTH panels keyed on the old worker_type='contract' rule the seed
    yields 14,843 == 14,843 and every `>=` still holds. Against the oracle the seed
    is 5,303 cloud / 883,000 estimated / 12,333 live-local, and the contract rule's
    14,843 is red on the first assertion."""
    client = admin_client
    b = client.get(f"/tools/consciousness/api/code-health/token-buckets?range={rng}&refresh=1")
    u = client.get(f"/tools/consciousness/api/code-health/token-usage?range={rng}&refresh=1")
    assert b.status_code == 200 and u.status_code == 200, (b.status_code, u.status_code)
    bj, uj = b.get_json(), u.get_json()
    exp_cloud, exp_est, exp_local = _expected_split(_RANGE_INTERVAL[rng])
    assert exp_cloud >= SEED_CLOUD_TOKENS and exp_est >= SEED_EST_TOKENS, "seed not in window — vacuous"
    assert bj["cloud_tokens"] == exp_cloud, f"range={rng}: buckets.cloud={bj['cloud_tokens']} != oracle {exp_cloud}"
    assert uj["totals"]["external_tokens"] == exp_cloud, f"range={rng}: usage.external != oracle {exp_cloud}"
    keys = {x["key"] for x in bj["buckets"]}
    assert "estimated" in keys, "estimated bucket missing — the ALL range would diverge again"
    est_tokens = next(x["tokens"] for x in bj["buckets"] if x["key"] == "estimated")
    assert est_tokens == exp_est == bj["estimated_tokens"] == uj["totals"]["estimated_tokens"]
    assert (
        bj["local_tokens"] == exp_local == uj["totals"]["local_tokens"]
    ), f"range={rng}: buckets.local={bj['local_tokens']} usage.local={uj['totals']['local_tokens']} oracle={exp_local}"
    assert bj["pct_local"] == uj["totals"]["pct_local"], "pct_local differs between the two panels"
    assert sum(x["tokens"] for x in bj["buckets"]) == bj["total_tokens"], "buckets no longer sum to total"
    assert bj["total_tokens"] == exp_cloud + exp_est + exp_local
    cloud_desc = next(x["desc"] for x in bj["buckets"] if x["key"] == "cloud")
    assert "worker_type" not in cloud_desc
