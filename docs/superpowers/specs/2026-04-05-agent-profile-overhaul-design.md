# Agent Profile Overhaul — Phase 1 Design Spec

**Date**: 2026-04-05
**Project**: Business Launch Readiness (#220)
**Decision**: #389 (Open Source Strategy), #390 (KBS Premium)
**Status**: Draft

---

## Goal

Clean up all 123 agent profiles so every agent has: complete identity data, accurate portrait reflecting their actual ethnicity/gender, a working system prompt, and an email address. This is the foundation for Phases 2-6 (business pipeline, email provisioning, agent capabilities, social media).

## Current State

| Field | Coverage | Notes |
|-------|----------|-------|
| display_name | 123/123 (100%) | Complete |
| bio | 123/123 (100%) | Complete |
| title | 121/123 (98%) | 2 missing |
| avatar_url | 107/123 (87%) | 16 missing |
| system_prompt | 71/123 (58%) | 52 missing — Legal 0%, Finance 33%, HR 33% |
| portrait files | ~108 PNGs | Many don't match agent ethnicity — whitewashed |
| email | 0/123 (0%) | Column doesn't exist yet |
| identity fields | Varies | gender, ethnicity, age_range, appearance_notes — gaps unknown |

## Design

### 1. System Prompt Architecture

**Structure: Department base + role specialization**

Each agent's system_prompt follows this format:

```
[DEPARTMENT BASE]
You are a member of the {Department Name} department at Kytran Empowerment,
led by {Director Acronym} ({Director Display Name}). Your department is
responsible for {department mission}. You operate on the {Floor} floor.

[ROLE SPECIALIZATION]
Your name is {display_name}. Your role is {title}.
{Unique personality, specialty, tools, communication style}

[OPERATIONAL CONTEXT]
- You have an email address: {email}
- You can be reached by other agents and external contacts
- You follow C.R.E.E.D. ethical guidelines
- You escalate decisions beyond your authority to your department director
```

**Work required:**
- Write 16 department base prompts (one per department)
- Write role-specific sections for all 52 agents missing prompts
- Review and migrate 71 existing prompts to the new format for consistency
- Director prompts are unique — they define department culture, not follow it

**Weakest departments (priority order):**
1. Legal & Regulatory (G.A.V.E.L.) — 0/5 prompts
2. Finance & Accounting (L.E.D.G.E.R.) — 2/6 prompts
3. Human Resources & Culture (K.I.N.) — 2/6 prompts
4. Marketing & Communications (S.I.G.N.A.L.) — 3/6 prompts

### 2. Portrait Regeneration

**Problem:** Current portraits skew white regardless of agent ethnicity. Asian agents look white, Black agents may be too light. The generation pipeline doesn't enforce identity strongly enough.

**Fix:**
1. Audit identity fields for all 123 agents — fill any blank gender, ethnicity, age_range, appearance_notes
2. Review the Department HQ portrait generation pipeline (`/platform_v2/tools/department_hq/`)
3. Update portrait generation prompts to strongly enforce:
   - Ethnicity and skin tone (explicit, not suggested)
   - Gender presentation
   - Age range
   - Any appearance_notes (hair, features, style)
4. Regenerate all 123 portraits — photorealistic professional headshot style
5. Store as PNGs in `/platform_v2/static/media/portraits/`
6. Update `avatar_url` for all agents

**Quality gate:** After generation, visually verify a sample from each ethnicity/gender category before bulk applying.

### 3. Email Provisioning

**Schema change:**
```sql
ALTER TABLE agents ADD COLUMN IF NOT EXISTS email VARCHAR(255);
```

**Email format rules:**
- Directors (16): `{acronym_lowercase}@kytranempowerment.com`
  - A.R.C.H.I.E. → `archie@kytranempowerment.com`
  - V.I.G.I.L. → `vigil@kytranempowerment.com`
  - F.O.R.G.E. → `forge@kytranempowerment.com`
- Staff (107): `{firstname}.{lastname}@kytranempowerment.com`
  - Jin Park → `jin.park@kytranempowerment.com`
  - DataMind → `datamind@kytranempowerment.com` (code-name agents use codename)

**Stalwart provisioning:**
- Create all 123 mailboxes via Stalwart admin API (port 443/8080)
- Set generated passwords, store securely (not in agents table — separate credentials table or vault)
- Verify DKIM signing works for agent-sent mail

**UI integration:**
- Department HQ: show email field in agent profile, editable by admin
- Directory (client-facing): show email in agent cards
- Agent service: `create_agent()` and `update_agent()` support email field

**Future (not this phase):**
- Gmail accounts for each agent (Google Work Suite integration)
- Gmail credentials stored in agent profile for autonomous email access
- Social media accounts per agent

### 4. Data Completeness Sweep

| Task | Count | Action |
|------|-------|--------|
| Missing titles | 2 | Assign appropriate titles |
| Blank identity fields | TBD | Audit and fill gender, ethnicity, age_range, appearance_notes |
| display_name consistency | Verify | Staff = human names, Directors = acronyms |
| Department assignments | Verify | All 123 agents assigned to correct department |
| Duplicate/orphan agents | Check | Any inactive or duplicate entries to clean up |

### 5. Validation Criteria

Phase 1 is complete when:
- [ ] All 123 agents have system_prompt (department base + role section)
- [ ] All 123 agents have accurate portraits matching their identity
- [ ] All 123 agents have email column populated
- [ ] All 123 mailboxes created on Stalwart
- [ ] All identity fields filled (no blanks in gender, ethnicity, age_range)
- [ ] Department HQ shows email in agent profiles
- [ ] Directory page shows email in agent cards
- [ ] Portrait pipeline updated to enforce ethnicity/appearance

## Dependencies

- Stalwart mail server running (confirmed: `stalwart_mail` container active)
- Department HQ portrait pipeline functional
- ComfyUI or AI image generation available for portraits
- Agent service layer (`agent_service.py`) handles all mutations

## Out of Scope (Future Phases)

- Gmail account provisioning (Phase 3+)
- Agent autonomous email reading/sending (Phase 4)
- Social media account creation (Phase 6)
- Department email routing loops (Phase 4)
- Agent capability system (Media Studio, posting) (Phase 5)

## Technical Notes

- All agent mutations go through `agent_service.py` — no direct SQL
- Portrait files stored at `/platform_v2/static/media/portraits/{codename}.png`
- Identity fields editable via Department HQ identity routes
- Stalwart uses internal directory (RocksDB) — accounts managed via admin API
- Email passwords should NOT be in the agents table — use a separate secure storage
