# LLM Ecosystem Redesign — Phase 0+1+2: Housekeeping, Foundation & Roster

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up stale modules, lay the data foundation (capability profiles, contractor tiers, C.R.E.E.D. compliance), then restructure the entire agent roster — models, names, types, and decommissions.

**Architecture:** DB-first approach. Most changes are SQL migrations + module_registry updates. No dispatch logic changes yet (that's Phase 3). The roster restructure touches the `agents` table, `contractor_providers` table, and `agent_skills` table. Directory module absorbed into DHQ.

**Tech Stack:** PostgreSQL migrations, Python (Flask module_registry, rbac.py), Ollama CLI for model deletion, static file cleanup.

**Spec:** `docs/superpowers/specs/2026-04-15-llm-ecosystem-redesign-design.md`
**Decision:** #441 (ADR logged 2026-04-15)

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `platform_v2/module_registry.py:844-857` | Disable directory module |
| Modify | `platform_v2/rbac.py:63` | Keep DIRECTORY_VIEW (used by public API) |
| Delete | `directory-*.png` (11 files in repo root) | Dev screenshot cleanup |
| Create | `database/migrations/NNN_ecosystem_redesign_foundation.sql` | Capability profiles, contractor tiers, C.R.E.E.D. column |
| Create | `database/migrations/NNN_roster_restructure.sql` | Agent model reassignment, conversions, decommissions, name cleanup |
| Modify | `platform_v2/tools/department_hq/services/bridge_dispatcher.py` | Rename class only (file rename in Phase 3) |
| Modify | `website/kytranempowerment.com/data/directory-fallback.json` | Regenerate with new 50-agent roster |

---

### Task 1: Disable Directory Module & Clean Screenshots

**Files:**
- Modify: `platform_v2/module_registry.py:853`
- Delete: 11 `directory-*.png` files in repo root

- [ ] **Step 1: Disable directory module in registry**

In `platform_v2/module_registry.py` at line 853, change:
```python
        enabled=True,
```
to:
```python
        enabled=False,
```

- [ ] **Step 2: Remove stale screenshots from repo root**

```bash
cd /mnt/archie_brain
rm -f directory-cards.png directory-cards-live.png directory-full.png \
      directory-ledger.png directory-live-api-working.png directory-live-test.png \
      directory-mobile-email.png directory-modal-archie.png \
      directory-modal-desktop.png directory-modal-mobile.png \
      directory-public-viewport.png
```

- [ ] **Step 3: Verify no other code imports from directory module**

```bash
cd /mnt/archie_brain/platform_v2
grep -rn "from tools.directory" --include="*.py" | grep -v __pycache__ | grep -v tools/directory/
```

Expected: No results (directory is self-contained, only registered via module_registry).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: disable directory module, clean root screenshots — DHQ Roster tab replaces it"
```

---

### Task 2: Foundation Migration — Capability Profiles & Contractor Tiers

**Files:**
- Create: `database/migrations/100_ecosystem_foundation.sql`

- [ ] **Step 1: Create the foundation migration**

Create `database/migrations/100_ecosystem_foundation.sql`:

```sql
-- ============================================================
-- LLM Ecosystem Redesign — Foundation Migration
-- Decision #441, Spec: 2026-04-15-llm-ecosystem-redesign-design.md
-- ============================================================

BEGIN;

-- 1. Department capability profiles
-- Stores required LLM capabilities per department
CREATE TABLE IF NOT EXISTS department_capability_profiles (
    id SERIAL PRIMARY KEY,
    department VARCHAR(100) NOT NULL UNIQUE,
    floor VARCHAR(50) NOT NULL,
    required_capabilities JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO department_capability_profiles (department, floor, required_capabilities) VALUES
('Executive Office', 'BRIDGE', '["summarization", "reasoning", "orchestration"]'),
('Operations & Infrastructure', 'OPERATIONS', '["log_analysis", "scripting", "diagnostics"]'),
('Logistics & Supply Chain', 'OPERATIONS', '["data_extraction", "cost_analysis"]'),
('Finance & Accounting', 'OPERATIONS', '["numerical_reasoning", "report_generation"]'),
('Engineering & Technology', 'ENGINEERING', '["code_generation", "code_review", "debugging", "architecture"]'),
('Security & Compliance', 'ENGINEERING', '["classification", "threat_analysis", "policy_reasoning"]'),
('Research & Development', 'ENGINEERING', '["reasoning", "research_synthesis", "embedding"]'),
('Creative & Design', 'CREATIVE', '["creative_writing", "image_generation", "vision"]'),
('Marketing & Communications', 'CREATIVE', '["copywriting", "social_content", "multilingual"]'),
('Documentation & Knowledge', 'CREATIVE', '["summarization", "knowledge_extraction", "quality_scoring"]'),
('Customer Success & Support', 'SERVICES', '["conversation", "sentiment_analysis", "empathy"]'),
('Human Resources & Culture', 'SERVICES', '["ethics_reasoning", "policy_compliance", "welfare_check"]'),
('Medical & Wellness', 'SERVICES', '["empathetic_dialogue", "health_reasoning"]'),
('Legal & Regulatory', 'SERVICES', '["legal_reasoning", "document_analysis", "policy"]'),
('Diplomatic & External Relations', 'SERVICES', '["multilingual", "diplomatic_writing", "translation"]'),
('Analytics & Intelligence', 'SERVICES', '["data_analysis", "forecasting", "pattern_recognition"]'),
('News & Media', 'CREATIVE', '["fact_checking", "bias_detection", "editorial", "news_writing"]')
ON CONFLICT (department) DO UPDATE SET
    floor = EXCLUDED.floor,
    required_capabilities = EXCLUDED.required_capabilities,
    updated_at = NOW();

-- 2. Add C.R.E.E.D. compliance tier to contractor_providers
ALTER TABLE contractor_providers ADD COLUMN IF NOT EXISTS creed_compliance_tier INTEGER DEFAULT 2;

COMMENT ON COLUMN contractor_providers.creed_compliance_tier IS '1=Compliant (local/privacy), 2=Conditional (acceptable policy), 3=Restricted (data may be retained)';

-- 3. Normalize capability tags — fix image_generation → image_gen
UPDATE contractor_providers
SET capabilities = REPLACE(capabilities::text, '"image_generation"', '"image_gen"')::jsonb
WHERE capabilities::text LIKE '%image_generation%';

-- 4. Set C.R.E.E.D. compliance tiers for existing contractors
UPDATE contractor_providers SET creed_compliance_tier = 1 WHERE provider_key IN ('comfyui', 'kokoro_tts', 'ollama_diffuser');
UPDATE contractor_providers SET creed_compliance_tier = 2 WHERE provider_key IN ('groq', 'cerebras', 'mistral', 'cohere', 'together', 'cloudflare_ai', 'huggingface');
UPDATE contractor_providers SET creed_compliance_tier = 3 WHERE provider_key IN ('openai', 'gemini', 'xai', 'replicate_audio', 'elevenlabs', 'perplexity', 'claude');
-- Cloud proxies (minimax, qwen3) are tier 2 by default

-- 5. Fix contractor tier positions (local → free → freemium → paid → premium → specialist)
UPDATE contractor_providers SET tier_position = 1 WHERE provider_key = 'comfyui';
UPDATE contractor_providers SET tier_position = 2 WHERE provider_key = 'kokoro_tts';
UPDATE contractor_providers SET tier_position = 3 WHERE provider_key = 'ollama_diffuser';
UPDATE contractor_providers SET tier_position = 4 WHERE provider_key = 'huggingface';
UPDATE contractor_providers SET tier_position = 5 WHERE provider_key = 'cloudflare_ai';
UPDATE contractor_providers SET tier_position = 6 WHERE provider_key = 'groq';
UPDATE contractor_providers SET tier_position = 7 WHERE provider_key = 'cerebras';
UPDATE contractor_providers SET tier_position = 9 WHERE provider_key = 'together';
UPDATE contractor_providers SET tier_position = 10 WHERE provider_key = 'cohere';
UPDATE contractor_providers SET tier_position = 11 WHERE provider_key = 'mistral';
UPDATE contractor_providers SET tier_position = 14 WHERE provider_key = 'minimax_cloud';
UPDATE contractor_providers SET tier_position = 15 WHERE provider_key = 'qwen3_cloud';
UPDATE contractor_providers SET tier_position = 19 WHERE provider_key = 'gemini';
UPDATE contractor_providers SET tier_position = 20 WHERE provider_key = 'xai';
UPDATE contractor_providers SET tier_position = 21 WHERE provider_key = 'perplexity';
UPDATE contractor_providers SET tier_position = 24 WHERE provider_key = 'openai';
UPDATE contractor_providers SET tier_position = 25 WHERE provider_key = 'claude';
UPDATE contractor_providers SET tier_position = 29 WHERE provider_key = 'replicate_audio';
UPDATE contractor_providers SET tier_position = 30 WHERE provider_key = 'elevenlabs';

-- 6. Add 6 new contractor providers
INSERT INTO contractor_providers (provider_key, display_name, base_url, capabilities, is_active, tier_position, creed_compliance_tier, is_cloud_proxy)
VALUES
('pollinations', 'Pollinations', 'https://image.pollinations.ai', '["image_gen"]', true, 8, 2, false),
('deepseek', 'DeepSeek', 'https://api.deepseek.com/v1', '["text_chat", "code", "reasoning"]', true, 12, 2, false),
('openrouter', 'OpenRouter', 'https://openrouter.ai/api/v1', '["text_chat", "code", "vision"]', true, 13, 2, false),
('stability_ai', 'Stability AI', 'https://api.stability.ai/v2beta', '["image_gen"]', true, 22, 3, false),
('fal_ai', 'Fal.ai', 'https://fal.run', '["image_gen"]', true, 23, 2, false),
('replicate', 'Replicate', 'https://api.replicate.com/v1', '["image_gen", "video_gen", "audio"]', true, 26, 3, false)
ON CONFLICT (provider_key) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    base_url = EXCLUDED.base_url,
    capabilities = EXCLUDED.capabilities,
    tier_position = EXCLUDED.tier_position,
    creed_compliance_tier = EXCLUDED.creed_compliance_tier;

COMMIT;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/100_ecosystem_foundation.sql
```

Expected: `BEGIN`, `CREATE TABLE`, multiple `UPDATE`/`INSERT`, `COMMIT`.

- [ ] **Step 3: Verify contractor providers updated**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT provider_key, tier_position, creed_compliance_tier FROM contractor_providers ORDER BY tier_position"
```

Expected: 25 rows, tier positions in order 1-30, all have creed_compliance_tier set.

- [ ] **Step 4: Verify department capability profiles**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT department, floor, required_capabilities FROM department_capability_profiles ORDER BY department"
```

Expected: 17 rows, one per department.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/100_ecosystem_foundation.sql
git commit -m "feat: ecosystem foundation — capability profiles, contractor tiers, C.R.E.E.D. compliance"
```

---

### Task 3: Roster Restructure — AI Agent Model Reassignment

**Files:**
- Create: `database/migrations/101_roster_restructure_ai.sql`

- [ ] **Step 1: Create AI roster migration**

Create `database/migrations/101_roster_restructure_ai.sql`:

```sql
-- ============================================================
-- LLM Ecosystem Redesign — AI Agent Roster Restructure
-- Decision #441
-- ============================================================

BEGIN;

-- 1. Reinstate A.R.C.H.I.E. — COO, dolphin3-8k, uncensored
UPDATE agents SET
    shift_state = 'active',
    model = 'dolphin3-8k:latest',
    title = 'Chief Operations Officer & Platform Director'
WHERE id = 2 AND name = 'ARCHIE';

-- 2. Reinstate F.O.R.G.E. — Senior Engineer
UPDATE agents SET
    shift_state = 'active',
    title = 'Senior Engineer & Self-Healing Pipeline'
WHERE id = 136 AND name = 'FORGE';

-- 3. Reassign models — purpose-matched per department capability
-- Engineering gets best coder
UPDATE agents SET model = 'deepseek-coder-v2:16b' WHERE id = 340 AND name = 'P.R.O.B.E.';

-- Security & HR get real reasoning (gemma3:12b)
UPDATE agents SET model = 'gemma3:12b' WHERE id = 3 AND name = 'VIGIL';
UPDATE agents SET model = 'gemma3:12b' WHERE id = 145 AND name = 'KIN';

-- Research & Legal get strong reasoning (phi4:14b)
UPDATE agents SET model = 'phi4:14b' WHERE id = 140 AND name = 'DARWIN';
UPDATE agents SET model = 'phi4:14b' WHERE id = 147 AND name = 'GAVEL';

-- News & Media — fact-checking needs reasoning, creative needs uncensored
UPDATE agents SET model = 'gemma3:12b' WHERE id = 48 AND name = 'fact';
UPDATE agents SET model = 'dolphin3:latest' WHERE id = 23 AND name = 'ink';

-- Fix ghost models (qwen2.5:7b not on disk)
UPDATE agents SET model = 'gemma2:9b' WHERE id = 332 AND name = 'scroll';
UPDATE agents SET model = 'llama3.2:3b' WHERE id = 331 AND name = 'heritage';

-- Vision specialist gets proper vision model
UPDATE agents SET model = 'qwen2.5vl:7b' WHERE id = 334 AND name = 'visage';

-- 4. Convert 5 acronym internals to worker_type='ai'
UPDATE agents SET worker_type = 'ai', is_department_ai = true WHERE id = 32 AND name = 'MARKET';
UPDATE agents SET worker_type = 'ai', is_department_ai = true WHERE id = 126 AND name = 'EMBER';
UPDATE agents SET worker_type = 'ai', is_department_ai = true WHERE id = 150 AND name = 'SHIELD';
UPDATE agents SET worker_type = 'ai', is_department_ai = true WHERE id = 336 AND name = 'ethos';
UPDATE agents SET worker_type = 'ai', is_department_ai = true WHERE id = 337 AND name = 'ARMADA';

-- Assign models to newly converted AI agents
UPDATE agents SET model = 'mistral:7b' WHERE id = 32 AND name = 'MARKET';
UPDATE agents SET model = 'llama3.2:3b' WHERE id = 126 AND name = 'EMBER';
UPDATE agents SET model = 'gemma2:9b' WHERE id = 150 AND name = 'SHIELD';
UPDATE agents SET model = 'gemma2:9b' WHERE id = 336 AND name = 'ethos';
UPDATE agents SET model = 'gemma2:9b' WHERE id = 337 AND name = 'ARMADA';

-- 5. Set News & Media floor to CREATIVE
UPDATE agents SET floor = 'CREATIVE' WHERE department = 'News & Media' AND floor IS DISTINCT FROM 'CREATIVE';

COMMIT;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/101_roster_restructure_ai.sql
```

- [ ] **Step 3: Verify A.R.C.H.I.E. and F.O.R.G.E. reinstated**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT name, model, shift_state, title FROM agents WHERE id IN (2, 136)"
```

Expected: ARCHIE active with dolphin3-8k:latest, FORGE active with qwen2.5-coder:7b.

- [ ] **Step 4: Verify all AI agent model assignments**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT name, model, shift_state, worker_type FROM agents WHERE worker_type = 'ai' AND shift_state != 'decommissioned' ORDER BY department, name"
```

Expected: 34 AI agents with purpose-matched models. No llama3.2:3b on P.R.O.B.E., no smollm2 on VIGIL, no ghost qwen2.5:7b.

- [ ] **Step 5: Verify converted agents**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT name, display_name, worker_type, model FROM agents WHERE id IN (32, 126, 150, 336, 337)"
```

Expected: All 5 show `worker_type = 'ai'`.

- [ ] **Step 6: Commit**

```bash
git add database/migrations/101_roster_restructure_ai.sql
git commit -m "feat: AI roster restructure — reinstated ARCHIE+FORGE, purpose-matched models, converted 5 acronyms"
```

---

### Task 4: Roster Restructure — Human Staff Name Cleanup

**Files:**
- Create: `database/migrations/102_roster_human_staff.sql`

- [ ] **Step 1: Create human staff migration**

Create `database/migrations/102_roster_human_staff.sql`:

```sql
-- ============================================================
-- LLM Ecosystem Redesign — Human Staff Name Cleanup
-- Rule: AI = ACRONYM with dots. Human = First Last (no code names).
-- Decision #441
-- ============================================================

BEGIN;

-- 1. Update kept human staff — remove code names, set proper display_name
-- Format: display_name = "First Last", remove code name from name field

-- Executive Office — Architect → Marcus Rivera
UPDATE agents SET
    display_name = 'Marcus Rivera',
    first_name = 'Marcus',
    last_name = 'Rivera',
    title = 'Chief Architect'
WHERE id = 5 AND name = 'Architect';

-- Operations & Infrastructure — Circuit → Amira Hassan
UPDATE agents SET
    display_name = 'Amira Hassan',
    first_name = 'Amira',
    last_name = 'Hassan',
    title = 'Infrastructure Engineer'
WHERE name = 'Circuit' AND department = 'Operations & Infrastructure';

-- Logistics & Supply Chain — Dispatch → Carmen Reyes (already has name)
UPDATE agents SET
    display_name = 'Carmen Reyes',
    first_name = 'Carmen',
    last_name = 'Reyes',
    title = 'Logistics Coordinator'
WHERE name = 'Dispatch' AND department = 'Logistics & Supply Chain';

-- Finance & Accounting — Value → Yuki Nakamura
UPDATE agents SET
    display_name = 'Yuki Nakamura',
    first_name = 'Yuki',
    last_name = 'Nakamura',
    title = 'Financial Analyst'
WHERE name = 'Value' AND department = 'Finance & Accounting';

-- Engineering & Technology — CodeSmith → Aria Chen (already has name)
UPDATE agents SET
    display_name = 'Aria Chen',
    first_name = 'Aria',
    last_name = 'Chen',
    title = 'Lead Software Engineer'
WHERE name = 'CodeSmith' AND department = 'Engineering & Technology';

-- Security & Compliance — Thorn → Rowan McAllister (already has name)
UPDATE agents SET
    display_name = 'Rowan McAllister',
    first_name = 'Rowan',
    last_name = 'McAllister',
    title = 'Penetration Tester & Red Team Lead'
WHERE name = 'Thorn' AND department = 'Security & Compliance';

-- Research & Development — Cortex → Olumide Adeyemi
UPDATE agents SET
    display_name = 'Olumide Adeyemi',
    first_name = 'Olumide',
    last_name = 'Adeyemi',
    title = 'Senior Data Scientist'
WHERE name = 'Cortex' AND department = 'Research & Development';

-- Creative & Design — Nova → Isabella Fernandez (already has name)
UPDATE agents SET
    display_name = 'Isabella Fernandez',
    first_name = 'Isabella',
    last_name = 'Fernandez',
    title = 'Creative Director'
WHERE name = 'Nova' AND department = 'Creative & Design';

-- Marketing & Communications — Scribe → Lea Dubois
UPDATE agents SET
    display_name = 'Lea Dubois',
    first_name = 'Lea',
    last_name = 'Dubois',
    title = 'Senior Copywriter'
WHERE name = 'Scribe' AND department = 'Marketing & Communications';

-- Documentation & Knowledge — Scholar → Sofia Petrov (already has name)
UPDATE agents SET
    display_name = 'Sofia Petrov',
    first_name = 'Sofia',
    last_name = 'Petrov',
    title = 'Head of Research & Knowledge'
WHERE name = 'Scholar' AND department = 'Documentation & Knowledge';

-- Customer Success & Support — Envoy → Kwame Asante (already has name)
UPDATE agents SET
    display_name = 'Kwame Asante',
    first_name = 'Kwame',
    last_name = 'Asante',
    title = 'Client Success Manager'
WHERE name = 'Envoy' AND department = 'Customer Success & Support';

-- Human Resources & Culture — Sage → Haruto Takahashi (already has name)
UPDATE agents SET
    display_name = 'Haruto Takahashi',
    first_name = 'Haruto',
    last_name = 'Takahashi',
    title = 'People & Culture Lead'
WHERE name = 'Sage' AND department = 'Human Resources & Culture';

-- Medical & Wellness — Zenith → Dr. Priya Sharma
UPDATE agents SET
    display_name = 'Dr. Priya Sharma',
    first_name = 'Priya',
    last_name = 'Sharma',
    title = 'Medical Director'
WHERE name = 'Zenith' AND department = 'Medical & Wellness';

-- Legal & Regulatory — Crucible → Dr. Kenji Yamamoto (already has name, fix title)
UPDATE agents SET
    display_name = 'Dr. Kenji Yamamoto',
    first_name = 'Kenji',
    last_name = 'Yamamoto',
    title = 'Legal Counsel'
WHERE name = 'Crucible' AND department = 'Legal & Regulatory';

-- Diplomatic & External Relations — Luna → Fatima Al-Rashid (already has name)
UPDATE agents SET
    display_name = 'Fatima Al-Rashid',
    first_name = 'Fatima',
    last_name = 'Al-Rashid',
    title = 'Senior Diplomatic Advisor'
WHERE name = 'Luna' AND department = 'Diplomatic & External Relations';

-- Analytics & Intelligence — Nexus → Jin Park (already has name)
UPDATE agents SET
    display_name = 'Jin Park',
    first_name = 'Jin',
    last_name = 'Park',
    title = 'Data & Vision Specialist'
WHERE name = 'Nexus' AND department = 'Analytics & Intelligence';

COMMIT;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/102_roster_human_staff.sql
```

- [ ] **Step 3: Verify human names are clean**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT name, display_name, first_name, last_name, title, department FROM agents WHERE worker_type = 'internal' AND shift_state = 'active' AND name IN ('Architect','Circuit','Dispatch','Value','CodeSmith','Thorn','Cortex','Nova','Scribe','Scholar','Envoy','Sage','Zenith','Crucible','Luna','Nexus') ORDER BY department"
```

Expected: 16 rows, all with proper First Last display_name, no code names in parentheses.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/102_roster_human_staff.sql
git commit -m "feat: human staff name cleanup — proper First Last names, diverse global representation"
```

---

### Task 5: Decommission Surplus Agents

**Files:**
- Create: `database/migrations/103_decommission_surplus.sql`

- [ ] **Step 1: Create decommission migration**

Create `database/migrations/103_decommission_surplus.sql`:

```sql
-- ============================================================
-- LLM Ecosystem Redesign — Decommission Surplus Agents
-- Keeps: 34 AI acronym + 16 human staff = 50 active roster
-- Decision #441
-- ============================================================

BEGIN;

-- Decommission human-named internal agents not in the kept-16 list
-- These are surplus staff replaced by the streamlined roster
UPDATE agents SET shift_state = 'decommissioned'
WHERE worker_type = 'internal'
AND shift_state NOT IN ('decommissioned')
AND name IN (
    'DataMind',   -- Analytics (winding_down already)
    'Delphi',     -- Analytics
    'Wordsmith',  -- Creative
    'Beacon-A',   -- Engineering
    'Forge',      -- Engineering (human Forge, not F.O.R.G.E.)
    'Onyx',       -- Engineering
    'Wrench',     -- Engineering
    'Atlas',      -- Engineering
    'Runway',     -- Documentation
    'Quill',      -- Documentation (human Quill, not Q.U.I.L.L.)
    'Catalyst',   -- HR
    'Oracle',     -- Finance
    'Uptime',     -- Operations
    'Pulse',      -- Marketing
    'Cipher',     -- Research
    'Scout',      -- Research
    'Spark-Jr',   -- Research
    'Helix'       -- Executive/Research
);

-- Decommission human-named contractor agents (replaced by cloud providers)
UPDATE agents SET shift_state = 'decommissioned'
WHERE worker_type = 'contractor'
AND shift_state NOT IN ('decommissioned')
AND name IN ('Pixel', 'Lens', 'Atom', 'Prism', 'Spark');

COMMIT;
```

- [ ] **Step 2: Pre-check — verify no autonomy jobs reference these agents by ID**

```bash
docker exec archie_database psql -U archie -d archie -t -c "
SELECT name FROM agents WHERE name IN ('DataMind','Delphi','Wordsmith','Beacon-A','Onyx','Wrench','Atlas','Runway','Catalyst','Oracle','Uptime','Pulse','Cipher','Scout','Spark-Jr','Helix','Pixel','Lens','Atom','Prism','Spark') AND shift_state != 'decommissioned'
"
```

Verify these are the agents you expect to decommission.

- [ ] **Step 3: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/103_decommission_surplus.sql
```

- [ ] **Step 4: Verify roster count**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT worker_type, shift_state, COUNT(*)
FROM agents
GROUP BY worker_type, shift_state
ORDER BY worker_type, shift_state
"
```

Expected active roster: ~29 ai active + 5 ai barracked + 16 internal active = 50 roster. Rest decommissioned.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/103_decommission_surplus.sql
git commit -m "feat: decommission 23 surplus agents — streamlined to 50-agent roster"
```

---

### Task 6: Delete Unused Ollama Models

**Files:** None (Ollama CLI operations only)

- [ ] **Step 1: Verify no agent references the models being deleted**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT name, model FROM agents
WHERE model IN ('qwen3-coder-cpu:latest', 'minicpm-v-cpu:latest', 'qwen25-classify:latest', 'qwen2.5:1.5b')
AND shift_state != 'decommissioned'
"
```

Expected: 0 rows (no active agent uses these).

- [ ] **Step 2: Check current disk usage**

```bash
df -h /mnt/llm_drive
```

Note the "Used" value (should be ~25GB).

- [ ] **Step 3: Delete unused models**

```bash
curl -s -X DELETE http://192.168.1.200:11434/api/delete -d '{"name": "qwen3-coder-cpu:latest"}'
curl -s -X DELETE http://192.168.1.200:11434/api/delete -d '{"name": "minicpm-v-cpu:latest"}'
curl -s -X DELETE http://192.168.1.200:11434/api/delete -d '{"name": "qwen25-classify:latest"}'
curl -s -X DELETE http://192.168.1.200:11434/api/delete -d '{"name": "qwen2.5:1.5b"}'
```

- [ ] **Step 4: Verify disk savings**

```bash
df -h /mnt/llm_drive
curl -s http://192.168.1.200:11434/api/tags | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Models remaining: {len(d[\"models\"])}')"
```

Expected: ~59GB freed, ~17 models remaining.

- [ ] **Step 5: Commit a note (no code change, but document it)**

```bash
git commit --allow-empty -m "chore: deleted 4 unused Ollama models — saved ~59GB (qwen3-coder-cpu, minicpm-v, qwen25-classify, qwen2.5:1.5b)"
```

---

### Task 7: Deploy & Verify

- [ ] **Step 1: Restart platform to pick up module_registry changes**

```bash
cd /mnt/archie_brain
docker compose restart archie_platform
```

- [ ] **Step 2: Wait for startup and check logs**

```bash
docker logs --tail 20 archie_platform
```

Expected: No errors, Google Work Suite module loaded, directory module disabled.

- [ ] **Step 3: Verify Google Work Suite accessible**

Open `http://192.168.1.200:3000/tools/google-work-suite` in browser. Should load the OAuth connection page.

- [ ] **Step 4: Verify directory module disabled**

Open `http://192.168.1.200:3000/tools/directory` — should return 404 or redirect.

- [ ] **Step 5: Verify DHQ Roster tab shows updated agents**

Open `http://192.168.1.200:3000/tools/department-hq` → Roster tab. Verify:
- A.R.C.H.I.E. shows as active with dolphin3-8k
- F.O.R.G.E. shows as active
- M.A.R.K.E.T., E.M.B.E.R., S.H.I.E.L.D., E.T.H.O.S., A.R.M.A.D.A. show as AI type
- Human staff show proper First Last names

- [ ] **Step 6: Verify DHQ Contractors tab shows updated tiers**

Open DHQ → Contractors tab. Verify 25 providers with correct tier ordering and C.R.E.E.D. compliance badges.

- [ ] **Step 7: Update Dev HQ tracking**

```
mcp complete_task — Task #1895 (Audit loaded models)
mcp create_task — "Phase 3: Dispatch redesign — capability-aware routing"
mcp create_task — "Phase 4: Welfare system — real metrics"
mcp create_task — "Phase 5: Academy rework — competency testing"
mcp create_task — "Phase 6: Telegram unification — A.R.C.H.I.E. voice"
mcp update_project_understanding — Project #261
```

- [ ] **Step 8: Final commit — push branch**

```bash
git push origin feat/code-health-audit-pipeline
```

---

## Summary

| Task | What It Does | Estimated Effort |
|------|-------------|-----------------|
| 1 | Disable directory module, clean screenshots | tiny |
| 2 | Foundation migration (capabilities, contractors, tiers) | medium |
| 3 | AI roster restructure (models, conversions, reinstatements) | medium |
| 4 | Human staff name cleanup (16 agents, diverse names) | small |
| 5 | Decommission 23 surplus agents | small |
| 6 | Delete 4 unused Ollama models (~59GB saved) | small |
| 7 | Deploy, verify, update Dev HQ | small |

**Total: 7 tasks, ~45 minutes of execution time.**

After this plan completes: 50-agent roster is live, models are purpose-matched, contractors are tiered, foundation is set for Phase 3 (dispatch), Phase 4 (welfare), Phase 5 (academy), and Phase 6 (telegram).
