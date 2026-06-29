# #4470 — Legal Watch ethics entity build-up

**Status: ✅ BUILT + LIVE 2026-06-24 (cont-85), PR #12 (kytran-legal-watch), ADR-002 #841.**
Owner chose Option A (live 9 now + historical follow-up). L0 source rediscovered (CIEC →
"Ethics Canada" Public Registry, server-rendered — no S.C.O.U.T. needed). L1+L2 shipped:
`ingest/ethics.py` re-pointed to `/en/public-registry/cards` + `/Details`; 9 authoritative
full-name reports ingested live on Citadel; `entity_graph_adapter` prefers `subject_full_name`
→ persons slug-resolve to existing MP/minister nodes (NO LOP/Wikidata resolver needed — the
graph endpoint resolves server-side by slug). Verified: LeBlanc ethics_ruling + 172 cast_vote
+ 29 covered_by + 18 lobbied_by; Kusie ethics + 168 votes + 23 donations. KB #275738.
**Historical ~52 reports (Wayback) deferred → task #4474.** Section below = original plan.

---

# #4470 — Legal Watch ethics entity build-up (PLAN — investigated 2026-06-24, build next session)

**Status:** investigated end-to-end this session; NOT built. Owner chose "plan now, build next session with full context budget." Defamation-sensitive — deserves a clean run.

**Goal:** make the Cross-Watch Legal entity graph carry *proper, defamation-safe person entities* for Ethics Commissioner (CIEC) investigation subjects, so an ethics ruling links to that person's votes/donations/coverage. Today the subjects are surname-only or junk.

---

## KEY FINDING (changes the whole task): the CIEC source has MOVED
The handoff framed #4470 as "fix the scraper to capture full names." The real blocker is bigger:
- **All 61 stored `ethics_rulings.report_url` values now return HTTP 404.** The CIEC site (`ciec-ccie.parl.gc.ca`) was reorganized; the old scheme `/en/investigations-enquetes/Pages/<Name>Report.aspx` is gone.
- The old listing `_LIST_URL` (`.../Pages/InvestReport-RapportEnquete.aspx`) → **404**. Homepage `/en` → 200 but a plain-HTML scrape of its nav surfaced **no** investigation links → the investigations index is likely **JS-rendered** (or moved to a new section name, e.g. "examinations").
- ⟹ The ethics **ingest itself (`ingest/ethics.py`) is currently broken** (scrapes `_LIST_URL` + report pages, both 404). The 61 rows are stale (last successful ingest pre-migration).
- ⟹ Re-scraping authoritative full names at the **stored** URLs is impossible. The full name USED to be on the report page body ("the Honourable Lisa Raitt…") — authoritative — but those pages 404.

## Current data taxonomy (the 61 stale rows)
Subject derived from the URL slug by `_slug_to_subject()` (ingest/ethics.py:63) → surname or topic word; full name never captured.
1. **~45 surname-only persons** — Fox, Bloom, Ouimet, Fergus, Scott, Maloney, Wernick, Qualtrough, Miller, Verschuren, Ng, Peschisolido, Kusie, Kristmanson, Chapman, Morneau, Smolik, Wright, Gill, Toews, Bennett, Bonner, Glover, Kosick, Lynn, Raitt, Sullivan, Finley, Dykstra, Guergis, Watson, Clement, Flaherty, Carson, Philpott, Vennard, Hill, Vandenbeld… Need full names. Most are FORMER ministers/MPs (not in current `parliament.mps`).
2. **~7 slug-mangled numbered reports** — `TrudeauII`, `trudeau3Report`, `ParadisII`, `ParadisIII`, `Angus1Report`, `Angus2Report`, `Morneau2Report` → real persons (Trudeau/Paradis/Angus/Morneau) + a report ordinal. `report_name` is cleaner ("Trudeau III Report", "AngusReport I").
3. **~9 non-person / junk** — `WrongdoingFed`/`WrongdoingPOH`/`WrongdoingDM` ("Report on alleged wrongdoing by a [public office holder]" — subject UNnamed), `Cheques`×2 ("The Cheques Report"), `Dec2014Report`, `Discontinuance`, several "Referral from the Public Sector Integrity Commissioner" (PSIC referrals — may or may not name a person). **Must NOT become person entities.**
4. **Casing/format** — `ratansi` (lowercase → Ratansi), `Leblanc-Report` (→ LeBlanc).

(Last session already hardened `entity_graph_adapter._is_person_subject()` 57→44 + suppressed 13 junk nodes via `status='suppressed'`. Don't redo that.)

---

## The build — 3 layers

### Layer 0 (NEW, BLOCKING): re-discover the moved CIEC source
- **First: check for a STRUCTURED dataset before scraping.** Look at open.canada.ca (CIEC investigations open data?) and a CIEC `/sitemap.xml` / any JSON endpoint. Structured > scraping.
- If only HTML: find the current investigations/examinations index + report URL pattern. If the nav is JS-rendered, use the **S.C.O.U.T. browser fabric** (`archie_scraper` + Playwright pool; see `reference_scout-browser-intelligence` / KB #270262) — same playbook used when CanLII (DataDome) + the SCC site moved this session.
- Re-point `_LIST_URL` + `_slug_to_subject` (or replace slug-parsing with real listing metadata).

### Layer 1: capture FULL names (authoritative = defamation-safe)
- Extract the subject's full name from the (new) report page itself — CIEC names the person ("the Honourable [Full Name]", "Mr./Ms./Mrs./Hon. [Full Name]", report title). This is the SAFEST source: it's CIEC's own statement of who the subject is.
- Consistency check: full-name surname must match the report/slug surname.
- Schema: add `subject_full_name` (keep `subject_name` surname for back-compat) OR overwrite `subject_name`. Decide.
- Numbered reports → same person across reports (Trudeau II/III = Justin Trudeau; Paradis II/III = Christian Paradis; Angus I/II; Morneau I/II = Bill Morneau).

### Layer 2: conservative single-match resolver (graph linkage)
Link the ethics person → existing `wtf.shared.entities` person (the MP/minister) so the Cross-Watch footprint connects ethics → votes/donations/coverage.
- **Reference-source DECISION (open):**
  - **LOP / PARLINFO / ourcommons.ca** — authoritative for FEDERAL parliamentarians incl. **historical** (PARLINFO has all past MPs/senators). Best for the MP/minister majority. Canadian gov source.
  - **Wikidata** — broader: covers non-elected POHs (deputy ministers, GIC appointees, board chairs — e.g. Wernick, Kristmanson, Verschuren) who won't be in an MP list. SPARQL-queryable. Less authoritative; higher wrong-entity risk.
  - **Recommendation:** primary LOP/PARLINFO (most subjects) + Wikidata fallback for non-elected POHs.
- **DEFAMATION GATE (HARD):** single-match-ONLY — link only on exactly one confident match (surname + given name + era/role). Ambiguous → store the name but DO NOT link to a parliament entity. Never guess. Non-persons (Wrongdoing/Cheques/referrals) never become person entities.

---

## Files / surfaces
- `ingest/ethics.py` — scraper: re-point source (L0) + full-name extraction (L1). `_slug_to_subject` (L63) is the current surname-deriver.
- `ingest/entity_graph_adapter.py` — consumer: `_is_person_subject()` (last session, suppress non-persons) + person-entity creation/linkage (L2). POSTs to `wtf-ingest-api:8106/api/internal/entity-graph/ingest`.
- `wtf.shared.entities` (hub `wtf` DB, IMMUTABLE — retire via `status='suppressed'`, `entities_guard()` blocks DELETE) + `parliament.mps`.
- `ethics_rulings` table (SQLite, Citadel `kytran_legal_api:/app/data/legal.db`) — may need `subject_full_name` / `person_entity_id` column.

## Open decisions for next session
1. Reference source: **LOP/PARLINFO (rec)** vs Wikidata vs both.
2. L0 re-discovery: structured dataset (open.canada.ca / sitemap / JSON) FIRST; S.C.O.U.T. browser only if JS-walled.
3. Schema: add `subject_full_name` column vs overwrite `subject_name`.
4. Ethics ingest is also currently BROKEN (source moved) — fixing L0 also restores ongoing ethics ingest (bonus). Consider adding ethics to the daily ingest cron once the source is re-pointed (it's route-only today).

## Defamation principle (restate)
Authoritative names (CIEC page) OR single unambiguous reference match. Suppress non-persons. Ambiguous → name only, no link. This is public-accountability data about real people — wrong attribution is defamatory.

**Refs:** KB #275688 (this investigation), cont-83 plan `.claude/plans/2026-06-24-cross-watch-legal-market-buildup.md`, S.C.O.U.T. KB #270262, SCC-site-moved precedent (KB #275551).
