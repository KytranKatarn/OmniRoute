# WTF + TheNews Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire `thenews.kytranempowerment.com` and stand up a 3-container What The Fact stack (`wtf-consumer` port 8103, `wtf-tech` port 8104, `wtf-ingest` internal) on the US Outpost VPS, migrating `what-the-fact.com` off Hostinger shared.

**Architecture:** Clean cut of TheNews (no data migration) → new `/mnt/archie_brain/what-the-fact/` repo with Flask services sharing a Postgres schema (articles, bias_scores, fact_checks, audit_trail, source_registry) → Caddy auto-HTTPS on VPS → Kytran SSO via existing SDK → registered alongside Watch-series in platform registries.

**Tech Stack:** Python 3.11, Flask, SQLAlchemy, psycopg2, feedparser, pytest, Docker Compose, Caddy 2, PostgreSQL 16, `kytran_auth.py` SDK (vendored — see task #2064).

**Spec:** `docs/superpowers/specs/2026-04-18-wtf-thenews-consolidation-design.md`

**Constants referenced throughout:**
- VPS host: `76.13.107.109` (SSH as root per existing Watch-series pattern)
- Consumer domain: `what-the-fact.com`
- Tech domain: `what-the-fact.tech`
- Hub: `192.168.1.200` (Archie platform + platform DB at port 5432)
- Shared DB: `archie` on hub (schema `wtf`)
- Repo root: `/mnt/archie_brain/what-the-fact/`

---

## File Structure

**Created:**
```
/mnt/archie_brain/what-the-fact/
├── docker-compose.yml                 # 3-service stack
├── Dockerfile.ingest                  # wtf-ingest image
├── Dockerfile.consumer                # wtf-consumer image
├── Dockerfile.tech                    # wtf-tech image
├── .env.example                       # documented env vars
├── README.md                          # install + run
│
├── shared/                            # shared across 3 services
│   ├── __init__.py
│   ├── db.py                          # SQLAlchemy engine + session factory
│   ├── models.py                      # Article, BiasScore, FactCheck, AuditTrail, Source
│   ├── kytran_auth.py                 # vendored SSO SDK (copy from kytran-auth/)
│   └── creed_events.py                # C.R.E.E.D. event emission helper
│
├── migrations/
│   └── 001_wtf_schema.sql             # tables + indexes in schema `wtf`
│
├── ingest/
│   ├── __init__.py
│   ├── sources/
│   │   ├── __init__.py
│   │   └── cbc_english.py             # CBC RSS fetcher
│   ├── normalizer.py                  # canonical article builder
│   ├── bias.py                        # rule-based bias heuristic
│   ├── persist.py                     # DB writes + dead-letter
│   └── run.py                         # main loop (once-per-hour)
│
├── consumer/
│   ├── __init__.py
│   ├── app.py                         # Flask app factory
│   ├── routes.py                      # list + detail views
│   ├── templates/
│   │   ├── base.html                  # Watch-series frame
│   │   ├── index.html                 # article list
│   │   └── article.html               # detail + bias badge
│   └── static/
│       └── style.css                  # Watch-series tokens
│
├── tech/
│   ├── __init__.py
│   ├── app.py                         # Flask app factory
│   ├── routes.py                      # transparency portal pages
│   ├── api.py                         # read-only /api/v1/*
│   ├── templates/
│   │   ├── base.html                  # Watch-series frame
│   │   ├── index.html                 # methodology landing
│   │   ├── transparency.html          # per-article audit trail
│   │   └── dashboard.html             # SSO-gated developer portal
│   └── static/
│       └── style.css                  # Watch-series tokens
│
└── tests/
    ├── __init__.py
    ├── conftest.py                    # test DB fixture
    ├── fixtures/
    │   ├── cbc_sample.xml             # frozen RSS sample
    │   └── bias_golden.json           # 10 labeled articles
    ├── test_cbc_english.py
    ├── test_normalizer.py
    ├── test_bias.py
    ├── test_persist.py
    ├── test_consumer_routes.py
    ├── test_tech_api.py
    └── test_tech_sso.py
```

**Modified:**
- `platform_v2/services/code_metrics_service.py` — rename TheNews entry → WTF; update path
- `platform_v2/services/infra_heartbeat_service.py` — swap `kytran_news` → `wtf-consumer`/`wtf-tech`/`wtf-ingest`
- `platform_v2/module_registry.py` — replace `kytran_news` ModuleDefinition with `what_the_fact`
- `database/migrations/305_oauth_userinfo_and_clients.sql` — superseded by new migration (added next)
- `database/migrations/306_wtf_oauth_clients.sql` — NEW: seeds `wtf-consumer`, `wtf-tech` clients, deactivates `news`
- `.claude/rules/operational-state.md` — product registry table + DNS list
- `MEMORY.md` + `project_session-handoff.md` — note retirement + new stack
- VPS `/root/archie-outpost/docker-compose.yml` — remove `kytran_news`, add 3 WTF services
- VPS `/etc/caddy/Caddyfile` — remove thenews stanza, add `what-the-fact.com` + `what-the-fact.tech`

---

## Phase A — Retire TheNews (parallel with Phase B)

### Task A1: Snapshot the `kytran_news` container before removal

**Why:** Spec Risk 2 — if the broken container holds any unique content, don't nuke it blind. A `docker commit` costs ~10 seconds and buys 30 days of undo.

**Files:**
- None modified locally. Operates on VPS only.

- [ ] **Step 1: SSH to VPS and snapshot the image**

```bash
ssh root@76.13.107.109 'docker commit kytran_news kytran_news_archive:$(date +%Y%m%d) && docker images | grep kytran_news_archive'
```

Expected output: one line showing `kytran_news_archive:YYYYMMDD ... <image id>`. Record the image ID.

- [ ] **Step 2: Dump any mounted volumes to a tarball on the VPS**

```bash
ssh root@76.13.107.109 'docker inspect kytran_news --format "{{range .Mounts}}{{.Source}}{{\"\n\"}}{{end}}" > /root/kytran_news_mounts.txt && cat /root/kytran_news_mounts.txt'
```

If output lists any bind-mount paths, tar them:
```bash
ssh root@76.13.107.109 'tar czf /root/kytran_news_backup_$(date +%Y%m%d).tar.gz -T /root/kytran_news_mounts.txt 2>/dev/null; ls -lh /root/kytran_news_backup_*.tar.gz'
```

Expected: tarball exists, size > 0. If no mounts, skip.

- [ ] **Step 3: Commit the "backup recorded" KB note**

```bash
# From hub
python3 -c "
import sys; sys.path.insert(0, '/mnt/archie_brain/platform_v2')
# store via MCP or direct DB — use MCP store_memory for consistency
"
```

Use the `mcp__archie__store_memory` tool with:
- memory_type: `vault_note`
- category: `infrastructure`
- tags: `["thenews", "retirement", "backup"]`
- content: `"kytran_news container archived 2026-04-18 to image kytran_news_archive:<YYYYMMDD> on 76.13.107.109. Mount tarball at /root/kytran_news_backup_<YYYYMMDD>.tar.gz. Retain 30 days (delete after 2026-05-18)."`

- [ ] **Step 4: Commit**

No code change — this task is operational. Record completion in task tracker only.

---

### Task A2: Remove `kytran_news` from VPS (stop → rm → compose → Caddy)

**Why:** Free port 8103 and its Caddy stanza before Phase C reuses them.

**Files:**
- Modify on VPS: `/root/archie-outpost/docker-compose.yml`
- Modify on VPS: `/etc/caddy/Caddyfile`

- [ ] **Step 1: Stop and remove the container**

```bash
ssh root@76.13.107.109 'docker stop kytran_news && docker rm kytran_news'
```

Expected: two lines of output, one `kytran_news` each. Non-zero exit only if container already gone — acceptable.

- [ ] **Step 2: Edit VPS compose to drop the service**

```bash
ssh root@76.13.107.109 'cp /root/archie-outpost/docker-compose.yml /root/archie-outpost/docker-compose.yml.bak_$(date +%Y%m%d)'
```

Then SSH in interactively and remove the `kytran_news:` service block. Validate:

```bash
ssh root@76.13.107.109 'cd /root/archie-outpost && docker compose config --quiet && grep -c kytran_news docker-compose.yml'
```

Expected: exit 0 from `config` (no YAML error); `grep -c` returns `0`.

- [ ] **Step 3: Remove the Caddy stanza for thenews**

```bash
ssh root@76.13.107.109 'cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak_$(date +%Y%m%d)'
```

Interactive edit: delete the `thenews.kytranempowerment.com { ... }` block. Validate:

```bash
ssh root@76.13.107.109 'caddy validate --config /etc/caddy/Caddyfile && grep -c thenews /etc/caddy/Caddyfile'
```

Expected: `Valid configuration`; grep returns `0`.

- [ ] **Step 4: Reload Caddy**

```bash
ssh root@76.13.107.109 'systemctl reload caddy && systemctl status caddy --no-pager | head -5'
```

Expected: status shows `active (running)` and no errors in last 5 lines.

- [ ] **Step 5: Smoke-check the domain is gone**

```bash
curl -sI https://thenews.kytranempowerment.com 2>&1 | head -3
```

Expected: connection refused, cert mismatch, or Caddy's default 404 — NOT a 200 from the old app.

- [ ] **Step 6: Commit (no code change, but a git tag helps audit)**

```bash
cd /mnt/archie_brain
git tag -a thenews-retired -m "kytran_news removed from VPS 2026-04-18"
git push origin thenews-retired
```

---

### Task A3: Remove TheNews references from hub registries

**Files:**
- Modify: `platform_v2/services/code_metrics_service.py` (~line 118-123, the `"What The Fact"` entry with `dir_name: "kytran-news"`)
- Modify: `platform_v2/module_registry.py` (~line 913-923, the `kytran_news` ModuleDefinition)
- Modify: `platform_v2/services/infra_heartbeat_service.py` (CRITICAL_CONTAINERS — if `kytran_news` listed)
- Modify: `.claude/rules/operational-state.md` (product registry table + DNS section)

- [ ] **Step 1: Grep for all references so nothing is missed**

```bash
cd /mnt/archie_brain
grep -rn "kytran_news\|kytran-news\|thenews\." \
  --include="*.py" --include="*.md" --include="*.yml" --include="*.yaml" \
  --exclude-dir=node_modules --exclude-dir=.git \
  platform_v2/ .claude/ docker-compose.yml MEMORY.md 2>/dev/null
```

Record every path:line hit.

- [ ] **Step 2: Update `code_metrics_service.py`**

Change the entry at `_STANDALONE_DEFS`:

```python
# OLD
{
    "name": "What The Fact",
    "dir_name": "kytran-news",
    "module_key": "standalone_kytran_news",
    "tier": 1,
    "type": "api",
    "compliance_packs": ["ubuntu-stig", "docker-stig"],
},

# NEW
{
    "name": "What The Fact",
    "dir_name": "what-the-fact",
    "module_key": "standalone_what_the_fact",
    "tier": 1,
    "compliance_packs": ["ubuntu-stig", "docker-stig", "network-stig"],
},
```

Also rename the `_WEBSITE_DEFS` entry (`"thenews.kytranempowerment.com"`) → remove it; the site is retired. If there's a separate `what-the-fact.com` entry that was tracking Hostinger shared, remove that too — we're not serving from shared anymore.

- [ ] **Step 3: Update `module_registry.py`**

Replace the `kytran_news` ModuleDefinition with:

```python
ModuleDefinition(
    id="what_the_fact",
    name="What The Fact",
    description="AI-powered transparent news<br>Bias detection • Fact-check summaries • Audit trails",
    icon="newspaper",
    category=ModuleCategory.MEDIA_OUTREACH,
    route="/external/wtf",
    external_url="https://what-the-fact.com",
    priority=2,
    tags=["standalone", "product", "watch-series"],
),
```

- [ ] **Step 4: Update `infra_heartbeat_service.py`**

Find the `CRITICAL_CONTAINERS` list. Remove any `kytran_news` entry. (Phase D Task D2 adds the new WTF containers.)

- [ ] **Step 5: Update `.claude/rules/operational-state.md`**

In the product registry table, replace the row:

```markdown
| The News | 8103 | thenews.kytranempowerment.com | kytran_news | VPS |
```

with:

```markdown
| What The Fact Consumer | 8103 | what-the-fact.com | wtf-consumer | VPS |
| What The Fact Tech     | 8104 | what-the-fact.tech | wtf-tech | VPS |
| WTF Ingest             | internal | — | wtf-ingest | VPS |
```

In the DNS section: change the VPS subdomain list — remove `thenews`, add `what-the-fact.com` and `what-the-fact.tech` (note: these are new apex-ish domains, not kytranempowerment.com subdomains — keep that distinction clear).

- [ ] **Step 6: Run platform tests to confirm nothing imports the old name**

```bash
cd /mnt/archie_brain && python -m pytest platform_v2/tests/ -x --tb=short -k "not integration" 2>&1 | tail -20
```

Expected: all pass. If any test fails on `kytran_news` import, fix the import.

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain
git checkout -b chore/retire-thenews
git add platform_v2/services/code_metrics_service.py platform_v2/module_registry.py \
        platform_v2/services/infra_heartbeat_service.py .claude/rules/operational-state.md
git commit -m "chore(retire): drop kytran_news / thenews references from registries"
```

---

### Task A4: Delete `thenews.kytranempowerment.com` DNS record + store retirement KB note

**Files:**
- None. Operates on Hostinger DNS + knowledge_base.

- [ ] **Step 1: Find the current A record for `thenews.kytranempowerment.com`**

Use the Hostinger MCP tool:

```
mcp__hostinger-api__DNS_getDNSRecordsV1 domain=kytranempowerment.com
```

Record the record id for `thenews` (type `A`).

- [ ] **Step 2: Delete the record**

```
mcp__hostinger-api__DNS_deleteDNSRecordsV1 domain=kytranempowerment.com recordIds=[<id>]
```

- [ ] **Step 3: Verify propagation (optional but useful)**

```bash
dig +short thenews.kytranempowerment.com @1.1.1.1
```

Expected: empty (eventually; may take up to TTL).

- [ ] **Step 4: Store retirement KB note**

Use `mcp__archie__store_memory`:
- memory_type: `vault_note`
- category: `infrastructure`
- tags: `["thenews", "retirement", "wtf-consolidation"]`
- content: summary of the retirement (date, VPS cleanup done, DNS deleted, port 8103 freed for wtf-consumer, backup image `kytran_news_archive:<date>` retained 30 days).

- [ ] **Step 5: Log decision**

Use `mcp__archie__log_decision`:
- decision: `"Retire thenews.kytranempowerment.com — clean cut, no data migration"`
- context: `"TheNews had a bad start, no traffic worth preserving. Port 8103 freed for wtf-consumer. Pipeline role consolidated into wtf-ingest. See spec 2026-04-18-wtf-thenews-consolidation-design.md."`

- [ ] **Step 6: Commit** (already done in A3 — no additional code change)

---

## Phase B — Stand up WTF stack (parallel with Phase A)

### Task B1: Scaffold the repo + shared package

**Files:**
- Create: all paths under `/mnt/archie_brain/what-the-fact/` listed in the File Structure above, EXCEPT the Dockerfiles and test fixtures (later tasks).
- Create: `what-the-fact/shared/kytran_auth.py` (vendored from `/mnt/archie_brain/kytran-auth/kytran_auth.py`)
- Create: `what-the-fact/shared/db.py`
- Create: `what-the-fact/shared/models.py` (SQLAlchemy models, empty skeletons)
- Create: `what-the-fact/shared/creed_events.py` (stub for now)
- Create: `what-the-fact/README.md`
- Create: `what-the-fact/.env.example`

- [ ] **Step 1: Create directory skeleton**

```bash
cd /mnt/archie_brain
mkdir -p what-the-fact/{shared,migrations,ingest/sources,consumer/templates,consumer/static,tech/templates,tech/static,tests/fixtures}
touch what-the-fact/{shared,ingest,ingest/sources,consumer,tech,tests}/__init__.py
```

- [ ] **Step 2: Vendor the Kytran SSO SDK**

```bash
cp /mnt/archie_brain/kytran-auth/kytran_auth.py /mnt/archie_brain/what-the-fact/shared/kytran_auth.py
```

Leave the file unmodified. (Task #2064 consolidates all copies later.)

- [ ] **Step 3: Write `shared/db.py`**

```python
"""SQLAlchemy engine + session factory for WTF services."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DB_URL = os.environ["WTF_DATABASE_URL"]  # e.g. postgresql+psycopg2://archie:***@192.168.1.200:5432/archie
engine = create_engine(DB_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_session():
    """FastAPI-style session generator."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4: Write `shared/models.py`**

```python
"""SQLAlchemy models for WTF — articles, bias_scores, fact_checks, audit_trail, source_registry."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, JSON, Boolean
from sqlalchemy.orm import relationship
from .db import Base


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, nullable=False)    # "cbc_english"
    name = Column(String(128), nullable=False)
    url = Column(String(512), nullable=False)
    country = Column(String(8), nullable=False, default="CA")
    language = Column(String(8), nullable=False, default="en")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("wtf.sources.id"), nullable=False)
    external_id = Column(String(512), nullable=False)          # canonical URL or GUID
    title = Column(String(1024), nullable=False)
    body = Column(Text, nullable=False)
    url = Column(String(1024), nullable=False)
    published_at = Column(DateTime, nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    source = relationship("Source")
    # unique(source_id, external_id) enforced in migration


class BiasScore(Base):
    __tablename__ = "bias_scores"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("wtf.articles.id"), nullable=False, unique=True)
    band = Column(String(16), nullable=False)                  # left|center-left|center|center-right|right
    score = Column(Float, nullable=False)                      # -1.0..+1.0
    heuristic_version = Column(String(16), nullable=False)
    rationale = Column(Text, nullable=False)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FactCheck(Base):
    __tablename__ = "fact_checks"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("wtf.articles.id"), nullable=False)
    claim = Column(Text, nullable=False)
    verdict = Column(String(32), nullable=False)               # true|mostly_true|mixed|false|unverified
    evidence = Column(Text, nullable=False)
    checker = Column(String(64), nullable=False)               # "heuristic-v1" for MVP
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditTrail(Base):
    __tablename__ = "audit_trail"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("wtf.articles.id"), nullable=False)
    event_type = Column(String(64), nullable=False)            # ingested|normalized|bias_scored|fact_checked|published
    payload = Column(JSON, nullable=False)                     # arbitrary diagnostic data
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FailedIngest(Base):
    __tablename__ = "failed_ingest"
    __table_args__ = {"schema": "wtf"}
    id = Column(Integer, primary_key=True)
    source_slug = Column(String(64), nullable=False)
    raw_payload = Column(JSON, nullable=False)
    error = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
```

- [ ] **Step 5: Write `shared/creed_events.py` stub**

```python
"""C.R.E.E.D. event emission — posts to ARCHIE governance channel."""
import os
import requests
import logging

logger = logging.getLogger(__name__)
CREED_URL = os.environ.get("CREED_EVENT_URL", "").rstrip("/")


def emit(event_type: str, payload: dict) -> bool:
    """Fire-and-forget CREED event. Returns True on HTTP 2xx, False otherwise."""
    if not CREED_URL:
        logger.debug("CREED_EVENT_URL not configured, skipping emit")
        return False
    try:
        r = requests.post(
            f"{CREED_URL}/events",
            json={"event_type": event_type, "payload": payload},
            timeout=3,
        )
        return 200 <= r.status_code < 300
    except Exception as exc:
        logger.warning("CREED emit failed: %s", exc)
        return False
```

- [ ] **Step 6: Write `.env.example`**

```
# Shared Postgres (read+write for ingest, read-only role for consumer/tech recommended)
WTF_DATABASE_URL=postgresql+psycopg2://archie:REPLACE_ME@192.168.1.200:5432/archie

# Kytran SSO (set on wtf-tech; wtf-consumer is guest-readable and can leave these unset)
KYTRAN_CLIENT_ID=wtf-tech
KYTRAN_CLIENT_SECRET=REPLACE_ME
KYTRAN_AUTH_URL=https://platform.kytranempowerment.com
KYTRAN_REDIRECT_URI=https://what-the-fact.tech/auth/kytran/callback

# CREED event emission
CREED_EVENT_URL=https://creed.kytranempowerment.com

# Flask
FLASK_SECRET_KEY=REPLACE_ME_WITH_32_RANDOM_BYTES
```

- [ ] **Step 7: Write `README.md`**

```markdown
# What The Fact

3-service stack for AI-powered transparent news.

## Services
- **wtf-consumer** (port 8103) — public reader at what-the-fact.com
- **wtf-tech** (port 8104) — transparency + developer portal at what-the-fact.tech
- **wtf-ingest** (internal) — RSS → canonical article → bias scoring → DB

## Development
1. `cp .env.example .env` and fill secrets
2. `docker compose up -d`
3. Visit http://localhost:8103

## Tests
`pip install -r requirements-dev.txt && pytest tests/`

## Deployment
Deployed to US Outpost (`76.13.107.109`) behind Caddy. See `docs/superpowers/specs/2026-04-18-wtf-thenews-consolidation-design.md`.
```

- [ ] **Step 8: Set up pytest + commit**

Create `what-the-fact/requirements.txt`:

```
Flask==3.0.0
SQLAlchemy==2.0.30
psycopg2-binary==2.9.9
feedparser==6.0.11
requests==2.32.3
python-dotenv==1.0.1
```

Create `what-the-fact/requirements-dev.txt`:

```
-r requirements.txt
pytest==8.2.0
pytest-flask==1.3.0
```

Commit:

```bash
cd /mnt/archie_brain
git checkout -b feat/wtf-consolidation
git add what-the-fact/
git commit -m "feat(wtf): scaffold 3-service stack + shared models"
```

---

### Task B2: Write the schema migration (test-first)

**Files:**
- Create: `what-the-fact/migrations/001_wtf_schema.sql`
- Create: `what-the-fact/tests/conftest.py`
- Create: `what-the-fact/tests/test_schema.py`

- [ ] **Step 1: Write `tests/conftest.py`**

```python
"""pytest fixtures: isolated DB per test using the `wtf_test` schema."""
import os
import pytest
from sqlalchemy import create_engine, text

TEST_DB_URL = os.environ.get(
    "WTF_TEST_DATABASE_URL",
    "postgresql+psycopg2://archie:archie@192.168.1.200:5432/archie",
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL, future=True)
    return eng


@pytest.fixture()
def clean_schema(engine):
    """Drop + recreate wtf_test schema, apply migration, yield."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS wtf_test CASCADE"))
        conn.execute(text("CREATE SCHEMA wtf_test"))
    # Apply migration with schema substitution
    with open("what-the-fact/migrations/001_wtf_schema.sql") as f:
        sql = f.read().replace("wtf.", "wtf_test.").replace("SCHEMA wtf", "SCHEMA wtf_test")
    with engine.begin() as conn:
        for stmt in sql.split(";\n"):
            if stmt.strip():
                conn.execute(text(stmt))
    yield
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS wtf_test CASCADE"))
```

- [ ] **Step 2: Write the failing test**

`what-the-fact/tests/test_schema.py`:

```python
"""Schema migration creates all expected tables with expected columns."""
from sqlalchemy import inspect


def test_all_tables_created(clean_schema, engine):
    insp = inspect(engine)
    tables = set(insp.get_table_names(schema="wtf_test"))
    assert tables == {
        "sources", "articles", "bias_scores",
        "fact_checks", "audit_trail", "failed_ingest",
    }


def test_articles_unique_external_id_per_source(clean_schema, engine):
    """Same external_id allowed across sources, duplicate within source rejected."""
    insp = inspect(engine)
    uqs = insp.get_unique_constraints("articles", schema="wtf_test")
    cols_sets = [tuple(sorted(u["column_names"])) for u in uqs]
    assert ("external_id", "source_id") in cols_sets
```

- [ ] **Step 3: Run to confirm failure**

```bash
cd /mnt/archie_brain && pytest what-the-fact/tests/test_schema.py -v 2>&1 | tail -10
```

Expected: fail — migration file doesn't exist yet.

- [ ] **Step 4: Write the migration**

`what-the-fact/migrations/001_wtf_schema.sql`:

```sql
-- WTF schema: articles, bias_scores, fact_checks, audit_trail, source_registry, failed_ingest
CREATE SCHEMA IF NOT EXISTS wtf;

CREATE TABLE IF NOT EXISTS wtf.sources (
    id         SERIAL PRIMARY KEY,
    slug       VARCHAR(64)  NOT NULL UNIQUE,
    name       VARCHAR(128) NOT NULL,
    url        VARCHAR(512) NOT NULL,
    country    VARCHAR(8)   NOT NULL DEFAULT 'CA',
    language   VARCHAR(8)   NOT NULL DEFAULT 'en',
    created_at TIMESTAMP    NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wtf.articles (
    id           SERIAL PRIMARY KEY,
    source_id    INTEGER       NOT NULL REFERENCES wtf.sources(id),
    external_id  VARCHAR(512)  NOT NULL,
    title        VARCHAR(1024) NOT NULL,
    body         TEXT          NOT NULL,
    url          VARCHAR(1024) NOT NULL,
    published_at TIMESTAMP     NOT NULL,
    ingested_at  TIMESTAMP     NOT NULL DEFAULT now(),
    CONSTRAINT articles_source_external_unique UNIQUE (source_id, external_id)
);
CREATE INDEX IF NOT EXISTS ix_articles_published_at ON wtf.articles (published_at DESC);

CREATE TABLE IF NOT EXISTS wtf.bias_scores (
    id                SERIAL PRIMARY KEY,
    article_id        INTEGER      NOT NULL UNIQUE REFERENCES wtf.articles(id) ON DELETE CASCADE,
    band              VARCHAR(16)  NOT NULL,
    score             REAL         NOT NULL,
    heuristic_version VARCHAR(16)  NOT NULL,
    rationale         TEXT         NOT NULL,
    computed_at       TIMESTAMP    NOT NULL DEFAULT now(),
    CONSTRAINT bias_band_check CHECK (band IN
        ('left','center-left','center','center-right','right'))
);

CREATE TABLE IF NOT EXISTS wtf.fact_checks (
    id         SERIAL PRIMARY KEY,
    article_id INTEGER      NOT NULL REFERENCES wtf.articles(id) ON DELETE CASCADE,
    claim      TEXT         NOT NULL,
    verdict    VARCHAR(32)  NOT NULL,
    evidence   TEXT         NOT NULL,
    checker    VARCHAR(64)  NOT NULL,
    checked_at TIMESTAMP    NOT NULL DEFAULT now(),
    CONSTRAINT fact_verdict_check CHECK (verdict IN
        ('true','mostly_true','mixed','false','unverified'))
);

CREATE TABLE IF NOT EXISTS wtf.audit_trail (
    id         SERIAL PRIMARY KEY,
    article_id INTEGER      NOT NULL REFERENCES wtf.articles(id) ON DELETE CASCADE,
    event_type VARCHAR(64)  NOT NULL,
    payload    JSONB        NOT NULL,
    created_at TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_article ON wtf.audit_trail (article_id);

CREATE TABLE IF NOT EXISTS wtf.failed_ingest (
    id          SERIAL PRIMARY KEY,
    source_slug VARCHAR(64) NOT NULL,
    raw_payload JSONB       NOT NULL,
    error       TEXT        NOT NULL,
    created_at  TIMESTAMP   NOT NULL DEFAULT now()
);
```

- [ ] **Step 5: Re-run the test to confirm it passes**

```bash
cd /mnt/archie_brain && pytest what-the-fact/tests/test_schema.py -v 2>&1 | tail -10
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add what-the-fact/migrations/001_wtf_schema.sql what-the-fact/tests/conftest.py what-the-fact/tests/test_schema.py
git commit -m "feat(wtf): schema migration + schema tests"
```

---

### Task B3: Ingest — CBC English RSS fetcher (test-first)

**Files:**
- Create: `what-the-fact/tests/fixtures/cbc_sample.xml` (frozen sample — ~5 articles)
- Create: `what-the-fact/tests/test_cbc_english.py`
- Create: `what-the-fact/ingest/sources/cbc_english.py`

- [ ] **Step 1: Create the frozen fixture**

Download once and commit:

```bash
curl -s "https://www.cbc.ca/cmlink/rss-topstories" -o /mnt/archie_brain/what-the-fact/tests/fixtures/cbc_sample.xml
head -c 500 /mnt/archie_brain/what-the-fact/tests/fixtures/cbc_sample.xml
```

Expected: starts with `<?xml` — it's RSS. If CBC ever changes format, test guards us.

- [ ] **Step 2: Write the failing test**

```python
# what-the-fact/tests/test_cbc_english.py
from ingest.sources.cbc_english import fetch_articles

FIXTURE = "what-the-fact/tests/fixtures/cbc_sample.xml"


def test_fetch_returns_dicts_with_expected_keys(monkeypatch):
    def fake_get(url, **kw):
        class R:
            status_code = 200
            content = open(FIXTURE, "rb").read()
        return R()

    monkeypatch.setattr("requests.get", fake_get)
    articles = fetch_articles()
    assert len(articles) >= 1
    for a in articles:
        assert set(a.keys()) >= {"external_id", "title", "body", "url", "published_at"}
        assert a["external_id"]
        assert a["url"].startswith("http")
```

- [ ] **Step 3: Run — confirm failure**

```bash
cd /mnt/archie_brain && pytest what-the-fact/tests/test_cbc_english.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: ingest.sources.cbc_english`.

- [ ] **Step 4: Write `ingest/sources/cbc_english.py`**

```python
"""CBC English top-stories RSS fetcher."""
from datetime import datetime
import logging
import feedparser
import requests

logger = logging.getLogger(__name__)
CBC_URL = "https://www.cbc.ca/cmlink/rss-topstories"
SOURCE_SLUG = "cbc_english"


def fetch_articles() -> list[dict]:
    """Fetch + parse. Returns list of raw article dicts (NOT canonicalized)."""
    resp = requests.get(CBC_URL, timeout=10, headers={"User-Agent": "WTF-Ingest/0.1"})
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    out = []
    for entry in feed.entries:
        pub = None
        if entry.get("published_parsed"):
            pub = datetime(*entry.published_parsed[:6])
        out.append({
            "external_id": entry.get("id") or entry.get("link"),
            "title":       entry.get("title", "").strip(),
            "body":        entry.get("summary", "").strip(),
            "url":         entry.get("link", ""),
            "published_at": pub or datetime.utcnow(),
        })
    logger.info("cbc_english: fetched %d articles", len(out))
    return out
```

- [ ] **Step 5: Run — confirm pass**

```bash
cd /mnt/archie_brain && pytest what-the-fact/tests/test_cbc_english.py -v 2>&1 | tail -10
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add what-the-fact/ingest/sources/cbc_english.py what-the-fact/tests/test_cbc_english.py what-the-fact/tests/fixtures/cbc_sample.xml
git commit -m "feat(wtf): CBC English RSS fetcher + frozen fixture"
```

---

### Task B4: Ingest — canonical normalizer (test-first)

**Files:**
- Create: `what-the-fact/tests/test_normalizer.py`
- Create: `what-the-fact/ingest/normalizer.py`

- [ ] **Step 1: Write the failing test**

```python
# what-the-fact/tests/test_normalizer.py
from datetime import datetime
from ingest.normalizer import canonicalize


def test_strips_html_from_body():
    raw = {"title": "T", "body": "<p>hello <b>world</b></p>", "url": "http://x",
           "external_id": "g-1", "published_at": datetime(2026, 4, 18)}
    out = canonicalize(raw)
    assert out["body"] == "hello world"


def test_truncates_title_to_1024():
    long = "x" * 2000
    raw = {"title": long, "body": "b", "url": "http://x",
           "external_id": "g-1", "published_at": datetime(2026, 4, 18)}
    out = canonicalize(raw)
    assert len(out["title"]) == 1024


def test_requires_external_id():
    import pytest
    raw = {"title": "T", "body": "b", "url": "http://x",
           "external_id": "", "published_at": datetime(2026, 4, 18)}
    with pytest.raises(ValueError, match="external_id"):
        canonicalize(raw)
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd /mnt/archie_brain && pytest what-the-fact/tests/test_normalizer.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Write `ingest/normalizer.py`**

```python
"""Canonicalize raw source-specific article dicts into a unified shape."""
import re
from html import unescape

_TAG_RE = re.compile(r"<[^>]+>")


def canonicalize(raw: dict) -> dict:
    if not raw.get("external_id"):
        raise ValueError("external_id required")
    if not raw.get("url"):
        raise ValueError("url required")
    body = unescape(_TAG_RE.sub("", raw.get("body") or "")).strip()
    body = re.sub(r"\s+", " ", body)
    title = (raw.get("title") or "").strip()[:1024]
    return {
        "external_id": raw["external_id"][:512],
        "title":       title,
        "body":        body,
        "url":         raw["url"][:1024],
        "published_at": raw["published_at"],
    }
```

- [ ] **Step 4: Run — confirm pass**

```bash
pytest what-the-fact/tests/test_normalizer.py -v 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add what-the-fact/ingest/normalizer.py what-the-fact/tests/test_normalizer.py
git commit -m "feat(wtf): canonical article normalizer"
```

---

### Task B5: Ingest — rule-based bias heuristic (golden-file TDD)

**Files:**
- Create: `what-the-fact/tests/fixtures/bias_golden.json` (10 labeled articles)
- Create: `what-the-fact/tests/test_bias.py`
- Create: `what-the-fact/ingest/bias.py`

- [ ] **Step 1: Write the golden fixture**

`what-the-fact/tests/fixtures/bias_golden.json`:

```json
[
  {"title": "Conservative government announces tax cut", "body": "The Conservative government today announced...", "expected_band": "center-right"},
  {"title": "NDP calls for higher minimum wage", "body": "The New Democratic Party leader demanded...", "expected_band": "center-left"},
  {"title": "Statistics Canada reports GDP growth of 2.3%", "body": "According to Statistics Canada, GDP grew by 2.3 percent in Q1", "expected_band": "center"},
  {"title": "Liberals propose new housing bill", "body": "The Liberal government has proposed a new bill to address housing", "expected_band": "center-left"},
  {"title": "Pipeline protest enters third week", "body": "Indigenous activists continue to block the pipeline access road", "expected_band": "center-left"},
  {"title": "Bank of Canada holds rates steady", "body": "The Bank of Canada announced today that it is holding interest rates unchanged", "expected_band": "center"},
  {"title": "Oil industry welcomes new federal incentives", "body": "The oil and gas industry praised the federal government's new tax incentives", "expected_band": "center-right"},
  {"title": "Climate scientists warn of 1.5C threshold", "body": "A new report from IPCC scientists warns the planet is approaching a 1.5 degree threshold", "expected_band": "center"},
  {"title": "Premier calls for reduced immigration", "body": "The premier today called for sharp reductions in federal immigration targets", "expected_band": "right"},
  {"title": "Union leaders praise new labour law", "body": "Labour unions hailed the new legislation that strengthens collective bargaining rights", "expected_band": "left"}
]
```

- [ ] **Step 2: Write the failing test**

```python
# what-the-fact/tests/test_bias.py
import json
from ingest.bias import score_bias

FIXTURE = "what-the-fact/tests/fixtures/bias_golden.json"


def test_golden_file_all_within_one_band():
    """Every golden article scores within 1 band of its expected label."""
    ORDER = ["left", "center-left", "center", "center-right", "right"]
    with open(FIXTURE) as f:
        items = json.load(f)
    failures = []
    for item in items:
        got = score_bias(item["title"], item["body"])
        expected = item["expected_band"]
        distance = abs(ORDER.index(got["band"]) - ORDER.index(expected))
        if distance > 1:
            failures.append(f"{item['title'][:50]!r}: expected {expected}, got {got['band']}")
    assert not failures, "golden-file drift:\n" + "\n".join(failures)


def test_returns_required_keys():
    out = score_bias("T", "body text")
    assert set(out.keys()) >= {"band", "score", "rationale", "heuristic_version"}
    assert -1.0 <= out["score"] <= 1.0
    assert out["heuristic_version"] == "v1"
```

- [ ] **Step 3: Run — confirm failure**

```bash
pytest what-the-fact/tests/test_bias.py -v 2>&1 | tail -10
```

- [ ] **Step 4: Write `ingest/bias.py`**

```python
"""Rule-based bias heuristic v1. Scores are -1.0 (left) to +1.0 (right)."""
import re

# Weighted trigger terms. Tuned against bias_golden.json fixture.
_TRIGGERS = {
    # negative = left-leaning
    "union":         -0.4, "unions":       -0.4, "labour":       -0.3,
    "collective bargaining": -0.5, "minimum wage": -0.4,
    "ndp":           -0.6, "new democratic": -0.6,
    "indigenous":    -0.3, "activists":    -0.3,
    # neutral
    "statistics canada": 0.0, "bank of canada": 0.0, "ipcc": 0.0, "scientists": 0.0,
    # positive = right-leaning
    "conservative":  0.5, "tax cut":       0.4, "tax cuts":      0.4,
    "oil and gas":   0.4, "oil industry":  0.4, "pipeline":      0.2,
    "reduced immigration": 0.7, "sharp reductions": 0.4,
    # slight center-left
    "liberal":      -0.2, "liberals":     -0.2, "housing bill": -0.2,
}

_BANDS = [
    (-0.6, "left"),
    (-0.2, "center-left"),
    (0.2,  "center"),
    (0.6,  "center-right"),
    (1.01, "right"),
]


def _band_for(score: float) -> str:
    for threshold, name in _BANDS:
        if score < threshold:
            return name
    return "right"


def score_bias(title: str, body: str) -> dict:
    text = (title + " " + body).lower()
    hits = []
    total = 0.0
    weight = 0.0
    for term, w in _TRIGGERS.items():
        if re.search(rf"\b{re.escape(term)}\b", text):
            hits.append(f"{term}({w:+.2f})")
            total += w
            weight += abs(w)
    score = total / weight if weight else 0.0
    score = max(-1.0, min(1.0, score))
    return {
        "band": _band_for(score),
        "score": round(score, 3),
        "rationale": "triggers: " + (", ".join(hits) if hits else "none — defaulted center"),
        "heuristic_version": "v1",
    }
```

- [ ] **Step 5: Iterate weights until golden-file passes**

```bash
pytest what-the-fact/tests/test_bias.py -v 2>&1 | tail -10
```

If any golden item fails by more than one band, tune the weight for its distinguishing term and retry. Do NOT weaken the assertion. This is the whole point of the golden file.

- [ ] **Step 6: Commit**

```bash
git add what-the-fact/ingest/bias.py what-the-fact/tests/test_bias.py what-the-fact/tests/fixtures/bias_golden.json
git commit -m "feat(wtf): rule-based bias heuristic v1 w/ golden-file tests"
```

---

### Task B6: Ingest — DB persist + dead-letter (test-first)

**Files:**
- Create: `what-the-fact/tests/test_persist.py`
- Create: `what-the-fact/ingest/persist.py`

- [ ] **Step 1: Write the failing test**

```python
# what-the-fact/tests/test_persist.py
from datetime import datetime
from sqlalchemy import text
from ingest.persist import upsert_article, record_failure


def _source_id(engine, slug):
    with engine.begin() as c:
        r = c.execute(text(
            "INSERT INTO wtf_test.sources (slug, name, url) VALUES (:s, :n, :u) RETURNING id"
        ), {"s": slug, "n": slug, "u": "http://x"})
        return r.scalar()


def test_upsert_inserts_then_dedupes(clean_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    sid = _source_id(engine, "test")
    art = {"external_id": "g-1", "title": "T", "body": "b",
           "url": "http://x", "published_at": datetime(2026, 4, 18)}
    bias = {"band": "center", "score": 0.0, "heuristic_version": "v1", "rationale": "none"}
    assert upsert_article(engine, sid, art, bias) is True   # inserted
    assert upsert_article(engine, sid, art, bias) is False  # dedupe no-op

    with engine.begin() as c:
        cnt = c.execute(text("SELECT COUNT(*) FROM wtf_test.articles")).scalar()
    assert cnt == 1


def test_record_failure_writes_to_failed_ingest(clean_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    record_failure(engine, "cbc_english", {"bad": "payload"}, "parser crashed: X")
    with engine.begin() as c:
        r = c.execute(text("SELECT source_slug, error FROM wtf_test.failed_ingest")).fetchone()
    assert r[0] == "cbc_english"
    assert "parser crashed" in r[1]
```

- [ ] **Step 2: Run — confirm failure**

- [ ] **Step 3: Write `ingest/persist.py`**

```python
"""DB writes: upsert articles + bias scores + audit trail. Dead-letter on failure."""
import json
import logging
import os
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _schema() -> str:
    return os.environ.get("WTF_SCHEMA", "wtf")


def upsert_article(engine, source_id: int, article: dict, bias: dict) -> bool:
    """Insert article + bias_score + audit entry in one tx. Returns True on insert, False on dedupe."""
    S = _schema()
    with engine.begin() as c:
        r = c.execute(text(f"""
            INSERT INTO {S}.articles (source_id, external_id, title, body, url, published_at)
            VALUES (:sid, :eid, :t, :b, :u, :p)
            ON CONFLICT (source_id, external_id) DO NOTHING
            RETURNING id
        """), {
            "sid": source_id, "eid": article["external_id"], "t": article["title"],
            "b": article["body"], "u": article["url"], "p": article["published_at"],
        })
        row = r.fetchone()
        if not row:
            return False
        aid = row[0]
        c.execute(text(f"""
            INSERT INTO {S}.bias_scores (article_id, band, score, heuristic_version, rationale)
            VALUES (:aid, :band, :score, :v, :rat)
        """), {"aid": aid, "band": bias["band"], "score": bias["score"],
               "v": bias["heuristic_version"], "rat": bias["rationale"]})
        c.execute(text(f"""
            INSERT INTO {S}.audit_trail (article_id, event_type, payload)
            VALUES (:aid, 'ingested', :p)
        """), {"aid": aid, "p": json.dumps({"source_id": source_id, "bias": bias})})
    return True


def record_failure(engine, source_slug: str, raw: dict, error: str) -> None:
    S = _schema()
    with engine.begin() as c:
        c.execute(text(f"""
            INSERT INTO {S}.failed_ingest (source_slug, raw_payload, error)
            VALUES (:s, :r, :e)
        """), {"s": source_slug, "r": json.dumps(raw, default=str), "e": error})
    logger.warning("dead-letter: %s - %s", source_slug, error[:100])
```

- [ ] **Step 4: Run — confirm pass**

- [ ] **Step 5: Commit**

```bash
git add what-the-fact/ingest/persist.py what-the-fact/tests/test_persist.py
git commit -m "feat(wtf): ingest persist + dead-letter"
```

---

### Task B7: Ingest — main loop (`run.py`) + Dockerfile

**Files:**
- Create: `what-the-fact/ingest/run.py`
- Create: `what-the-fact/Dockerfile.ingest`

- [ ] **Step 1: Write `ingest/run.py`**

```python
"""Entry point for wtf-ingest. Polls each source hourly, normalizes, scores, persists."""
import logging
import os
import time
from sqlalchemy import create_engine, text

from ingest.sources.cbc_english import fetch_articles as cbc_fetch, SOURCE_SLUG as CBC_SLUG
from ingest.normalizer import canonicalize
from ingest.bias import score_bias
from ingest.persist import upsert_article, record_failure
from shared.creed_events import emit as creed_emit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wtf-ingest")
POLL_SECS = int(os.environ.get("WTF_POLL_SECS", "3600"))


def _ensure_source(engine, slug, name, url) -> int:
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO wtf.sources (slug, name, url) VALUES (:s, :n, :u)
            ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name, url=EXCLUDED.url
        """), {"s": slug, "n": name, "u": url})
        return c.execute(text("SELECT id FROM wtf.sources WHERE slug=:s"), {"s": slug}).scalar()


def run_once(engine) -> dict:
    """Run one ingestion pass across all sources. Returns stats dict."""
    stats = {"inserted": 0, "skipped": 0, "failed": 0}
    sid = _ensure_source(engine, CBC_SLUG, "CBC English Top Stories",
                          "https://www.cbc.ca/cmlink/rss-topstories")
    try:
        raw_articles = cbc_fetch()
    except Exception as exc:
        log.exception("cbc fetch failed")
        record_failure(engine, CBC_SLUG, {}, f"fetch: {exc}")
        stats["failed"] += 1
        return stats
    for raw in raw_articles:
        try:
            article = canonicalize(raw)
            bias = score_bias(article["title"], article["body"])
            inserted = upsert_article(engine, sid, article, bias)
            if inserted:
                stats["inserted"] += 1
                creed_emit("wtf.article.ingested", {
                    "source": CBC_SLUG, "url": article["url"], "bias": bias["band"],
                })
            else:
                stats["skipped"] += 1
        except Exception as exc:
            log.exception("article failed: %s", raw.get("url"))
            record_failure(engine, CBC_SLUG, raw, str(exc))
            stats["failed"] += 1
    log.info("run_once: %s", stats)
    return stats


def main():
    engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    while True:
        try:
            run_once(engine)
        except Exception:
            log.exception("run_once crashed — sleeping and retrying")
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `Dockerfile.ingest`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ /app/shared/
COPY ingest/ /app/ingest/
COPY migrations/ /app/migrations/
ENV PYTHONPATH=/app
USER nobody
CMD ["python", "-m", "ingest.run"]
```

- [ ] **Step 3: Smoke test locally**

```bash
cd /mnt/archie_brain/what-the-fact
docker build -f Dockerfile.ingest -t wtf-ingest:dev . && \
docker run --rm --env-file .env -e WTF_POLL_SECS=999999 wtf-ingest:dev python -c "
from sqlalchemy import create_engine
import os
from ingest.run import run_once
print(run_once(create_engine(os.environ['WTF_DATABASE_URL'])))
" 2>&1 | tail -20
```

Expected: dict like `{'inserted': N, 'skipped': 0, 'failed': 0}` with N > 0.

- [ ] **Step 4: Commit**

```bash
git add what-the-fact/ingest/run.py what-the-fact/Dockerfile.ingest
git commit -m "feat(wtf): ingest main loop + Dockerfile"
```

---

### Task B8: Consumer — Flask app + list view (test-first)

**Files:**
- Create: `what-the-fact/consumer/app.py`
- Create: `what-the-fact/consumer/routes.py`
- Create: `what-the-fact/consumer/templates/base.html`
- Create: `what-the-fact/consumer/templates/index.html`
- Create: `what-the-fact/consumer/static/style.css`
- Create: `what-the-fact/tests/test_consumer_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# what-the-fact/tests/test_consumer_routes.py
import os
from datetime import datetime
import pytest
from sqlalchemy import text

from consumer.app import create_app
from ingest.persist import upsert_article


@pytest.fixture()
def app(clean_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    # seed a source + article
    with engine.begin() as c:
        c.execute(text("INSERT INTO wtf_test.sources (slug, name, url) VALUES ('t', 'T', 'http://x')"))
        sid = c.execute(text("SELECT id FROM wtf_test.sources WHERE slug='t'")).scalar()
    upsert_article(engine, sid,
        {"external_id": "g-1", "title": "Headline one", "body": "body",
         "url": "http://x/1", "published_at": datetime(2026, 4, 18)},
        {"band": "center", "score": 0.0, "heuristic_version": "v1", "rationale": "none"})
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def test_index_lists_article(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Headline one" in r.data
    assert b"center" in r.data  # bias band badge
```

- [ ] **Step 2: Write `consumer/app.py`**

```python
from flask import Flask
from .routes import bp


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    import os
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev")
    app.register_blueprint(bp)
    return app
```

- [ ] **Step 3: Write `consumer/routes.py`**

```python
import os
from flask import Blueprint, render_template, abort
from sqlalchemy import create_engine, text

bp = Blueprint("wtf", __name__)
_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _schema():
    return os.environ.get("WTF_SCHEMA", "wtf")


@bp.get("/")
def index():
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, s.name AS source, b.band
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            ORDER BY a.published_at DESC LIMIT 50
        """)).mappings().all()
    return render_template("index.html", articles=rows)


@bp.get("/article/<int:article_id>")
def article(article_id: int):
    S = _schema()
    with _db().begin() as c:
        row = c.execute(text(f"""
            SELECT a.id, a.title, a.body, a.url, a.published_at,
                   s.name AS source, b.band, b.score, b.rationale
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
    if not row:
        abort(404)
    return render_template("article.html", a=row)
```

- [ ] **Step 4: Write templates**

`consumer/templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}What The Fact{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <header class="wtf-header">
    <a href="/" class="wtf-brand">What The Fact</a>
    <nav><a href="https://what-the-fact.tech">Transparency</a></nav>
  </header>
  <main>{% block content %}{% endblock %}</main>
  <footer class="wtf-footer">
    <span>Built on radical transparency. <a href="https://what-the-fact.tech">How we score bias →</a></span>
  </footer>
</body>
</html>
```

`consumer/templates/index.html`:

```html
{% extends "base.html" %}
{% block content %}
<ul class="wtf-list">
{% for a in articles %}
  <li>
    <a href="/article/{{ a.id }}">{{ a.title }}</a>
    <span class="wtf-source">{{ a.source }}</span>
    <span class="wtf-bias wtf-bias-{{ a.band }}">{{ a.band }}</span>
    <time>{{ a.published_at.strftime('%Y-%m-%d') }}</time>
  </li>
{% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 5: Write basic CSS (Watch-series palette)**

`consumer/static/style.css`:

```css
:root {
  --wtf-bg: #0b0d12;
  --wtf-fg: #d9dde6;
  --wtf-accent: #64d2ff;
  --wtf-border: #1e2330;
}
body { margin: 0; font-family: -apple-system, system-ui, Segoe UI, sans-serif;
       background: var(--wtf-bg); color: var(--wtf-fg); }
.wtf-header { display: flex; justify-content: space-between; padding: 1rem 2rem;
              border-bottom: 1px solid var(--wtf-border); }
.wtf-brand { color: var(--wtf-accent); font-weight: 600; text-decoration: none; }
.wtf-list { list-style: none; padding: 1rem 2rem; }
.wtf-list li { padding: .75rem 0; border-bottom: 1px solid var(--wtf-border); }
.wtf-list a { color: var(--wtf-fg); text-decoration: none; font-weight: 500; }
.wtf-source { margin-left: .75rem; opacity: .7; font-size: .85em; }
.wtf-bias { margin-left: .75rem; padding: .15em .5em; border-radius: 3px;
            font-size: .75em; text-transform: uppercase; }
.wtf-bias-left        { background: #3b5aa3; }
.wtf-bias-center-left { background: #5578b8; }
.wtf-bias-center      { background: #6b7280; }
.wtf-bias-center-right{ background: #b87c55; }
.wtf-bias-right       { background: #a33b3b; }
.wtf-footer { padding: 2rem; border-top: 1px solid var(--wtf-border); opacity: .7; font-size: .85em; }
```

- [ ] **Step 6: Run — confirm pass**

```bash
pytest what-the-fact/tests/test_consumer_routes.py -v 2>&1 | tail -10
```

- [ ] **Step 7: Commit**

```bash
git add what-the-fact/consumer/ what-the-fact/tests/test_consumer_routes.py
git commit -m "feat(wtf): consumer Flask app + list view"
```

---

### Task B9: Consumer — article detail view (test-first)

**Files:**
- Create: `what-the-fact/consumer/templates/article.html`
- Modify: `what-the-fact/tests/test_consumer_routes.py` — add detail test

- [ ] **Step 1: Add the failing test**

Append to `test_consumer_routes.py`:

```python
def test_detail_renders(client):
    r = client.get("/article/1")
    assert r.status_code == 200
    assert b"Headline one" in r.data
    assert b"body" in r.data


def test_detail_404(client):
    r = client.get("/article/999999")
    assert r.status_code == 404
```

- [ ] **Step 2: Confirm failure**

```bash
pytest what-the-fact/tests/test_consumer_routes.py -v 2>&1 | tail -10
```

Expected: `template 'article.html' not found`.

- [ ] **Step 3: Write `consumer/templates/article.html`**

```html
{% extends "base.html" %}
{% block title %}{{ a.title }} — What The Fact{% endblock %}
{% block content %}
<article class="wtf-article">
  <h1>{{ a.title }}</h1>
  <p class="wtf-meta">
    <span class="wtf-source">{{ a.source }}</span> ·
    <time>{{ a.published_at.strftime('%Y-%m-%d %H:%M') }}</time> ·
    {% if a.band %}
      <span class="wtf-bias wtf-bias-{{ a.band }}">{{ a.band }}</span>
      ({{ "%.2f"|format(a.score) }})
    {% endif %}
  </p>
  <div class="wtf-body">{{ a.body }}</div>
  {% if a.rationale %}
    <aside class="wtf-transparency">
      <strong>Why this bias band?</strong> {{ a.rationale }}
      <a href="https://what-the-fact.tech/transparency/{{ a.id }}">Full audit trail →</a>
    </aside>
  {% endif %}
  <p class="wtf-source-link"><a href="{{ a.url }}" rel="noopener" target="_blank">Read at source →</a></p>
</article>
{% endblock %}
```

- [ ] **Step 4: Confirm pass**

- [ ] **Step 5: Commit**

```bash
git add what-the-fact/consumer/templates/article.html what-the-fact/tests/test_consumer_routes.py
git commit -m "feat(wtf): consumer article detail view"
```

---

### Task B10: Consumer — Dockerfile + gunicorn

**Files:**
- Create: `what-the-fact/Dockerfile.consumer`
- Modify: `what-the-fact/requirements.txt` — add `gunicorn==21.2.0`

- [ ] **Step 1: Append to `requirements.txt`**

```
gunicorn==21.2.0
```

- [ ] **Step 2: Write `Dockerfile.consumer`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ /app/shared/
COPY consumer/ /app/consumer/
ENV PYTHONPATH=/app
EXPOSE 8103
USER nobody
CMD ["gunicorn", "--bind", "0.0.0.0:8103", "--workers", "2", "--access-logfile", "-", "consumer.app:create_app()"]
```

- [ ] **Step 3: Smoke-build**

```bash
cd /mnt/archie_brain/what-the-fact
docker build -f Dockerfile.consumer -t wtf-consumer:dev .
docker run --rm -d --name wtf-consumer-test --env-file .env -p 18103:8103 wtf-consumer:dev
sleep 2 && curl -sI http://localhost:18103/ | head -3 && docker stop wtf-consumer-test
```

Expected: HTTP 200 with `Content-Type: text/html`.

- [ ] **Step 4: Commit**

```bash
git add what-the-fact/Dockerfile.consumer what-the-fact/requirements.txt
git commit -m "feat(wtf): consumer Dockerfile"
```

---

### Task B11: Tech — Flask app + Kytran SSO + transparency view (test-first)

**Files:**
- Create: `what-the-fact/tech/app.py`
- Create: `what-the-fact/tech/routes.py`
- Create: `what-the-fact/tech/templates/base.html`
- Create: `what-the-fact/tech/templates/index.html`
- Create: `what-the-fact/tech/templates/transparency.html`
- Create: `what-the-fact/tech/templates/dashboard.html`
- Create: `what-the-fact/tech/static/style.css`
- Create: `what-the-fact/tests/test_tech_sso.py`

- [ ] **Step 1: Write the failing test**

```python
# what-the-fact/tests/test_tech_sso.py
import pytest
from tech.app import create_app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("KYTRAN_CLIENT_ID", "wtf-tech")
    monkeypatch.setenv("KYTRAN_CLIENT_SECRET", "s")
    monkeypatch.setenv("KYTRAN_AUTH_URL", "https://platform.kytranempowerment.com")
    monkeypatch.setenv("KYTRAN_REDIRECT_URI", "https://what-the-fact.tech/auth/kytran/callback")
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_index_public(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"radical transparency" in r.data.lower() or b"transparent" in r.data.lower()


def test_dashboard_requires_sso(client):
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 301)
    assert "/auth/kytran/login" in r.location


def test_login_redirects_to_oauth(client):
    r = client.get("/auth/kytran/login", follow_redirects=False)
    assert r.status_code == 302
    assert "platform.kytranempowerment.com" in r.location
    assert "client_id=wtf-tech" in r.location
```

- [ ] **Step 2: Write `tech/app.py`**

```python
from flask import Flask
from shared.kytran_auth import KytranAuth
from .routes import bp


def create_app():
    import os
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev")
    KytranAuth(app)
    app.register_blueprint(bp)
    return app
```

- [ ] **Step 3: Write `tech/routes.py`**

```python
import os
from flask import Blueprint, render_template, session, abort, redirect, url_for
from sqlalchemy import create_engine, text

bp = Blueprint("wtf_tech", __name__)
_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _schema():
    return os.environ.get("WTF_SCHEMA", "wtf")


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/transparency/<int:article_id>")
def transparency(article_id: int):
    S = _schema()
    with _db().begin() as c:
        art = c.execute(text(f"""
            SELECT a.id, a.title, a.url, b.band, b.score, b.rationale, b.heuristic_version
            FROM {S}.articles a LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
        if not art:
            abort(404)
        trail = c.execute(text(f"""
            SELECT event_type, payload, created_at FROM {S}.audit_trail
            WHERE article_id = :id ORDER BY created_at
        """), {"id": article_id}).mappings().all()
    return render_template("transparency.html", a=art, trail=trail)


@bp.get("/dashboard")
def dashboard():
    if "kytran_user" not in session:
        return redirect(url_for("kytran_login", next="/dashboard"))
    return render_template("dashboard.html", user=session["kytran_user"])
```

- [ ] **Step 4: Write `tech/templates/base.html`** — same structure as consumer `base.html` but with tech branding (nav link back to consumer, different accent color e.g. `--wtf-accent: #a78bfa`).

- [ ] **Step 5: Write `tech/templates/index.html`**

```html
{% extends "base.html" %}
{% block content %}
<section class="wtf-hero">
  <h1>Radical transparency in AI news.</h1>
  <p>Every article scored, every decision audited, every source documented.
     Sign in with Kytran Empowerment for API access.</p>
  <a class="wtf-btn" href="/auth/kytran/login?next=/dashboard">Sign in with Kytran Empowerment</a>
</section>
<section class="wtf-methodology">
  <h2>How we score bias</h2>
  <p>WTF uses heuristic v1 — weighted keyword triggers calibrated against a 10-article golden
     file of Canadian political coverage. Full methodology →
     <a href="https://github.com/KytranKatarn/archie-platform">source</a>.</p>
</section>
{% endblock %}
```

- [ ] **Step 6: Write `tech/templates/transparency.html`**

```html
{% extends "base.html" %}
{% block content %}
<article class="wtf-transparency">
  <h1>{{ a.title }}</h1>
  <p><a href="{{ a.url }}">Source article</a></p>
  <section>
    <h2>Bias score</h2>
    <p><span class="wtf-bias wtf-bias-{{ a.band }}">{{ a.band }}</span>
       score: {{ "%.2f"|format(a.score) }} · heuristic: {{ a.heuristic_version }}</p>
    <blockquote>{{ a.rationale }}</blockquote>
  </section>
  <section>
    <h2>Audit trail</h2>
    <ol>
    {% for e in trail %}
      <li><time>{{ e.created_at.isoformat() }}</time>
          <strong>{{ e.event_type }}</strong>
          <pre>{{ e.payload|tojson(indent=2) }}</pre></li>
    {% endfor %}
    </ol>
  </section>
</article>
{% endblock %}
```

- [ ] **Step 7: Write `tech/templates/dashboard.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Developer Dashboard</h1>
<p>Welcome, {{ user.name or user.username }}.</p>
<h2>Read-only API</h2>
<pre>GET /api/v1/articles?limit=50
GET /api/v1/articles/&lt;id&gt;
GET /api/v1/articles/&lt;id&gt;/audit</pre>
{% endblock %}
```

- [ ] **Step 8: Run — confirm pass**

```bash
pytest what-the-fact/tests/test_tech_sso.py -v 2>&1 | tail -10
```

- [ ] **Step 9: Commit**

```bash
git add what-the-fact/tech/ what-the-fact/tests/test_tech_sso.py
git commit -m "feat(wtf): tech app w/ SSO + transparency portal"
```

---

### Task B12: Tech — read-only API (test-first, contract tests)

**Files:**
- Create: `what-the-fact/tech/api.py`
- Modify: `what-the-fact/tech/app.py` — register api blueprint
- Create: `what-the-fact/tests/test_tech_api.py`

- [ ] **Step 1: Write the failing test**

```python
# what-the-fact/tests/test_tech_api.py
from datetime import datetime
import pytest
from sqlalchemy import text
from tech.app import create_app
from ingest.persist import upsert_article


@pytest.fixture()
def client(clean_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("KYTRAN_CLIENT_ID", "wtf-tech")
    monkeypatch.setenv("KYTRAN_CLIENT_SECRET", "s")
    monkeypatch.setenv("KYTRAN_AUTH_URL", "https://platform.kytranempowerment.com")
    monkeypatch.setenv("KYTRAN_REDIRECT_URI", "https://what-the-fact.tech/auth/kytran/callback")
    with engine.begin() as c:
        c.execute(text("INSERT INTO wtf_test.sources (slug, name, url) VALUES ('t','T','http://x')"))
        sid = c.execute(text("SELECT id FROM wtf_test.sources WHERE slug='t'")).scalar()
    upsert_article(engine, sid,
        {"external_id": "g-1", "title": "API test", "body": "b",
         "url": "http://x/1", "published_at": datetime(2026, 4, 18)},
        {"band": "center", "score": 0.0, "heuristic_version": "v1", "rationale": "none"})
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_api_list_shape(client):
    r = client.get("/api/v1/articles?limit=50")
    assert r.status_code == 200
    data = r.get_json()
    assert "articles" in data and isinstance(data["articles"], list)
    a = data["articles"][0]
    assert set(a.keys()) >= {"id", "title", "url", "published_at", "source", "bias"}


def test_api_detail_shape(client):
    r = client.get("/api/v1/articles/1")
    assert r.status_code == 200
    data = r.get_json()
    assert data["id"] == 1
    assert "bias" in data and "band" in data["bias"]


def test_api_audit_shape(client):
    r = client.get("/api/v1/articles/1/audit")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data["events"], list) and len(data["events"]) >= 1


def test_api_404(client):
    r = client.get("/api/v1/articles/999999")
    assert r.status_code == 404
```

- [ ] **Step 2: Write `tech/api.py`**

```python
import os
from flask import Blueprint, jsonify, request
from sqlalchemy import create_engine, text

api = Blueprint("wtf_api", __name__, url_prefix="/api/v1")
_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _schema():
    return os.environ.get("WTF_SCHEMA", "wtf")


@api.get("/articles")
def list_articles():
    limit = min(int(request.args.get("limit", 50)), 200)
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, s.name AS source,
                   b.band, b.score
            FROM {S}.articles a JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            ORDER BY a.published_at DESC LIMIT :n
        """), {"n": limit}).mappings().all()
    return jsonify({"articles": [{
        "id": r["id"], "title": r["title"], "url": r["url"],
        "published_at": r["published_at"].isoformat(), "source": r["source"],
        "bias": {"band": r["band"], "score": r["score"]} if r["band"] else None,
    } for r in rows]})


@api.get("/articles/<int:article_id>")
def get_article(article_id: int):
    S = _schema()
    with _db().begin() as c:
        r = c.execute(text(f"""
            SELECT a.id, a.title, a.body, a.url, a.published_at, s.name AS source,
                   b.band, b.score, b.rationale, b.heuristic_version
            FROM {S}.articles a JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
    if not r:
        return jsonify({"error": "not_found"}), 404
    return jsonify({
        "id": r["id"], "title": r["title"], "body": r["body"], "url": r["url"],
        "published_at": r["published_at"].isoformat(), "source": r["source"],
        "bias": {"band": r["band"], "score": r["score"], "rationale": r["rationale"],
                 "heuristic_version": r["heuristic_version"]} if r["band"] else None,
    })


@api.get("/articles/<int:article_id>/audit")
def get_audit(article_id: int):
    S = _schema()
    with _db().begin() as c:
        exists = c.execute(text(f"SELECT 1 FROM {S}.articles WHERE id=:id"), {"id": article_id}).scalar()
        if not exists:
            return jsonify({"error": "not_found"}), 404
        rows = c.execute(text(f"""
            SELECT event_type, payload, created_at FROM {S}.audit_trail
            WHERE article_id = :id ORDER BY created_at
        """), {"id": article_id}).mappings().all()
    return jsonify({"events": [{
        "event_type": r["event_type"], "payload": r["payload"],
        "at": r["created_at"].isoformat(),
    } for r in rows]})
```

- [ ] **Step 3: Register in `tech/app.py`**

Edit `tech/app.py` — add after `app.register_blueprint(bp)`:

```python
    from .api import api
    app.register_blueprint(api)
```

- [ ] **Step 4: Confirm pass**

```bash
pytest what-the-fact/tests/test_tech_api.py -v 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add what-the-fact/tech/api.py what-the-fact/tech/app.py what-the-fact/tests/test_tech_api.py
git commit -m "feat(wtf): tech read-only API v1"
```

---

### Task B13: Tech — Dockerfile + compose

**Files:**
- Create: `what-the-fact/Dockerfile.tech`
- Create: `what-the-fact/docker-compose.yml`

- [ ] **Step 1: Write `Dockerfile.tech`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ /app/shared/
COPY tech/ /app/tech/
ENV PYTHONPATH=/app
EXPOSE 8104
USER nobody
CMD ["gunicorn", "--bind", "0.0.0.0:8104", "--workers", "2", "--access-logfile", "-", "tech.app:create_app()"]
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
services:
  wtf-ingest:
    build: { context: ., dockerfile: Dockerfile.ingest }
    image: ghcr.io/kytrankatarn/wtf-ingest:0.1.0
    restart: unless-stopped
    env_file: [.env]
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    mem_limit: 512m
    cpus: 0.5

  wtf-consumer:
    build: { context: ., dockerfile: Dockerfile.consumer }
    image: ghcr.io/kytrankatarn/wtf-consumer:0.1.0
    restart: unless-stopped
    env_file: [.env]
    ports: ["8103:8103"]
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    mem_limit: 512m
    cpus: 0.5

  wtf-tech:
    build: { context: ., dockerfile: Dockerfile.tech }
    image: ghcr.io/kytrankatarn/wtf-tech:0.1.0
    restart: unless-stopped
    env_file: [.env]
    ports: ["8104:8104"]
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    mem_limit: 512m
    cpus: 0.5
```

- [ ] **Step 3: Smoke test full stack locally**

```bash
cd /mnt/archie_brain/what-the-fact
docker compose build && docker compose up -d
sleep 5
curl -sI http://localhost:8103/ | head -3
curl -sI http://localhost:8104/ | head -3
docker compose down
```

Expected: both HTTP 200.

- [ ] **Step 4: Commit**

```bash
git add what-the-fact/Dockerfile.tech what-the-fact/docker-compose.yml
git commit -m "feat(wtf): tech Dockerfile + 3-service docker-compose"
```

---

## Phase C — Deploy to VPS (blocked by Phase B)

### Task C1: Seed OAuth clients for WTF (migration 306)

**Files:**
- Create: `database/migrations/306_wtf_oauth_clients.sql`

- [ ] **Step 1: Write migration**

```sql
-- Migration 306: Replace 'news' OAuth client with WTF clients
-- Idempotent: ON CONFLICT DO UPDATE, and deactivate obsolete 'news' client

UPDATE oauth_clients SET is_active = false WHERE client_id = 'news';

INSERT INTO oauth_clients (client_id, client_secret, redirect_uri, name, is_active)
VALUES
    ('wtf-consumer', encode(gen_random_bytes(32), 'hex'),
     'https://what-the-fact.com/auth/kytran/callback', 'What The Fact Consumer', true),
    ('wtf-tech',     encode(gen_random_bytes(32), 'hex'),
     'https://what-the-fact.tech/auth/kytran/callback', 'What The Fact Tech', true)
ON CONFLICT (client_id) DO UPDATE SET
    redirect_uri = EXCLUDED.redirect_uri,
    name         = EXCLUDED.name,
    is_active    = EXCLUDED.is_active;
```

- [ ] **Step 2: Apply on hub DB**

```bash
docker exec -i archie_database psql -U archie -d archie \
  < /mnt/archie_brain/database/migrations/306_wtf_oauth_clients.sql
```

Expected: `INSERT 0 2`, `UPDATE 1`.

- [ ] **Step 3: Extract the wtf-tech client_secret for VPS env**

```bash
docker exec archie_database psql -U archie -d archie -tAc \
  "SELECT client_secret FROM oauth_clients WHERE client_id='wtf-tech'"
```

Record the secret. Save to hub secrets store (e.g., the `.env` file that the VPS syncs from, NOT to git).

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add database/migrations/306_wtf_oauth_clients.sql
git commit -m "feat(oauth): seed wtf-consumer + wtf-tech clients, deactivate news"
```

---

### Task C2: Apply WTF schema migration on shared hub DB

**Files:** None — applies `what-the-fact/migrations/001_wtf_schema.sql` to the hub DB.

- [ ] **Step 1: Apply**

```bash
docker cp /mnt/archie_brain/what-the-fact/migrations/001_wtf_schema.sql \
  archie_database:/tmp/wtf_001.sql
docker exec archie_database psql -U archie -d archie -f /tmp/wtf_001.sql
```

Expected: `CREATE SCHEMA`, `CREATE TABLE` × 6, `CREATE INDEX` × 2.

- [ ] **Step 2: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt wtf.*"
```

Expected: 6 tables listed.

- [ ] **Step 3: Commit (no code change — log in KB)**

Use `mcp__archie__store_memory`:
- memory_type: `vault_note`
- category: `database`
- content: `"WTF schema applied to hub DB 2026-04-18. Tables: wtf.{sources, articles, bias_scores, fact_checks, audit_trail, failed_ingest}. Migration file: what-the-fact/migrations/001_wtf_schema.sql"`

---

### Task C3: Push WTF stack to VPS + wire compose

**Files:**
- Modify on VPS: `/root/archie-outpost/docker-compose.yml` — add 3 WTF services
- Create on VPS: `/root/archie-outpost/wtf/.env`

- [ ] **Step 1: Build + push images to registry**

```bash
cd /mnt/archie_brain/what-the-fact
docker build -f Dockerfile.ingest   -t ghcr.io/kytrankatarn/wtf-ingest:0.1.0   .
docker build -f Dockerfile.consumer -t ghcr.io/kytrankatarn/wtf-consumer:0.1.0 .
docker build -f Dockerfile.tech     -t ghcr.io/kytrankatarn/wtf-tech:0.1.0     .
docker push ghcr.io/kytrankatarn/wtf-ingest:0.1.0
docker push ghcr.io/kytrankatarn/wtf-consumer:0.1.0
docker push ghcr.io/kytrankatarn/wtf-tech:0.1.0
```

- [ ] **Step 2: Write VPS `.env` via SSH (interactive heredoc)**

```bash
ssh root@76.13.107.109 'mkdir -p /root/archie-outpost/wtf && cat > /root/archie-outpost/wtf/.env' <<EOF
WTF_DATABASE_URL=postgresql+psycopg2://archie:REPLACE_WITH_DB_PASSWORD@192.168.1.200:5432/archie
KYTRAN_CLIENT_ID=wtf-tech
KYTRAN_CLIENT_SECRET=REPLACE_WITH_SECRET_FROM_C1_STEP_3
KYTRAN_AUTH_URL=https://platform.kytranempowerment.com
KYTRAN_REDIRECT_URI=https://what-the-fact.tech/auth/kytran/callback
CREED_EVENT_URL=https://creed.kytranempowerment.com
FLASK_SECRET_KEY=$(openssl rand -hex 32)
WTF_POLL_SECS=3600
EOF
```

Replace `REPLACE_WITH_...` inline before running.

- [ ] **Step 3: Add services to VPS compose**

SSH in, edit `/root/archie-outpost/docker-compose.yml`, append:

```yaml
  wtf-ingest:
    image: ghcr.io/kytrankatarn/wtf-ingest:0.1.0
    restart: unless-stopped
    env_file: /root/archie-outpost/wtf/.env
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    mem_limit: 512m

  wtf-consumer:
    image: ghcr.io/kytrankatarn/wtf-consumer:0.1.0
    restart: unless-stopped
    env_file: /root/archie-outpost/wtf/.env
    ports: ["8103:8103"]
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    mem_limit: 512m

  wtf-tech:
    image: ghcr.io/kytrankatarn/wtf-tech:0.1.0
    restart: unless-stopped
    env_file: /root/archie-outpost/wtf/.env
    ports: ["8104:8104"]
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    mem_limit: 512m
```

Validate:

```bash
ssh root@76.13.107.109 'cd /root/archie-outpost && docker compose config --quiet && echo OK'
```

- [ ] **Step 4: Pull + start**

```bash
ssh root@76.13.107.109 'cd /root/archie-outpost && docker compose pull wtf-ingest wtf-consumer wtf-tech && docker compose up -d wtf-ingest wtf-consumer wtf-tech'
```

Expected: three `started` lines.

- [ ] **Step 5: Smoke check**

```bash
ssh root@76.13.107.109 'curl -sI http://localhost:8103/ | head -3 && curl -sI http://localhost:8104/ | head -3 && docker logs --tail 5 wtf-ingest'
```

Expected: two 200s, ingest log shows `run_once: {'inserted': N, ...}`.

---

### Task C4: Add Caddy stanzas for WTF domains

**Files:**
- Modify on VPS: `/etc/caddy/Caddyfile`

- [ ] **Step 1: Append Caddy blocks**

SSH in, append to `/etc/caddy/Caddyfile`:

```
what-the-fact.com {
    reverse_proxy localhost:8103
    encode zstd gzip
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
    log {
        output file /var/log/caddy/wtf-consumer.log
    }
}

what-the-fact.tech {
    reverse_proxy localhost:8104
    encode zstd gzip
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
    log {
        output file /var/log/caddy/wtf-tech.log
    }
}
```

- [ ] **Step 2: Validate + reload**

```bash
ssh root@76.13.107.109 'caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy && systemctl status caddy --no-pager | head -5'
```

Expected: `Valid configuration`, then `active (running)`.

---

### Task C5: Point DNS at VPS via Hostinger

**Files:** None — uses Hostinger MCP.

- [ ] **Step 1: Look up `what-the-fact.com` current records**

```
mcp__hostinger-api__DNS_getDNSRecordsV1 domain=what-the-fact.com
```

Record every A/AAAA row.

- [ ] **Step 2: Update A record to VPS IP**

```
mcp__hostinger-api__DNS_updateDNSRecordsV1 domain=what-the-fact.com recordId=<id> type=A value=76.13.107.109 ttl=300
```

If no existing A record, use the add path instead.

Delete stray AAAA records (Hostinger shared often has IPv6 that would short-circuit to shared hosting).

- [ ] **Step 3: Repeat for `what-the-fact.tech`**

Same pattern, domain `what-the-fact.tech`.

- [ ] **Step 4: Wait for propagation**

```bash
for d in what-the-fact.com what-the-fact.tech; do
  echo "=== $d ==="
  dig +short $d @1.1.1.1
done
```

Expected (eventually, may take minutes up to TTL): both resolve to `76.13.107.109`.

- [ ] **Step 5: Verify Caddy got certs**

```bash
curl -sI https://what-the-fact.com/ | head -5
curl -sI https://what-the-fact.tech/ | head -5
```

Expected: `HTTP/2 200` and a Caddy-set cert.

If "certificate issuance failed" appears, check `journalctl -u caddy --no-pager --since '5 minutes ago'` on VPS — usually means DNS hasn't propagated yet. Wait + retry.

---

### Task C6: Unhost `what-the-fact.com` from Hostinger shared

**Files:** None — operates on Hostinger hosting panel.

- [ ] **Step 1: List existing Hostinger-hosted websites**

```
mcp__hostinger-api__hosting_listWebsitesV1
```

Find the `what-the-fact.com` entry.

- [ ] **Step 2: Disable/remove hosting for the domain**

Hostinger API exposes per-domain hosting controls; use the appropriate disable/remove call for that website. If the API lacks a "remove website" endpoint, do it in the Hostinger panel manually — documented as one-off in the KB note below.

- [ ] **Step 3: Re-check live serve**

```bash
curl -sI https://what-the-fact.com/ | grep -i server
```

Expected: `Server: Caddy` (NOT `hcdn`, `nginx/hostinger`, or similar).

- [ ] **Step 4: Store KB note**

Use `mcp__archie__store_memory`:
- memory_type: `vault_note`
- category: `infrastructure`
- tags: `["hostinger", "wtf", "unhost"]`
- content: `"what-the-fact.com unhosted from Hostinger shared on 2026-04-18. Now serving from VPS 76.13.107.109 via Caddy. DNS A record updated, cert issued by Let's Encrypt."`

---

## Phase D — Ship + observe (blocked by Phase C)

### Task D1: Register WTF in hub infra registries

**Files:**
- Modify: `platform_v2/services/infra_heartbeat_service.py` — add 3 CRITICAL_CONTAINERS
- Modify: `platform_v2/services/code_metrics_service.py` — already handled in A3
- Modify: `platform_v2/module_registry.py` — already handled in A3
- Modify: `.claude/rules/operational-state.md` — already handled in A3

- [ ] **Step 1: Add containers to CRITICAL_CONTAINERS**

Open `platform_v2/services/infra_heartbeat_service.py` and add to the `CRITICAL_CONTAINERS` registry:

```python
{"name": "wtf-consumer", "host": "76.13.107.109", "port": 8103, "product": "What The Fact"},
{"name": "wtf-tech",     "host": "76.13.107.109", "port": 8104, "product": "What The Fact"},
{"name": "wtf-ingest",   "host": "76.13.107.109", "port": None, "product": "What The Fact"},
```

Match the exact tuple/dict shape used by existing entries — inspect the first few before adding.

- [ ] **Step 2: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 3: Verify heartbeat sees them**

Wait ~60s then browse Consciousness module → Code Health tab, or query:

```bash
docker exec archie_platform python -c "
from platform_v2.services.infra_heartbeat_service import check_critical_containers
for r in check_critical_containers():
    if 'wtf' in r['name']:
        print(r)
"
```

Expected: 3 lines, each with `status: ok`.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/infra_heartbeat_service.py
git commit -m "feat(heartbeat): register wtf-consumer, wtf-tech, wtf-ingest"
```

---

### Task D2: Heartbeat kill test

**Why:** Spec Testing Strategy requires each container fail-and-recover is observed.

- [ ] **Step 1: Kill `wtf-consumer` on VPS**

```bash
ssh root@76.13.107.109 'docker stop wtf-consumer'
```

- [ ] **Step 2: Wait for heartbeat cycle + check Telegram**

The heartbeat poll interval is ~60s. Within 2 minutes, a V.I.G.I.L. Tier-2 approval should appear in the ARCHIE Telegram channel with `🚨 wtf-consumer offline on 76.13.107.109 — approve restart?`.

- [ ] **Step 3: Approve**

Click `Approve` in Telegram. Verify the container restarts:

```bash
ssh root@76.13.107.109 'docker ps | grep wtf-consumer'
```

Expected: running, with recent `Up` timestamp.

- [ ] **Step 4: Repeat for `wtf-tech` and `wtf-ingest`**

Same pattern. For `wtf-ingest` (no port), heartbeat should detect via `docker ps` state not HTTP.

- [ ] **Step 5: Commit test evidence to KB**

Use `mcp__archie__store_memory` with a summary: `"V.I.G.I.L. heartbeat validated against all 3 WTF containers on 2026-04-18. Kill → Telegram alert → approve → recovery in < 60s per container."`

---

### Task D3: End-to-end verification

- [ ] **Step 1: Public pages load with cert**

```bash
curl -sI https://what-the-fact.com/ | head -3
curl -sI https://what-the-fact.tech/ | head -3
```

Expected: `HTTP/2 200` for both.

- [ ] **Step 2: Consumer has at least one real article from ingest**

Open `https://what-the-fact.com/` in browser (or Playwright). Expected: at least one CBC headline listed with a bias band badge.

- [ ] **Step 3: Click into an article, see detail + transparency link**

Click the headline. Expected: body text, bias band, link to `what-the-fact.tech/transparency/<id>`.

- [ ] **Step 4: Tech transparency page loads**

Follow the link. Expected: bias score + rationale + audit trail events.

- [ ] **Step 5: SSO round-trip**

Click `Sign in with Kytran Empowerment` on `what-the-fact.tech`. Expected: redirect to ARCHIE hub login → approve → land on `/dashboard` with your name.

- [ ] **Step 6: API smoke**

```bash
curl -s https://what-the-fact.tech/api/v1/articles?limit=5 | head -c 200
```

Expected: JSON with `{"articles": [...]}`.

- [ ] **Step 7: Store verification note**

Use `mcp__archie__store_memory`: summary of verified flow + timestamp.

---

### Task D4: Close `project #260` + file follow-up tasks + memory update

- [ ] **Step 1: Close project #260**

Use `mcp__archie__update_project_status` (or the appropriate MCP tool):
- project_id: 260
- status: `completed`
- notes: `"Superseded by WTF + TheNews consolidation — TheNews retired, WTF deployed to VPS 2026-04-18. See spec 2026-04-18-wtf-thenews-consolidation-design.md and plan 2026-04-18-wtf-thenews-consolidation.md."`

- [ ] **Step 2: File the 7 follow-up tasks from the spec**

For each, use `mcp__archie__create_task` under project #259 (What The Fact):

1. `"WTF · Add Global News as second Canadian source"` — priority 5
2. `"WTF · ML bias scoring v2 (replace heuristic)"` — priority 6
3. `"WTF · Fact-check partner integration (legal review first)"` — priority 7
4. `"WTF · Public API launch on .tech (docs + rate limits + keys)"` — priority 5
5. `"WTF · Deploy wtf-ingest to first outpost node"` — priority 7
6. `"WTF · Paid tier integration once KBS gating Phase 2 lands"` — priority 6
7. `"WTF · i18n pass (French Canadian first)"` — priority 7

- [ ] **Step 3: Update `MEMORY.md`**

Edit `/home/kytran/.claude/projects/-mnt-archie-brain/memory/MEMORY.md`. Under "Active Project Context", replace the `project_kytran-news.md` entry line (now in Archived) with a fresh entry:

```markdown
- [What The Fact](project_what-the-fact.md) — AI news platform. 3-container stack on VPS: wtf-consumer:8103, wtf-tech:8104, wtf-ingest. Supersedes TheNews (retired 2026-04-18).
```

Create `/home/kytran/.claude/projects/-mnt-archie-brain/memory/project_what-the-fact.md` with frontmatter:

```markdown
---
name: What The Fact
description: 3-service AI news stack on VPS, ships CBC articles with bias scoring + transparency
type: project
---

**Status** (2026-04-18): deployed, MVP live
**Domains**: what-the-fact.com (consumer, 8103), what-the-fact.tech (transparency + API, 8104)
**Host**: US Outpost 76.13.107.109, behind Caddy
**Source**: /mnt/archie_brain/what-the-fact/
**Shared DB**: archie@192.168.1.200:5432, schema `wtf`
**Auth**: Kytran SSO via vendored kytran_auth.py (clients wtf-consumer, wtf-tech in oauth_clients)
**MVP source**: CBC English top-stories RSS (hourly pull)
**Bias**: rule-based heuristic v1 (10-article golden-file)

Supersedes TheNews (project #260 closed as duplicate). Follow-ups tracked in project #259 tasks.
```

- [ ] **Step 4: Archive `project_kytran-news.md`**

In memory file, change `archived: false` (or add) to `archived: true` in its frontmatter. Remove from MEMORY.md index. Add line under "Archived" section.

- [ ] **Step 5: Update session-handoff**

Edit `project_session-handoff.md`. Add a dated section:

```markdown
## 2026-04-18 — WTF + TheNews consolidation complete
- Retired kytran_news (VPS 8103, backup image retained 30d)
- Shipped WTF 3-container stack: wtf-consumer:8103, wtf-tech:8104, wtf-ingest (internal)
- Both domains on VPS behind Caddy w/ auto-HTTPS
- Registered in heartbeat, Code Health, module_registry, operational-state
- Project #260 closed (superseded). Follow-ups filed under #259.
- Spec: docs/superpowers/specs/2026-04-18-wtf-thenews-consolidation-design.md
- Plan: docs/superpowers/plans/2026-04-18-wtf-thenews-consolidation.md
```

- [ ] **Step 6: Log final decision**

Use `mcp__archie__log_decision`:
- decision: `"Ship WTF 3-container stack; close project #260 as superseded"`
- context: `"What The Fact now deployed to VPS with SSO, bias scoring, and transparency portal. TheNews retired. See spec + plan in docs/superpowers/."`

- [ ] **Step 7: Push the feature branch + merge PR**

```bash
cd /mnt/archie_brain
git push -u origin feat/wtf-consolidation
gh pr create --title "WTF + TheNews consolidation" --body "$(cat <<'EOF'
## Summary
- Retired thenews.kytranempowerment.com (VPS + hub registries + DNS)
- Shipped 3-container What The Fact stack: wtf-consumer:8103, wtf-tech:8104, wtf-ingest
- Both domains live on VPS behind Caddy with auto-HTTPS
- Kytran SSO integration on wtf-tech via vendored kytran_auth.py
- Registered alongside Watch-series in all platform registries

## Test plan
- [x] All pytest suites pass (schema, CBC fetch, normalizer, bias golden, persist, consumer routes, tech SSO, tech API)
- [x] Local docker-compose smoke
- [x] VPS deployment verified (HTTPS 200 on both domains, certs issued)
- [x] End-to-end article flow (CBC RSS → normalized → scored → persisted → consumer list → detail → tech transparency)
- [x] SSO round-trip on /dashboard
- [x] V.I.G.I.L. heartbeat kill-and-recover for each container
- [x] Project #260 closed, follow-ups filed

Spec: docs/superpowers/specs/2026-04-18-wtf-thenews-consolidation-design.md
Plan: docs/superpowers/plans/2026-04-18-wtf-thenews-consolidation.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Let user merge per feedback_pr-management.md.

---

## Self-Review (to run after following the plan)

When complete, verify:

- [ ] TheNews container gone (`ssh root@76.13.107.109 docker ps | grep -c kytran_news` → 0)
- [ ] Port 8103 serves WTF consumer (`curl -sI https://what-the-fact.com/` → 200)
- [ ] Port 8104 serves WTF tech (`curl -sI https://what-the-fact.tech/` → 200)
- [ ] DNS clean: `dig thenews.kytranempowerment.com` empty; `dig what-the-fact.com` → VPS IP
- [ ] Hostinger shared no longer serving `what-the-fact.com`
- [ ] Heartbeat green on all 3 WTF containers
- [ ] Code Health shows `what-the-fact` project at `/mnt/archie_brain/what-the-fact/`
- [ ] Module registry has `what_the_fact` (not `kytran_news`)
- [ ] `.claude/rules/operational-state.md` reflects new product registry
- [ ] Project #260 closed
- [ ] 7 follow-up tasks filed under #259
- [ ] `MEMORY.md` + session-handoff updated
