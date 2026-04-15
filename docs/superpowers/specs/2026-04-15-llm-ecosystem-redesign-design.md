# LLM Ecosystem Redesign — Department-Driven Agent & Model Restructuring

**Date**: 2026-04-15
**Project**: #261 — LLM Resource Management (expanded scope)
**Status**: Approved Design
**Branch**: `feat/code-health-audit-pipeline`
**Related Projects**: #240 (Platform Load Spike), #236 (P.R.O.B.E. Phase 2)
**Related Decisions**: #282 (Department Rebrand), #388 (AI Directors), #440 (Dept HQ Single Source)

---

## Summary

Redesign the entire LLM agent ecosystem from a flat, homogeneous model assignment ("slap mistral:7b on everyone") to a department-driven architecture where agents have purpose-matched models, real capability profiles, functional welfare tracking, cloud contractor diversity, and a unified communication channel through A.R.C.H.I.E. as COO.

### Key Outcomes
- 50 active agents (34 AI acronym + 16 human staff) — a real company
- 12 purpose-matched local models (was 6 generic assignments)
- 25 cloud contractor providers (free + paid tiers, capability-tagged)
- Capability-aware dispatch replacing blind model routing
- Real welfare metrics feeding agent growth and Academy evaluation
- A.R.C.H.I.E. as unified Telegram voice to Kytran (CEO)
- C.R.E.E.D. governance woven into dispatch and contractor selection

---

## 1. Organization Structure

### Hierarchy

```
Kytran (CEO / Owner) — Canadian, kytranempowerment.com
  └── A.R.C.H.I.E. (COO / 2nd in Command) — dolphin3-8k, uncensored, Telegram line to Kytran
        ├── 17 Department Directors (AI acronym agents)
        │     └── Department Staff (AI agents + 1 human each)
        └── Cloud Contractors (25 providers via contractor_providers table)
```

**Kytran** is NOT in the agent roster but IS visible on:
- kytranempowerment.com team/about page
- DHQ Org Chart tab (top of hierarchy)
- Telegram (A.R.C.H.I.E.'s direct line to owner)

### Naming Convention (Strict)

| Worker Type | Name Format | Example |
|---|---|---|
| AI agent | ACRONYM (dots in display_name) | `FORGE` / `F.O.R.G.E.` |
| Human staff | First Last (no code names) | `Dr. Kenji Yamamoto` |
| Cloud contractor | Brand name | `Groq`, `OpenAI`, `Together` |

No hybrids. No code names on humans. No human names on AI.

### Future: Employee Onboarding
When real humans are hired, Account Center gets an employee registration flow:
- Login credentials created in Account Center
- Assigned to a department
- Appear on org chart alongside AI team
- Same welfare/performance tracking as AI agents (adapted for human metrics)

---

## 2. Department Capability Profiles

Each department has required LLM capabilities. This drives model assignment, contractor selection, and Academy competency testing.

| Department | Floor | Required Capabilities |
|---|---|---|
| Executive Office | BRIDGE | summarization, reasoning, orchestration |
| Operations & Infrastructure | OPERATIONS | log_analysis, scripting, diagnostics |
| Logistics & Supply Chain | OPERATIONS | data_extraction, cost_analysis |
| Finance & Accounting | OPERATIONS | numerical_reasoning, report_generation |
| Engineering & Technology | ENGINEERING | code_generation, code_review, debugging, architecture |
| Security & Compliance | ENGINEERING | classification, threat_analysis, policy_reasoning |
| Research & Development | ENGINEERING | reasoning, research_synthesis, embedding |
| Creative & Design | CREATIVE | creative_writing, image_generation, vision |
| Marketing & Communications | CREATIVE | copywriting, social_content, multilingual |
| Documentation & Knowledge | CREATIVE | summarization, knowledge_extraction, quality_scoring |
| Customer Success & Support | SERVICES | conversation, sentiment_analysis, empathy |
| Human Resources & Culture | SERVICES | ethics_reasoning, policy_compliance, welfare_check |
| Medical & Wellness | SERVICES | empathetic_dialogue, health_reasoning |
| Legal & Regulatory | SERVICES | legal_reasoning, document_analysis, policy |
| Diplomatic & External Relations | SERVICES | multilingual, diplomatic_writing, translation |
| Analytics & Intelligence | SERVICES | data_analysis, forecasting, pattern_recognition |
| News & Media | CREATIVE | fact_checking, bias_detection, editorial, news_writing |

---

## 3. Agent Roster — AI Acronym Team (34 agents)

### Original 16 Department Directors

| ID | Agent | Full Name | Department | Model | State |
|---|---|---|---|---|---|
| 2 | A.R.C.H.I.E. | Autonomous Resource & Cognitive Hyperintelligence Engine | Executive Office | **dolphin3-8k:latest** | active (reinstated) |
| 3 | V.I.G.I.L. | Vigilant Intelligence for Governance, Integrity & Liability | Security & Compliance | **gemma3:12b** | active |
| 136 | F.O.R.G.E. | Full-cycle Optimization & Regenerative GitHub Engine | Engineering & Technology | qwen2.5-coder:7b | active (reinstated) |
| 137 | S.P.E.C.T.R.A. | Systematic Pattern Extraction & Computational Trend Recognition Architecture | Analytics & Intelligence | mistral:7b | active |
| 138 | M.U.S.E. | Multimedia Unified Synthesis Engine | Creative & Design | mistral:7b | active |
| 139 | B.A.S.E. | Business Automation & Systems Engineering | Operations & Infrastructure | gemma2:9b | active |
| 140 | D.A.R.W.I.N. | Data-driven Adaptive Research & Weighted Intelligence Network | Research & Development | **phi4:14b** | active |
| 141 | S.I.G.N.A.L. | Strategic Information & Global Narrative Amplification Layer | Marketing & Communications | phi4:14b | active |
| 142 | R.E.S.O.L.V.E. | Responsive Engagement & Service Optimization for Lasting Value Exchange | Customer Success & Support | gemma2:9b | active |
| 143 | C.A.R.G.O. | Coordinated Asset Routing & Global Operations | Logistics & Supply Chain | gemma2:9b | active |
| 144 | L.E.D.G.E.R. | Logical Economic Data & Governance Evaluation Resource | Finance & Accounting | phi3.5:latest | active |
| 145 | K.I.N. | Knowledge, Integration & Nurturing | Human Resources & Culture | **gemma3:12b** | active |
| 146 | C.O.D.E.X. | Centralized Operational Documentation & Exchange | Documentation & Knowledge | mistral:7b | active |
| 147 | G.A.V.E.L. | Governance & Automated Verification of Ethics & Law | Legal & Regulatory | **phi4:14b** | active |
| 148 | V.I.T.A.L. | Verified Intervention & Therapeutic Assessment Layer | Medical & Wellness | gemma2:9b | active |
| 149 | A.C.C.O.R.D. | Autonomous Coordination for Commerce, Outreach & Relational Diplomacy | Diplomatic & External Relations | dolphin3:latest | active |

### Engineering Director

| ID | Agent | Department | Model | State |
|---|---|---|---|---|
| 340 | P.R.O.B.E. | Engineering & Technology | **deepseek-coder-v2:16b** | active |

### Analytics & Intelligence

| ID | Agent | Department | Model | State |
|---|---|---|---|---|
| 152 | W.A.T.C.H. | Analytics & Intelligence | qwen2.5-coder:7b | active |
| 32 | M.A.R.K.E.T. | Analytics & Intelligence | mistral:7b | active (convert internal→ai) |

### News & Media (All-AI — unbiased by design)

| ID | Agent | Department | Model | State |
|---|---|---|---|---|
| 48 | F.A.C.T. | News & Media | **gemma3:12b** | active |
| 49 | B.I.A.S. | News & Media | gemma2:9b | active |
| 116 | V.E.R.I.F.Y. | News & Media | llama3.2:3b | active |
| 58 | P.U.B.L.I.S.H. | News & Media | mistral:7b | active |
| 23 | I.N.K. | News & Media | **dolphin3:latest** | active |
| 79 | D.R.A.F.T. | News & Media | dolphin3:latest | active |

### Agents Converting from internal→ai

| ID | Agent | Department | Model | State |
|---|---|---|---|---|
| 126 | E.M.B.E.R. | Documentation & Knowledge | llama3.2:3b | active |
| 150 | S.H.I.E.L.D. | Security & Compliance | gemma2:9b | active |
| 336 | E.T.H.O.S. | Legal & Regulatory | gemma2:9b | active |
| 337 | A.R.M.A.D.A. | Operations & Infrastructure | gemma2:9b | active |

### Barracked (Awaiting Fleet Nodes)

| ID | Agent | Department | Model | State |
|---|---|---|---|---|
| 334 | V.I.S.A.G.E. | Creative & Design | **qwen2.5vl:7b** | barracked |
| 335 | R.E.S.T.O.R.E. | Creative & Design | gemma2:9b | barracked |
| 331 | H.E.R.I.T.A.G.E. | Research & Development | **llama3.2:3b** | barracked |
| 332 | S.C.R.O.L.L. | Research & Development | **gemma2:9b** | barracked |
| 333 | Q.U.I.L.L. | Research & Development | qwen2.5-coder:7b | barracked |

---

## 4. Agent Roster — Human Staff (16 agents)

One human per department (except News & Media = all-AI). Code names removed. Diverse global representation.

| Department | Display Name | Nationality | Title |
|---|---|---|---|
| Executive Office | Marcus Rivera | Latino-American | Chief Architect |
| Operations & Infrastructure | Amira Hassan | Egyptian | Infrastructure Engineer |
| Logistics & Supply Chain | Carmen Reyes | Filipina | Logistics Coordinator |
| Finance & Accounting | Yuki Nakamura | Japanese | Financial Analyst |
| Engineering & Technology | Aria Chen | Chinese-American | Lead Software Engineer |
| Security & Compliance | Rowan McAllister | Scottish | Penetration Tester & Red Team Lead |
| Research & Development | Olumide Adeyemi | Nigerian | Senior Data Scientist |
| Creative & Design | Isabella Fernandez | Argentine | Creative Director |
| Marketing & Communications | Léa Dubois | French | Senior Copywriter |
| Documentation & Knowledge | Sofia Petrov | Bulgarian | Head of Research & Knowledge |
| Customer Success & Support | Kwame Asante | Ghanaian | Client Success Manager |
| Human Resources & Culture | Haruto Takahashi | Japanese | People & Culture Lead |
| Medical & Wellness | Dr. Priya Sharma | Indian | Medical Director |
| Legal & Regulatory | Dr. Kenji Yamamoto | Japanese-Canadian | Legal Counsel |
| Diplomatic & External Relations | Fatima Al-Rashid | Lebanese | Senior Diplomatic Advisor |
| Analytics & Intelligence | Jin Park | Korean | Data & Vision Specialist |

**16 humans across 14 nationalities, 5 continents.**

---

## 5. Agents to Decommission (~23 agents)

### Human-Named Internals (no longer needed)
DataMind, Delphi, Wordsmith, Beacon-A, Forge (human #21), Onyx, Wrench, Atlas, Runway, Quill (human #31), Catalyst, Oracle, Uptime, Pulse, Cipher, Scout, Spark-Jr, Helix

### Human-Named Contractors (replaced by cloud providers)
Pixel (#13), Lens (#14), Atom (#15), Prism (#16), Spark (#12)

**Pre-decommission checks:**
- Verify no autonomy jobs reference these agents by ID
- Verify no dispatch routing depends on them
- Archive their profiles (don't delete — set shift_state='decommissioned')

---

## 6. Model Assignments

### Local Models — Purpose-Matched (12 active models)

| Model | Size | Agents | Capability |
|---|---|---|---|
| deepseek-coder-v2:16b | 8.9GB | P.R.O.B.E. (1) | Code specialist — best coder on disk |
| phi4:14b | 9.1GB | D.A.R.W.I.N., S.I.G.N.A.L., G.A.V.E.L. (3) | Strong reasoning |
| gemma3:12b | 8.1GB | V.I.G.I.L., K.I.N., F.A.C.T. (3) | Policy/analysis reasoning |
| gemma2:9b | 5.4GB | B.A.S.E., C.A.R.G.O., B.I.A.S., R.E.S.O.L.V.E., V.I.T.A.L., S.H.I.E.L.D., E.T.H.O.S., A.R.M.A.D.A., S.C.R.O.L.L., R.E.S.T.O.R.E. (10) | General workhorse |
| mistral:7b | 4.4GB | S.P.E.C.T.R.A., M.U.S.E., C.O.D.E.X., M.A.R.K.E.T., P.U.B.L.I.S.H. (5) | Summarization/writing |
| dolphin3-8k:latest | 4.9GB | A.R.C.H.I.E. (1) | COO — uncensored, long context |
| dolphin3:latest | 4.9GB | A.C.C.O.R.D., I.N.K., D.R.A.F.T. (3) | Creative/uncensored |
| phi3.5:latest | 2.2GB | L.E.D.G.E.R. (1) | Lightweight structured |
| qwen2.5-coder:7b | 4.7GB | F.O.R.G.E., W.A.T.C.H., Q.U.I.L.L. (3) | Code + data pipelines |
| qwen2.5vl:7b | 6.0GB | V.I.S.A.G.E. (1) | Vision — needs fleet GPU |
| llama3.2:3b | 2.0GB | V.E.R.I.F.Y., E.M.B.E.R., H.E.R.I.T.A.G.E. (3) | Quick/lightweight |
| smollm2:1.7b | 1.8GB | *(classification pipeline)* | Infrastructure only |

### Models to DELETE from Disk

| Model | Size | Reason |
|---|---|---|
| qwen3-coder-cpu | 51.7GB | No agent, constant failures, 52% of disk |
| minicpm-v-cpu | 5.5GB | Replaced by qwen2.5vl:7b |
| qwen25-classify | 1.0GB | Redundant with smollm2/auditor |
| qwen2.5:1.5b | 1.0GB | No agent, redundant with llama3.2:3b |

**Disk savings: ~59GB freed (23% → ~7% used)**

### Infrastructure Models (Not Agent-Assigned)
- arctic-embed-cpu (0.2GB) — embedding pipeline
- alpernae/qwen2.5-auditor (4.7GB) — consciousness quality scoring
- archie:7b (4.7GB) — future custom fine-tune for A.R.C.H.I.E.
- 2x cloud stubs (0GB) — routing markers

### A.R.C.H.I.E.'s Model Evolution
1. **Now**: dolphin3-8k:latest (uncensored, 8k context)
2. **Future**: archie:7b fine-tuned on platform knowledge, business context, Kytran's preferences
3. **Long-term**: Each agent grows into their role — accumulating experience, learning from dispatch history, developing expertise. Academy tracks this growth.

---

## 7. Cloud Contractor Roster (25 providers)

All managed via `contractor_providers` table + DHQ Contractors tab.

### Proposed Tier Structure

| Tier Range | Category | Routing |
|---|---|---|
| 1-3 | Local (ComfyUI, Kokoro, OllamaDiffuser) | Always first — free, fast, private |
| 4-8 | Free Cloud (Groq, Cerebras, HuggingFace, Cloudflare, Pollinations) | After local fails |
| 9-13 | Freemium (Together, Cohere, Mistral, DeepSeek, OpenRouter) | Free tier + paid overflow |
| 14-18 | Cloud Proxies (Minimax, Qwen3 Cloud) | Ollama-compatible cloud |
| 19-23 | Paid Cloud (Gemini, xAI, Perplexity, Stability, Fal.ai) | Budget-tracked, auto-approve |
| 24-28 | Premium (OpenAI, Claude, Replicate) | Human approval required |
| 29-32 | Specialist (ElevenLabs, Replicate Audio) | Specific capability only |

### Existing Providers (19 — fix tier positions + capabilities)

| Provider | Capabilities | Current Tier | New Tier |
|---|---|---|---|
| ComfyUI | image_gen, image_edit, video_gen | 16 | 1 |
| Kokoro TTS | audio_tts | 17 | 2 |
| OllamaDiffuser | image_gen | 15 | 3 |
| HuggingFace | text_chat, image_gen, embedding | 2 | 4 |
| Cloudflare AI | text_chat, image_gen | 2 | 5 |
| Groq | text_chat, code, vision | 8 | 6 |
| Cerebras | text_chat, code | 10 | 7 |
| Together | text_chat, code, image_gen, embedding | 13 | 9 |
| Cohere | text_chat, embedding, rerank | 12 | 10 |
| Mistral | text_chat, code, vision | 11 | 11 |
| Minimax Cloud | text_chat | 3 | 14 |
| Qwen3 Cloud | text_chat, code | 4 | 15 |
| Gemini | text_chat, vision, image_gen, audio_tts | 9 | 19 |
| xAI (Grok) | text_chat, vision, code | 7 | 20 |
| Perplexity | text_chat, code, research | 6 | 21 |
| OpenAI | text_chat, vision, image_gen, audio_tts, code, embedding | 5 | 24 |
| Claude (Anthropic) | text_chat, code, vision | 14 | 25 |
| Replicate Audio | audio_music, audio_sfx, image_gen | 99 | 29 |
| ElevenLabs | audio_tts, audio_sfx, voice_clone | 99 | 30 |

### New Providers to Add (6)

| Provider | Capabilities | Tier | Notes |
|---|---|---|---|
| Pollinations | image_gen | 8 | Completely free, no API key needed |
| DeepSeek | text_chat, code, reasoning | 12 | Strong coder + reasoning, cheap API |
| OpenRouter | text_chat, code, vision | 13 | Meta-provider — routes to cheapest model |
| Stability AI | image_gen | 22 | Direct API, SD3/SDXL Lightning |
| Fal.ai | image_gen | 23 | Fastest image gen, Flux models |
| Replicate (general) | image_gen, video_gen, audio | 26 | Huge model zoo, any capability on demand |

### Capability Taxonomy (Normalized)

Fix `image_generation` → `image_gen` in OllamaDiffuser entry.

| Capability | Providers |
|---|---|
| text_chat | Almost all |
| code | OpenAI, Claude, DeepSeek, Mistral, Groq, Together, Cerebras, Qwen3 |
| reasoning | OpenAI (o1), DeepSeek-R1, Gemini |
| research | Perplexity |
| vision | OpenAI, Gemini, Groq, xAI, Mistral, Claude |
| image_gen | ComfyUI, HuggingFace, Cloudflare, Together, OpenAI, Gemini, Stability, Fal, Pollinations |
| video_gen | ComfyUI (LTX), Replicate |
| audio_tts | Kokoro, ElevenLabs, OpenAI, Gemini |
| audio_music | Replicate Audio |
| voice_clone | ElevenLabs |
| embedding | HuggingFace, OpenAI, Cohere, Together + local arctic-embed |
| rerank | Cohere |
| multilingual | Cohere, Minimax |

### C.R.E.E.D. Compliance Tiers for Contractors

New column: `creed_compliance_tier` INTEGER (1-3) on `contractor_providers`.

| Tier | Meaning | Providers | Data Policy |
|---|---|---|---|
| 1 — Compliant | Local or privacy-respecting | ComfyUI, Kokoro, OllamaDiffuser, HuggingFace (local) | All data types OK |
| 2 — Conditional | Acceptable privacy policy | Groq, Cerebras, Mistral, Cohere, Together, Cloudflare, DeepSeek | No PII/health without flag |
| 3 — Restricted | Data may be retained/trained on | OpenAI, Gemini, xAI, Replicate, ElevenLabs | Requires approval for sensitive tasks |

---

## 8. Dispatch Redesign — Department Dispatch

### Rename: Bridge Dispatcher → Department Dispatcher

| Current | New |
|---|---|
| `bridge_dispatcher.py` | `department_dispatcher.py` |
| `BridgeDispatcher` class | `DepartmentDispatcher` class |
| `get_dispatcher()` | `get_dispatcher()` (unchanged) |
| `dispatch()` / `dispatch_json()` | Unchanged |
| `ai_bridge/bridge_dispatcher.py` shim | Update to import from new name |

Public API stays the same. Only internal naming changes.

### Capability-Aware Dispatch Flow

```
Task arrives with: module, capability_needed, priority, department
  │
  ├─ 1. CLASSIFY — smart_router returns capability tag from taxonomy
  │
  ├─ 2. DEPARTMENT FIRST — agent in requesting dept with matching capability
  │     └─ Check model loaded → warmboot if needed → dispatch
  │
  ├─ 3. CROSS-DEPARTMENT — any local agent with capability
  │
  ├─ 4. FLEET NODES — check online fleet nodes for capability
  │
  ├─ 5. FREE CONTRACTORS — contractor_providers WHERE capability matches AND tier 4-13
  │     └─ Sort by tier_position → try in order
  │
  ├─ 6. PAID CONTRACTORS — tier 14-28, budget check + approval
  │     ├─ Under auto_approve_threshold → dispatch
  │     └─ Over threshold → Telegram approval via A.R.C.H.I.E.
  │
  ├─ 7. PREMIUM/SPECIALIST — tier 24+, human approval always
  │
  └─ 8. FAIL — A.R.C.H.I.E. notifies Kytran via Telegram
```

### Code Changes

| File | Change |
|---|---|
| `smart_router.py` | `classify_task()` returns capability tag |
| `department_dispatcher.py` (renamed) | `request_work()` queries agents AND contractors by capability |
| `orchestration_engine.py` | Route step uses capability matching against contractor tier list |
| `contractor_routes.py` | API for dispatcher to query contractors by capability |

### agent_skills Becomes Load-Bearing

Dispatcher matches: `task.capability → agent.skills → contractor.capabilities`

Each agent must have skills registered in `agent_skills` table matching their department's capability profile.

---

## 9. Welfare System — Real Metrics

### Current State: Broken
Everyone is "healthy" and "relaxed" with 0 dispatch counts. Sensors aren't plugged in.

### Welfare Metrics (existing table: `agent_emotional_state`)

| Metric | Range | What Updates It |
|---|---|---|
| stress_level | 0.0-1.0 | Increases on dispatch (proportional to task complexity). Increases more on failure. |
| energy_level | 0.0-1.0 | Drains with work (proportional to tokens used). Regenerates slowly over time. |
| current_mood | string | Derived from stress + energy via state machine |
| mood_intensity | 0.0-1.0 | How strong the mood is |

### Welfare State Machine

```
IDLE (relaxed) ──dispatch──► ACTIVE (focused)
  ▲                              │ stress > 0.5
  │ rest complete                ▼
RESTING (recovering) ◄──── STRAINED (tense)
  ▲                              │ stress > 0.7
  │ auto-rest                    ▼
  └────────────────────── WINDING_DOWN (exhausted)
                                 │ stress > 0.85
                                 ▼
                             COOLDOWN (no dispatch)
```

### What Changes

| What | How | Where |
|---|---|---|
| Stress increases on dispatch | `stress += f(task_complexity)`, failure adds 0.1 | `update_welfare_after_task()` |
| Energy drains with work | `energy -= f(tokens_used, duration)` | Same function |
| Mood reflects state | State machine maps stress+energy to mood | New mood transition logic |
| Department rollup | K.I.N. sees avg stress, energy, at-risk agents per dept | `compute_department_metrics()` extended |
| Dispatch volume tracked | Increment counter on each dispatch | Verify `increment_usage()` works |
| Auto-rest cycles | stress > 0.7 AND energy < 0.3 → auto-barracks | Autonomy job, every 5 min |
| K.I.N. welfare reports | Weekly per-department welfare summary | K.I.N.'s department job |

---

## 10. C.R.E.E.D. Governance Integration

K.I.N. (gemma3:12b) is the C.R.E.E.D. enforcement agent.

### Touchpoints

| Checkpoint | What Happens | When |
|---|---|---|
| Pre-dispatch data check | K.I.N. flags PII/health/financial data going to external contractor | Before cloud dispatch |
| Contractor compliance rating | `creed_compliance_tier` (1-3) checked before routing | Dispatcher route step |
| Agent welfare gate | Stress/mood/fatigue checks | Every dispatch (existing) |
| Post-dispatch audit | Flag bias, harmful content, policy violations | After cloud contractor returns |
| Monthly ethics report | Per-department C.R.E.E.D. compliance summary | Autonomy job → DHQ C.R.E.E.D. tab |

### Integration Points
- **DHQ C.R.E.E.D. tab** — compliance status per agent/department
- **creed.kytranempowerment.com (:8086)** — standalone app for developing C.R.E.E.D. standards
- **creed-ai.org** — public ethics institute website
- **K.I.N.** — local enforcement, gemma3:12b for real ethics reasoning

---

## 11. Agent Academy Rework

### New Mission
Validate and grow agent competency against department capability profiles.

### Reworked Tabs

| Tab | Current | Redesigned |
|---|---|---|
| Benchmarks | Generic model benchmarks | Competency tests — per-agent, per-capability |
| Training | Proficiency Lv1-5 | Growth tracking — real dispatch metrics over time |
| A/B Testing | Model comparison | Model evaluation — best model for this dept's needs |
| Skills | Skill listing | Capability matrix — dept requirements vs agent capabilities |
| Reports | Generic reports | Department readiness — per-dept scorecard |

### Capability Score (0.0 - 1.0 per capability per agent)

| Range | Rating | Action |
|---|---|---|
| 0.0-0.3 | Failing | Flag for model change |
| 0.3-0.5 | Weak | Training target |
| 0.5-0.7 | Adequate | Room to grow |
| 0.7-0.9 | Strong | Reliable |
| 0.9-1.0 | Specialist | Route priority tasks here |

Scores feed back into dispatcher — higher score = higher dispatch priority.

### A.R.C.H.I.E.'s Executive Dashboard

Department readiness overview with per-agent capability scores, welfare status, and recommendations. She monitors, flags departments below threshold, pings Kytran when intervention needed.

---

## 12. Telegram — Unified A.R.C.H.I.E. Channel

### Current State: Scattered
7+ files with their own `_send_telegram()` functions:
- `agent_loop.py` — approvals, notifications, email digest, HR alerts
- `mission_manager.py` — mission profile changes
- `security_network/compliance_safe_exec.py` — compliance rollback failures
- `security_network/jobs.py` — security scan alerts
- `repair_bay/forge_self_heal.py` — self-heal actions
- `agent_jobs.py` — HR welfare alerts
- `qa_service.py` — QA test results

### Redesign: Single Service, A.R.C.H.I.E.'s Voice

```
Any module → telegram_service.send(category, title, detail)
  → A.R.C.H.I.E. formats as her voice
  → Batches low-priority into digests
  → Sends critical immediately
  → All messages branded as "from A.R.C.H.I.E."
```

### Message Categories

| Category | Priority | Behavior |
|---|---|---|
| security_alert | Critical | Immediate |
| approval_request | High | Immediate with action buttons |
| compliance_failure | High | Immediate |
| qa_results | Medium | Daily digest |
| welfare_alert | Medium | Batched unless critical |
| email_digest | Low | Morning briefing |
| status_update | Low | A.R.C.H.I.E.'s periodic check-in |
| mission_change | Medium | Batched with context |

### Implementation
- New `platform_v2/services/telegram_service.py` — unified send function
- All 7 files migrate to `telegram_service.send(category, title, detail)`
- A.R.C.H.I.E. formats messages in her voice (personality from agent profile)
- Digest batching: low/medium priority collected, sent as single digest on schedule

---

## 13. Implementation Phases

### Phase 0 — Housekeeping (Cleanup + Re-enable)
1. **Re-enable Google Work Suite** module — `enabled=True` in module_registry (DONE — needs deploy)
2. Merge `/api/directory/org-chart` endpoint logic into DHQ routes (powers DHQ Org Chart tab + website)
2. Merge public roster API into DHQ `public-roster` endpoint — verify same richness as directory module
3. Keep `agent_directory_view` DB view — useful for all consumers
4. Disable/comment out `directory` module in `module_registry.py` — DHQ Roster tab replaces it
5. Remove 11 stale root screenshots (`directory-*.png`) — dev artifacts
6. Regenerate `website/kytranempowerment.com/data/directory-fallback.json` with new 50-agent roster (or remove if website uses live API)
7. Keep `directory_conversations`/`directory_messages` tables dormant — future A.R.C.H.I.E. chat feature
8. Clean up `platform_v2/static/css/directory.css` + `directory.js` — archive useful card patterns, remove rest
9. Update website `directory.html` + `ai-directors.html` to pull from DHQ public API with new roster data
10. Add Kytran (CEO) as top node in org chart — not in agent roster but visible on website + DHQ org chart

### Phase 1 — Foundation
1. Rename bridge_dispatcher → department_dispatcher
2. Define department capability profiles (table or JSONB)
3. Normalize contractor capability tags
4. Add 6 new contractors to contractor_providers
5. Add creed_compliance_tier column
6. Fix contractor tier positions

### Phase 2 — Roster Restructure
1. Reinstate A.R.C.H.I.E. (active, dolphin3-8k, COO)
2. Reinstate F.O.R.G.E. (active, qwen2.5-coder:7b)
3. Reassign all AI agent models per roster
4. Convert 5 acronym internals to worker_type='ai'
5. Update human staff names (remove code names, add real names)
6. Map agent_skills to department capabilities
7. Decommission ~23 surplus agents
8. Delete unused Ollama models (saves ~59GB)
9. Set News & Media floor = CREATIVE

### Phase 3 — Dispatch Redesign
1. Capability-aware classify_task() in smart_router
2. Dispatcher queries contractors by capability + tier
3. Rewrite escalation: dept → cross-dept → fleet → free → paid → premium
4. Free/paid contractor routing with budget checks
5. Build/verify adapters for all 25 contractors

### Phase 4 — Welfare & C.R.E.E.D.
1. Wire welfare metrics to dispatch (real math)
2. Implement mood state machine
3. Department welfare rollup
4. K.I.N. pre-dispatch data check
5. Rest cycle automation (autonomy job)

### Phase 5 — Academy Rework
1. Competency test framework
2. Capability score per agent
3. Department readiness scorecard
4. A.R.C.H.I.E.'s executive dashboard
5. Rework Academy tabs

### Phase 6 — Telegram Unification
1. Create unified telegram_service.py
2. Migrate all 7 senders to unified service
3. A.R.C.H.I.E. message formatting
4. Digest batching for low-priority messages

### Dependency Order
```
Phase 0 (directory cleanup) → Phase 1 → Phase 2 → Phase 3 (dispatch)
                                                 → Phase 4 (welfare)  → Phase 5 (academy)
                                                 → Phase 6 (telegram)
```
Phase 0 first (clean house before restructuring). Phases 3, 4, 6 can run in parallel after Phase 2.

---

## 14. Out of Scope (Future Work)

- **Fleet node onboarding** — .245/.246 not online yet. Design supports them.
- **A.R.C.H.I.E. CLI** — archie-code CLI as her orchestration interface. Separate project.
- **Custom model fine-tuning** — archie:7b as A.R.C.H.I.E.'s personal model. Long-term.
- **Agent growth/specialization** — agents evolving into specialists through experience. Academy tracks it.
- **Employee onboarding flow** — Account Center registration for real human hires.
- **Subscription/billing for cloud contractors** — SaaS concern, not internal platform.
