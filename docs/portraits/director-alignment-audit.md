# Director Flag Alignment — 3 Surfaces One Source of Truth

## All three surfaces read the same DB column

| Surface | API | Feeds from |
|---------|-----|-----------|
| Public `/directory.html` | `/api/public/directory` | `public_roster_service.py` → `public_agent_directory` view → `agents.is_department_ai` |
| Public `/ai-directors.html` | `/api/public/directory` (filtered `is_director=true`) | same as above |
| DHQ **Org Chart** tab | `/api/org-chart` | `agent_service.get_org_chart()` → `agents.is_department_ai` |
| DHQ **Roster** tab | `/api/roster` | `agent_service.list_agents()` → `agents.is_department_ai` |

**Conclusion**: fixing `agents.is_department_ai` cleans up all three surfaces automatically. One migration, one source of truth.

## The drift — 22 flagged directors, should be 17

### 5 departments with duplicate director flags (demote one per row)

| Department | Currently flagged | Keep as director | Demote to specialist |
|------------|-------------------|------------------|----------------------|
| Analytics & Intelligence | M.A.R.K.E.T. (32) + S.P.E.C.T.R.A. (137) | S.P.E.C.T.R.A. | **M.A.R.K.E.T.** |
| Documentation & Knowledge | C.O.D.E.X. (146) + E.M.B.E.R. (126) | C.O.D.E.X. | **E.M.B.E.R.** |
| Legal & Regulatory | E.T.H.O.S. (336) + G.A.V.E.L. (147) | G.A.V.E.L. | **E.T.H.O.S.** |
| Operations & Infrastructure | A.R.M.A.D.A. (337) + B.A.S.E. (139) | B.A.S.E. | **A.R.M.A.D.A.** |
| Security & Compliance | S.H.I.E.L.D. (150) + V.I.G.I.L. (3) | V.I.G.I.L. | **S.H.I.E.L.D.** |

### 2 unresolved — need your decision

1. **Engineering & Technology** — DB flags **F.O.R.G.E.** as director; MEMORY.md says **P.R.O.B.E.** is director (F.O.R.G.E. `winding_down`). DB shift_state says F.O.R.G.E. is `active`, contradicting MEMORY.md. **Which is canonical?**
2. **News & Media** — DB flags **F.A.C.T.** as director; MEMORY.md says "AI-only, no single director" (6 equal-rank agents). **Keep F.A.C.T. as director, or allow department with no director?** (data model currently requires one.)

## Hidden Org Chart bug

`agent_service.get_org_chart()` (agent_service.py:552-555) only keeps the LAST `is_department_ai=true` agent seen per department — the other flagged director is silently dropped from both the director slot AND the staff list. So right now 5 agents disappear entirely from the Org Chart tab.

## Migration 340 — proposed (blocked on 2 decisions above)

```sql
-- Demote 5 duplicate director flags
UPDATE agents SET is_department_ai=false, updated_at=NOW() WHERE id IN (32, 126, 336, 337, 150);

-- Engineering & Technology (pick one, per your decision)
-- UPDATE agents SET is_department_ai=false WHERE id=136;  -- if P.R.O.B.E. is canon, demote F.O.R.G.E.
-- UPDATE agents SET is_department_ai=true  WHERE id=340;  -- ... and promote P.R.O.B.E.

-- News & Media — keep F.A.C.T. OR demote depending on your choice
```

## Phase 1 update — 7 of 8 regenerated, E.M.B.E.R. in flight
All 7 verified sci-fi (I.N.K. spot-check passed). E.M.B.E.R. landing in ~3 min.

## Decision points for you

1. **F.O.R.G.E. vs P.R.O.B.E.** — director of Engineering & Technology = ?
2. **News & Media director** — keep F.A.C.T., or remove director flag entirely (and allow the dept to have no director in the UI)?
3. **Then go** — I apply migration 340 and all three surfaces realign in one shot.
