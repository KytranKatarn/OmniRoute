# EU AI Act Compliance Pack — Design Spec (Task #1717, slice A)

**Date:** 2026-06-26
**Task:** #1717 (project #234 "Competitive Feature Gaps")
**Status:** Approved design — ready for implementation plan
**Scope decision:** Slice A — author the open-source JSON rule packs only. Scanner/attestation UI, public badge, KSO copy, and `platform_signal` auto-mapping are explicit follow-ups.

---

## 1. Motivation

The EU AI Act (Regulation (EU) 2024/1689) has its majority provisions applying **2 August 2026**. Commercial tools (Credo AI, Holistic AI) charge **$50K+/yr** to encode these obligations as auditable checklists. #1717 ships the equivalent as **open-source JSON rule packs** that map to A.R.C.H.I.E.'s existing compliance-rule-pack pattern.

Grounding: KB vault_note **#268968** (C.R.E.E.D. AI Ethics Landscape) already documents the Act's risk pyramid (prohibited / high / limited / minimal), Article 50 (transparency/deepfake disclosure), and Article 73 (serious-incident reporting).

## 2. Goal & Non-Goals

**Goal:** Produce 4 well-formed, validated, open-source JSON rule packs encoding the EU AI Act, reusing and extending the existing rule-pack schema, plus a README and a validation test.

**Non-goals (this slice):**
- No interactive scanner / attestation-answering UI (Option B follow-up).
- No public "EU AI Act readiness" SVG badge / page (Option C follow-up).
- No KSO standalone copy.
- No `platform_signal` auto-mapping (e.g., wiring the transparency article to the live C.R.E.E.D. score).
- No mirroring to the public `archie-code` repo (follow-up — the "open-source distribution" of these artifacts).

## 3. Key design constraint — governance ≠ host-scan

The existing 5 rule packs (Ubuntu STIG, Docker STIG, HIPAA, Network STIG, CIS Ubuntu) are **host-security scans**: each rule's `check` runs a real command (`awk /etc/passwd`, read `sshd_config`) and auto-passes/fails. EU AI Act obligations are **governance/attestation** questions ("Is there a risk-management system?", "Is training data documented?", "Is AI-generated content disclosed?") — no shell command answers them.

Therefore we **reuse the schema shape** but add a new `check.type: "attestation"` (human yes/no/NA + evidence), and replace the shell `fix` with a `remediation` guidance string. The host-security scanner does NOT execute these packs (it globs scan-output dirs, not `rule_packs/`; packs are run by pack_id via host_monitor/KSO), and we further isolate the new packs in a dedicated subdir so nothing auto-runs a governance attestation as a shell command.

## 4. Schema (extended rule-pack format)

```json
{
  "pack_id": "eu-ai-act-transparency",
  "name": "EU AI Act — Transparency Obligations (Article 50)",
  "description": "Article 50 transparency duties for AI providers and deployers.",
  "version": "1.0",
  "framework": "EU AI Act (Regulation (EU) 2024/1689)",
  "category": "ai_governance",
  "effective_date": "2026-08-02",
  "rules": [
    {
      "rule_id": "EUAIA-TR-01",
      "severity": "high",
      "title": "Disclosure of AI interaction",
      "description": "Natural persons interacting with an AI system are informed they are interacting with AI, unless obvious from context.",
      "applies_to": ["provider"],
      "eu_ai_act_ref": "Article 50(1)",
      "check": {
        "type": "attestation",
        "question": "Are users informed when they are interacting with an AI system (e.g., chatbot disclosure)?",
        "evidence_prompt": "Link to the UI disclosure / chatbot banner / ToS clause.",
        "default_status": "not_assessed"
      },
      "remediation": "Add a clear, conspicuous notice that the user is interacting with AI at the start of the interaction.",
      "nist_ai_rmf_mapping": ["GOVERN 1.2", "MAP 5.1"]
    }
  ]
}
```

Field contract:
- **Pack:** `pack_id` (kebab), `name`, `description`, `version`, `framework` (constant), `category` = `"ai_governance"`, `effective_date`, `rules[]`.
- **Rule:** `rule_id` (`EUAIA-<PACK>-NN`, unique across all packs), `severity` ∈ {low, medium, high} (assignment guide: **high** = prohibited practices + core high-risk/GPAI obligations; **medium** = procedural/documentation/registration duties; **low** = limited-risk transparency + best-practice items), `title`, `description`, `applies_to` ⊆ {provider, deployer, gpai_provider, all}, `eu_ai_act_ref` (article/annex string), `check` (`{type:"attestation", question, evidence_prompt, default_status:"not_assessed"}`), `remediation` (string), `nist_ai_rmf_mapping` (array, optional crosswalk).
- Back-compat: the shape is a superset of the existing packs (same `pack_id`/`name`/`rules`/`rule_id`/`severity`/`title`/`description`), so a future scanner that understands `check.type` can consume both.

## 5. The 4 packs (rule coverage)

### `eu-ai-act-risk-classification.json` — classify your system
Rules that walk a provider through the risk pyramid:
- **Prohibited (Art. 5):** subliminal/manipulative techniques; exploitation of vulnerabilities; social scoring; untargeted facial-image scraping; emotion recognition in workplace/education; biometric categorization of sensitive traits; real-time remote biometric ID in public spaces; predictive policing by profiling.
- **High-risk (Art. 6 + Annex III):** biometrics; critical infrastructure; education; employment/worker management; access to essential services (incl. credit scoring, benefits); law enforcement; migration/border; justice & democratic processes. + Annex I safety components.
- **Limited / transparency (Art. 50):** pointer to the transparency pack.
- **Minimal:** residual (voluntary codes).

### `eu-ai-act-high-risk-requirements.json` — obligations IF high-risk
- Art. 9 risk-management system · Art. 10 data governance · Art. 11 technical documentation (Annex IV) · Art. 12 record-keeping/logging · Art. 13 transparency to deployers (instructions for use) · Art. 14 human oversight · Art. 15 accuracy/robustness/cybersecurity.
- Provider/deployer duties: Art. 17 QMS · Art. 18 documentation retention · Art. 43 conformity assessment · Art. 47 EU declaration of conformity · Art. 48 CE marking · Art. 49 EU-database registration · Art. 26 deployer obligations · Art. 72 post-market monitoring · Art. 73 serious-incident reporting.

### `eu-ai-act-gpai-obligations.json` — general-purpose AI models (Ch. V)
- Art. 53 (all GPAI): technical documentation (Annex XI); information to downstream providers (Annex XII); copyright policy; public summary of training content.
- Art. 54: authorized representative (non-EU providers).
- Art. 55 (systemic-risk GPAI, ≥10^25 FLOPs / Art. 51): model evaluation & adversarial testing; systemic-risk assessment & mitigation; serious-incident tracking & reporting; cybersecurity protection.

### `eu-ai-act-transparency.json` — Article 50
- 50(1) AI-interaction disclosure · 50(2) machine-readable marking of synthetic audio/image/video/text · 50(3) emotion-recognition & biometric-categorization notice · 50(4) deepfake disclosure + AI-generated public-interest text disclosure.

## 6. File manifest

```
platform_v2/tools/security_network/rule_packs/eu_ai_act/
├── _manifest.json                          # lists the 4 packs (machine-discoverable, isolated from host glob)
├── README.md                               # schema doc + open-source intent + "how to use"
├── eu-ai-act-risk-classification.json
├── eu-ai-act-high-risk-requirements.json
├── eu-ai-act-gpai-obligations.json
└── eu-ai-act-transparency.json
platform_v2/tests/test_eu_ai_act_packs.py   # validation test
```

## 7. Testing (how we test a data-only deliverable)

`test_eu_ai_act_packs.py` (pytest) asserts, for every pack in `eu_ai_act/`:
1. Valid JSON; required pack fields present; `category == "ai_governance"`.
2. `rule_id` unique across ALL four packs; matches `^EUAIA-[A-Z]+-\d{2}$`.
3. Every rule has: `severity` ∈ {low,medium,high}; non-empty `title`/`description`/`remediation`; `eu_ai_act_ref` non-empty; `applies_to` ⊆ allowed set; `check.type == "attestation"` with `question` + `default_status == "not_assessed"`.
4. `_manifest.json` lists exactly the 4 pack files present on disk (no drift).

## 8. Risks & mitigations
- **Legal accuracy:** article references must be correct. Mitigation: cite article numbers verbatim; `description` paraphrases, never asserts legal advice; README disclaimer ("informational, not legal advice"). Grounded in KB #268968 + the Regulation's article structure.
- **Breaking host scans:** mitigated by the isolated subdir + new `check.type` the host scanner never executes.
- **Schema drift vs existing packs:** superset design keeps back-compat; `_manifest.json` + test prevent intra-pack drift.

## 9. Out-of-scope follow-up tasks (file after slice A merges)
1. Option B — attestation/self-assessment runner + UI (Security Network or C.R.E.E.D.) writing to `compliance_scan_results`, readiness %.
2. Option C — public "EU AI Act readiness" SVG badge + page.
3. `platform_signal` mappings (transparency → live C.R.E.E.D. score, logging → record-keeping).
4. KSO standalone copy + public `archie-code` mirror (true open-source distribution).
