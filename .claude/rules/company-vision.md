# Kytran Empowerment — Company Vision & National Alignment

**Shared grounding for ALL AI workers — Codex, Claude, and A.R.C.H.I.E. agents alike.**
This is the canonical "who we are, what we're building, and why it matters nationally."
(Codex reads it via `AGENTS.md`; Claude via `CLAUDE.md`/memory; A.R.C.H.I.E. via the KB.)

---

## 1. What Kytran Empowerment is
**Kytran Empowerment Inc.** builds a **Canadian Civic Intelligence Platform** + a suite of
AI-powered consumer/business tools — all running on **A.R.C.H.I.E.**, a self-hosted,
ethical, **local-sovereign** AI cluster. Public sites: **www.kytranempowerment.com**
(product hub) and **www.creed-ai.org** (ethics/governance nonprofit).

## 2. A.R.C.H.I.E. — the spine
> **A.R.C.H.I.E. = the orchestration · collaboration · ethical · local-sovereign cluster network.**

- **Orchestration**: ~34 AI agents across 17 departments; the Department-HQ dispatcher routes
  every task to the right agent with welfare + cost + ethics gating (never direct model calls).
- **Collaboration**: humans + Claude + Codex + the local agents work the same backlog
  (Dev HQ projects/tasks, delegation, PR review).
- **Ethical**: C.R.E.E.D. governance + transparency scoring sit in the loop.
- **Local-sovereign**: inference runs **local-first** on Canadian-owned hardware (a hub GPU +
  a global Headscale mesh of nodes); cloud is escalation-only. Civic data stays on our infra,
  not a foreign cloud.

## 3. The Watch Series — Canadian Civic Intelligence (5 products)
Unified by a **Shared Entity Graph** that resolves the same people/orgs across all datasets,
tracing one **8-link accountability chain**:
**Money → MP → Vote → Policy → Contract → Market → Coverage → Public.**

| Product | Domain | Traces | Public dataset |
|---|---|---|---|
| **Gov Watch** | gov.kytranempowerment.com | Federal procurement, tenders, awards, GIC appointments | CanadaBuys / PSPC / TBS |
| **Civic Watch** | civic.kytranempowerment.com | Municipal/civic spending & transparency | Open civic data |
| **Legal Watch** | legal.kytranempowerment.com | Courts, rulings, regulatory | CanLII / Canada Gazette |
| **Market Watch** | market.kytranempowerment.com | Securities, filings, market reaction | SEDAR |
| **What The Fact** | what-the-fact.com / .tech | News bias scoring + fact-checking + coverage | 46 Canadian sources, RSS |

Parliament link: votes (Hansard) + donations (Elections Canada) feed the chain. None of these
datasets were connected before — the platform's job is to **connect them** for the public.

## 4. C.R.E.E.D. — ethics & how we support it (creed-ai.org)
**C.R.E.E.D.** is the governance/ethics layer + a **grant-target nonprofit**
(creed.kytranempowerment.com :8086 standalone + the public creed-ai.org site).
- Continuous **transparency scoring** of our own AI (public score + SVG badges + API).
- Public methodology / white papers; powers the governance widget on creed-ai.org + WTF.
- **How A.R.C.H.I.E. supports it**: E.T.H.O.S. (agent #336) runs CREED governance work —
  KPIs, weekly ethics briefs, grant drafting, mail triage. Every dispatch is welfare- and
  ethics-gated; scores auto-refresh from live compliance scans.

## 5. National alignment — "AI for All" (Carney, 2026-06-04)
Canada's national AI strategy targets **trust, opportunity, sovereignty** (+$200B growth,
250k jobs, adoption 12%→60% by 2034) and explicitly warns against "critical parts of our AI
ecosystem under foreign control." Kytran Empowerment is **purpose-built to this**:

| AI-for-All pillar | How we already embody it |
|---|---|
| **Sovereignty** | Local-first inference on Canadian-owned hardware; civic data never leaves our infra; cloud is escalation-only. The anti-"foreign control" answer, in production. |
| **Trust** | C.R.E.E.D. ethics governance + public transparency scoring; the Watch Series exists to make government/markets transparent to citizens (bias scoring, fact-check, accountability chain). |
| **Opportunity** | Canadian-built AI tooling (platform + Business Suite + Watch products) lowers the AI-adoption barrier for SMBs and citizens — the 12%→60% adoption goal, bottom-up. |

**Positioning line**: *Kytran Empowerment is sovereign, ethical, Canadian-built civic AI —
A.R.C.H.I.E. as the local cluster, the Watch Series as the public-accountability product,
C.R.E.E.D. as the trust layer — the AI-for-All vision running today, not in five years.*

---
*Source: ADR #608 / KB #267315 #268587 (platform vision); AI for All announcement
(pm.gc.ca, 2026-06-04, indexed `ai-for-all-canada-2026`). Keep this file in sync with
`AGENTS.md` §"Who we are" and `CLAUDE.md`.*
