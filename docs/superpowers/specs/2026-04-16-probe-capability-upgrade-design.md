# P.R.O.B.E. Capability Upgrade — Design Doc

**Date**: 2026-04-16
**Project**: #236 P.R.O.B.E. Phase 2 — Bridge Dispatch + CLI + SaaS
**Task**: #2022 (research)
**Origin**: Account Center QA (#2013) surfaced that P.R.O.B.E. can verify routes don't 500 but can't review layout/template quality/UX.

---

## 1. Current State

P.R.O.B.E. runs YAML-declared suites via `qa_spec_runner.py` with three test types:

| Type | What it checks | Mechanism |
|------|----------------|-----------|
| `api` | HTTP status/headers/JSON keys | `requests` session |
| `page_load` | HTML loads, selectors present | `requests` + BeautifulSoup |
| `e2e` | Playwright user flows | `qa_e2e_runner.py` (pytest-asyncio) |

Suites live in `platform_v2/qa_suites/*.yaml`. Runs go through `qa_service.run_suite()`, store to `qa_runs`/`qa_run_results`, auto-create Repair Bay proposals on failure, push Telegram alerts, and emit PDF reports via `qa_report_service`.

**Explicitly in scope to leave alone**: the YAML schema, existing runner, report pipeline. Upgrades are **additive new test types**.

---

## 2. The Three Gaps

### Gap 1: Visual / LCARS consistency regression

**Failure modes we need to catch**
- Wrong accent (`--bm-accent` resolves to the wrong hex)
- Frame missing (e.g. `.bm-frame` / elbow corner elements not present)
- CSS class collision (a token gets overridden silently)
- Responsive breakpoints fail at 480 / 768 / 1024

**Options**

| Option | Pros | Cons |
|--------|------|------|
| A. Playwright screenshot + pixelmatch-py diff | Broadest coverage; catches anything visual | Flaky — timestamps, animations, dynamic data; large baseline disk; many false positives; hard to tell *why* it failed |
| B. DOM-tree structural diff | Deterministic, no image noise | Misses visual issues: a wrong color still passes structure checks |
| C. **Computed-style + selector snapshot per breakpoint** | Semantic, targets LCARS directly (CSS vars + required classes), low noise, fast, diff reads like a changelog | Requires maintaining a selector list per suite |
| D. Hybrid (C + targeted region screenshots) | Covers surprises | Adds flakiness; defer to v2 |

**Pick: Option C — computed-style + selector snapshot per breakpoint.**

**Rationale**: LCARS is a rule-based design system — `var(--archie-*)` tokens, a small set of frame classes (`bm-frame`, `bm-shell`, `lcars-elbow-*`), and deterministic breakpoints. The *exact* failures called out in the task brief (wrong accent, missing frame, collisions, responsive breaks) are all expressible as assertions over `getComputedStyle()` + `querySelectorAll()` output. That makes this option:

- **Deterministic** — zero image flake
- **Legible** — failures report `--bm-accent expected #7aa7ff, got #ff00ff` instead of "12% pixel diff somewhere"
- **Cheap** — one Playwright page + three `evaluate()` calls per breakpoint, no pixel comparison
- **Low baseline cost** — JSON blob ~5 KB per suite/breakpoint vs. screenshot PNG ~500 KB

**Escape hatch**: if we later need to catch visual failures not expressible as computed-style assertions (e.g. "the elbow is drawn, but it's the wrong shape"), Option A can be layered on top as a new `visual_pixel` test type with region masks. Don't build it yet.

---

### Gap 2: Template extraction analysis

**Failure modes**
- Inline `<style>` block > N lines (should be in a `.css`)
- Inline `<script>` block > N lines (should be in a `.js`)
- The same CSS rule block repeated in N templates (extract to a shared stylesheet)

**Options**

| Option | Pros | Cons |
|--------|------|------|
| A. **Static BeautifulSoup + heuristic scanner** | Deterministic, fast, no LLM cost, reproducible, runs in CI | Can't give nuanced refactor suggestions |
| B. Bridge LLM with scoring rubric on every template | Richer recommendations | Expensive (~50 templates × LLM roundtrip), non-deterministic, slow |
| C. Hybrid: static scanner → flag suspects → LLM only on flagged files | Best of both | More moving parts; defer |

**Pick: Option A — static BeautifulSoup + heuristic scanner.**

**Rationale**: The thing we actually need is a *signal*, not a refactor proposal. A static scanner that emits three metrics — `inline_css_lines`, `inline_js_lines`, `duplicate_block_hashes` — is sufficient to drive proposals and dashboards. Every LLM call here is waste because the question is factual, not interpretive. BeautifulSoup handles Jinja well enough for `<style>` / `<script>` detection (it ignores the `{% %}` and `{{ }}` inside text nodes).

**Escape hatch**: if we later want phrasing like "this block looks like what's already in `base.css`, extract it" we can add Option B as a `template_deep_review` action run only on templates the scanner flagged.

**Duplicate detection**: hash each `<style>` block's normalized content (whitespace-collapsed, comments stripped) and group by hash across the whole `templates/` tree. Groups with ≥2 members become extraction candidates.

---

### Gap 3: Subjective UX scoring

**Failure modes**
- Navigation unclear (tabs look like labels, not clickable)
- Info density wrong (either empty + wasteful, or overloaded)
- Accent inconsistent within a tab
- Empty states not handled (lists show blank instead of a message)

**Options**

| Option | Pros | Cons |
|--------|------|------|
| A. **Local vision model via Bridge (`qwen2.5-vl:7b`)** | Free at inference; local; keeps data on-box; fits the Bridge 11-tier pattern | Slower; VRAM contention with ComfyUI; quality < frontier |
| B. Cloud vision (Claude 3.5 Sonnet vision, or `qwen2.5-vl:cloud`) | High quality, no VRAM contention | Cost per screenshot; external dependency |
| C. Text-only LLM over DOM/CSS snapshot (no vision) | Cheap, deterministic-ish | Can't actually *see* layout — misses density, empty states |

**Pick: Option A — local `qwen2.5-vl:7b` via Bridge, with tier escalation to cloud.**

**Rationale**: Exactly the pattern Bridge dispatch was built for. `qwen2.5-vl:7b` handles screenshot + rubric well enough for scoring, runs on the M4000 (needs VRAM swap with ComfyUI — already supported via `_vram_swap_for_comfyui`), and escalates to `qwen2.5-vl:cloud` or Claude Sonnet vision via the standard tier-up when local is unavailable or the run is flagged high-priority.

**Rubric**: stored in KB as a `vault_note` with tag `probe-ux-rubric` and `knowledge_type='vault_note'`. Schema:

```yaml
version: 1
dimensions:
  - name: navigation_clarity
    scale: 1-5
    criteria:
      5: "Active tab obvious, clickable affordance clear, hierarchy unambiguous"
      3: "Tabs visible but hover/active state weak"
      1: "Tabs look like static text, no affordance"
  - name: information_density
    scale: 1-5
    criteria: ...
  - name: accent_consistency
    scale: 1-5
    criteria: ...
  - name: empty_state_handling
    scale: 1-5
    criteria: ...
threshold_for_pass: 3.5
```

Score + raw rationale stored in `qa_ux_rubric_scores`. Failures below threshold auto-create Repair Bay proposals with the rubric-scored screenshot attached.

**Escape hatch**: if `qwen2.5-vl:7b` output quality is too noisy to drive proposals, flip the default in config to cloud. No code change.

---

## 3. Integration Approach

### 3.1 YAML schema additions

Existing suite YAMLs stay untouched. Add three new `type:` values:

```yaml
# Visual consistency
- name: "ac-visual-consistency"
  type: visual_snapshot
  path: /tools/account-center/
  breakpoints: [480, 768, 1024]
  selectors:
    - ".bm-frame"
    - ".bm-shell"
    - ":root"                  # root captures --archie-* and --bm-accent
    - "[data-lcars-elbow]"
  snapshot_name: "account-center-v1"   # baseline key

# Template health
- name: "ac-template-health"
  type: template_analysis
  targets:
    - templates/tools/account_center.html
    - templates/tools/account_center_includes/*.html
  thresholds:
    max_inline_css_lines: 50
    max_inline_js_lines: 100
    max_duplicate_block_members: 1   # 2+ members = fail

# UX scoring
- name: "ac-ux-score"
  type: ux_score
  path: /tools/account-center/
  breakpoints: [1024]
  rubric: probe-ux-rubric-v1
  min_score: 3.5
```

### 3.2 Runner dispatch

In `qa_spec_runner.execute_spec()`, the existing `type` switch learns three new branches that call three new runner modules:

```
qa_spec_runner.py
  ├── _run_api_test                        (existing)
  ├── _run_page_load_test                  (existing)
  ├── _run_e2e_batch                       (existing)
  ├── _run_visual_snapshot_test  → qa_visual_runner.py         (new)
  ├── _run_template_analysis_test → qa_template_analyzer.py    (new)
  └── _run_ux_score_test         → qa_ux_scorer.py             (new)
```

Each new runner returns the same `{"passed": bool, "detail": {...}}` shape the existing runners use, so `qa_service.run_suite()`, report generation, proposal creation, and Telegram alerts keep working without modification.

### 3.3 DB schema additions

Two new tables, both keyed on `run_id` / `suite_id` so they slot into the existing reporting:

```sql
CREATE TABLE qa_visual_baselines (
    id              SERIAL PRIMARY KEY,
    suite_id        INT REFERENCES qa_suites(id) ON DELETE CASCADE,
    snapshot_name   TEXT NOT NULL,
    breakpoint      INT NOT NULL,
    baseline        JSONB NOT NULL,            -- {selector: {prop: value, ...}}
    captured_at     TIMESTAMP DEFAULT NOW(),
    captured_by     INT REFERENCES users(id),
    UNIQUE (suite_id, snapshot_name, breakpoint)
);

CREATE TABLE qa_ux_rubric_scores (
    id              SERIAL PRIMARY KEY,
    run_id          INT REFERENCES qa_runs(id) ON DELETE CASCADE,
    suite_id        INT REFERENCES qa_suites(id),
    rubric_version  TEXT NOT NULL,
    path            TEXT NOT NULL,
    breakpoint      INT,
    scores          JSONB NOT NULL,            -- {dimension: score}
    overall_score   NUMERIC(3,2) NOT NULL,
    passed          BOOLEAN NOT NULL,
    model_used      TEXT,
    rationale       TEXT,
    screenshot_path TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

Template analysis doesn't need a new table — its results fit the existing `qa_run_results.details` JSONB blob and drive Repair Bay proposals the same way API failures do.

### 3.4 Bridge dispatch contract for UX scoring

- Capability: register new `ux_scoring` capability in `smart_router.CAPABILITY_ROUTING`
- Home tier: Pixel (vision) / any agent with `ux_scoring` skill
- Tier up: local `qwen2.5-vl:7b` → `qwen2.5-vl:cloud` → Claude Sonnet vision (external_providers)
- VRAM swap: `qa_ux_scorer` calls `_vram_swap_for_comfyui` equivalent before invoking the vision model so ComfyUI and `qwen2.5-vl` don't fight for the 8 GB M4000
- All calls go through `tools.department_hq.services.bridge_dispatcher.dispatch_json()` — never direct Ollama (ADR-013)

---

## 4. Follow-up Tasks (to be created under #236)

Each implementation task below is independently shippable and non-blocking on the others.

### Task A — Visual snapshot runner + baseline management (effort: medium)

**Files**
- `platform_v2/services/qa_visual_runner.py` (new) — Playwright-driven computed-style snapshot, baseline fetch, diff, JSON blob comparison
- `platform_v2/services/qa_spec_runner.py` — wire `type: visual_snapshot` into the type dispatch
- `platform_v2/tools/repair_bay/qa_routes.py` — add `POST /api/qa/baselines/<suite_id>/accept` to promote a run into the baseline
- `database/migrations/NNN_qa_visual_baselines.sql` — create table
- `platform_v2/qa_suites/admin-account-center.yaml` — add first `visual_snapshot` test as pilot

**Acceptance**: change `--bm-accent` in `lcars-tokens.css`, suite fails with a clear diff; revert, suite passes; baseline can be re-accepted from the UI.

### Task B — Template analyzer + proposal integration (effort: small)

**Files**
- `platform_v2/services/qa_template_analyzer.py` (new) — BeautifulSoup walk, line-count thresholds, duplicate-block hashing across `templates/` tree
- `platform_v2/services/qa_spec_runner.py` — wire `type: template_analysis`
- `platform_v2/qa_suites/admin-account-center.yaml` — add `template_analysis` test
- `platform_v2/services/audit_pipeline.py` — ensure template_analysis failures create Repair Bay proposals with the same "critical/high → individual, medium → weekly batch" pattern

**Acceptance**: adding a 200-line `<style>` block to `account_center.html` fails the suite and creates a proposal; removing it passes.

### Task C — UX scorer via Bridge vision + rubric (effort: medium)

**Files**
- `platform_v2/services/qa_ux_scorer.py` (new) — Playwright screenshot, Bridge dispatch with rubric, parse score JSON, store to `qa_ux_rubric_scores`
- `platform_v2/services/qa_spec_runner.py` — wire `type: ux_score`
- `platform_v2/tools/department_hq/services/smart_router.py` — register `ux_scoring` capability + tier escalation
- `database/migrations/NNN_qa_ux_rubric_scores.sql` — create table
- Seed: store `probe-ux-rubric-v1` as vault_note in KB (not a migration)
- `platform_v2/qa_suites/admin-account-center.yaml` — add `ux_score` test

**Acceptance**: run on Account Center at 1024px, receive a score per rubric dimension + overall, stored to DB; score below 3.5 creates a Repair Bay proposal with screenshot attached.

---

## 5. Out of Scope for This Research Task

- Actually implementing any of A/B/C (each becomes its own task under #236)
- Extending YAML schema beyond the three new `type:` values above
- Multi-site / KBS-customer QA-as-a-Service (task #1728 already covers that)
- Playwright pixel-diff (option 1A) — explicit v2 escape hatch
- `template_deep_review` LLM pass (option 2C) — explicit v2 escape hatch

---

## 6. Open Questions (for user before implementing)

1. **Baseline promotion UX** — should baselines auto-accept on first run, or require an explicit "accept" click? (Proposing: require explicit accept, so the first run is always a no-op pass.)
2. **Rubric editing** — edit the KB vault_note directly, or build a UI panel in Repair Bay → QA tab? (Proposing: edit the vault_note for v1; UI panel in v2.)
3. **UX scorer cadence** — run on every QA suite, or only on a weekly schedule to save VRAM? (Proposing: weekly + on-demand via MCP / CLI; not per-suite.)
