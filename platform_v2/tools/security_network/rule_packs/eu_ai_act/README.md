# EU AI Act Compliance Rule Packs (open source)

Open-source JSON rule packs encoding the EU AI Act (Regulation (EU) 2024/1689),
whose majority provisions apply from **2 August 2026**. They reuse A.R.C.H.I.E.'s
compliance rule-pack format, extended with a governance `attestation` check type.

**These are informational and NOT legal advice.** Article references are verbatim;
obligations are paraphrased.

## Packs
- `eu-ai-act-risk-classification.json` — classify a system (prohibited / high / limited / minimal).
- `eu-ai-act-high-risk-requirements.json` — Chapter III obligations for high-risk systems.
- `eu-ai-act-gpai-obligations.json` — Chapter V obligations for general-purpose AI models.
- `eu-ai-act-transparency.json` — Article 50 transparency duties.

## Rule schema
Each rule: `rule_id` (`EUAIA-<PACK>-NN`), `severity`, `title`, `description`,
`applies_to` (provider/deployer/gpai_provider/all), `eu_ai_act_ref`,
`check` (`{type:"attestation", question, evidence_prompt, default_status}`),
`remediation`, optional `nist_ai_rmf_mapping`.

`check.type` is `attestation` (human yes/no/NA + evidence) — these are governance
obligations, not host-config scans, so they are NOT executed by the host-security scanner.
