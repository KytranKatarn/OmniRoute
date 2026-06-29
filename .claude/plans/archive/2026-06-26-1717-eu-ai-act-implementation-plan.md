# EU AI Act Compliance Pack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 4 open-source EU AI Act JSON rule packs (risk-classification, high-risk-requirements, GPAI, transparency) + README + a validation test, in the existing compliance-rule-pack format extended for governance attestation.

**Architecture:** Pure data artifacts in an isolated `rule_packs/eu_ai_act/` subdir (so the host-security scanner never executes governance attestations) + a pytest validation suite that enforces schema, unique rule IDs, and manifest-vs-disk consistency. No runtime/UI code.

**Tech Stack:** JSON, Python 3.12, pytest. Runs in the `archie_platform` container (`platform_v2` is volume-mounted → `/app`).

**Spec:** `.claude/plans/2026-06-26-1717-eu-ai-act-compliance-pack-design.md`

## Global Constraints

- **Branch:** `feat/1717-eu-ai-act-rule-packs` — feature branch, PR, never push to main. End commit messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Pack dir:** `platform_v2/tools/security_network/rule_packs/eu_ai_act/` (NEW subdir — must not contain host-scan `check.type` values).
- **Test dir:** `platform_v2/tests/test_eu_ai_act_packs.py`.
- **Test run command (canonical):** `docker exec archie_platform python3 -m pytest /app/tests/test_eu_ai_act_packs.py -v`
- **Pack field contract:** `pack_id`, `name`, `description`, `version`="1.0", `framework`="EU AI Act (Regulation (EU) 2024/1689)", `category`="ai_governance", `effective_date`="2026-08-02", `rules[]`.
- **Rule JSON template (render every inventory row into THIS exact shape):**
  ```json
  {
    "rule_id": "EUAIA-XX-NN",
    "severity": "high|medium|low",
    "title": "<title>",
    "description": "<one-sentence paraphrase of the obligation — informational, never legal advice>",
    "applies_to": ["provider|deployer|gpai_provider|all"],
    "eu_ai_act_ref": "<Article/Annex cite>",
    "check": {
      "type": "attestation",
      "question": "<yes/no/NA question>",
      "evidence_prompt": "<what evidence to link>",
      "default_status": "not_assessed"
    },
    "remediation": "<plain-language remediation guidance>",
    "nist_ai_rmf_mapping": ["<optional NIST AI RMF crosswalk>"]
  }
  ```
- **rule_id format:** `^EUAIA-[A-Z]+-\d{2}$`, globally unique across all 4 packs. Prefixes: `TR` (transparency), `RC` (risk-classification), `HR` (high-risk), `GPAI`.
- **Severity guide:** high = prohibited practices + core high-risk/GPAI obligations; medium = procedural/documentation/registration duties; low = limited-risk transparency + best-practice/determination items.
- **Legal disclaimer:** README + each pack `description` are informational only, NOT legal advice. Article references verbatim; obligations paraphrased.

---

### Task 1: Validation test harness + Transparency pack + README + manifest

**Files:**
- Create: `platform_v2/tests/test_eu_ai_act_packs.py`
- Create: `platform_v2/tools/security_network/rule_packs/eu_ai_act/eu-ai-act-transparency.json`
- Create: `platform_v2/tools/security_network/rule_packs/eu_ai_act/_manifest.json`
- Create: `platform_v2/tools/security_network/rule_packs/eu_ai_act/README.md`

**Interfaces:**
- Produces: the `eu_ai_act/` pack dir, the `_manifest.json` shape (`{"framework","version","packs":[{"file","pack_id","name"}]}`), and the validation suite that all later tasks rely on (no test changes needed in Tasks 2–3).

- [ ] **Step 1: Write the failing test** — `platform_v2/tests/test_eu_ai_act_packs.py`

```python
import glob
import json
import os
import re

import pytest

PACK_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "tools",
        "security_network",
        "rule_packs",
        "eu_ai_act",
    )
)

ALLOWED_SEVERITY = {"low", "medium", "high"}
ALLOWED_APPLIES = {"provider", "deployer", "gpai_provider", "all"}
RULE_ID_RE = re.compile(r"^EUAIA-[A-Z]+-\d{2}$")
PACK_FIELDS = (
    "pack_id", "name", "description", "version",
    "framework", "category", "effective_date", "rules",
)


def pack_files():
    return sorted(glob.glob(os.path.join(PACK_DIR, "eu-ai-act-*.json")))


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_pack_dir_has_packs():
    assert pack_files(), f"no packs found in {PACK_DIR}"


@pytest.mark.parametrize("path", pack_files())
def test_pack_well_formed(path):
    pack = load(path)
    for field in PACK_FIELDS:
        assert field in pack, f"{os.path.basename(path)} missing '{field}'"
    assert pack["category"] == "ai_governance"
    assert pack["framework"] == "EU AI Act (Regulation (EU) 2024/1689)"
    assert isinstance(pack["rules"], list) and pack["rules"]


@pytest.mark.parametrize("path", pack_files())
def test_rules_valid(path):
    for r in load(path)["rules"]:
        assert RULE_ID_RE.match(r["rule_id"]), f"bad rule_id {r.get('rule_id')}"
        assert r["severity"] in ALLOWED_SEVERITY
        assert r["title"] and r["description"] and r["remediation"]
        assert r["eu_ai_act_ref"]
        assert r["applies_to"] and set(r["applies_to"]) <= ALLOWED_APPLIES
        chk = r["check"]
        assert chk["type"] == "attestation"
        assert chk["question"]
        assert chk["default_status"] == "not_assessed"


def test_rule_ids_globally_unique():
    seen = {}
    for path in pack_files():
        for r in load(path)["rules"]:
            rid = r["rule_id"]
            assert rid not in seen, f"duplicate {rid} in {path} & {seen[rid]}"
            seen[rid] = path


def test_manifest_matches_disk():
    manifest = load(os.path.join(PACK_DIR, "_manifest.json"))
    listed = {p["file"] for p in manifest["packs"]}
    on_disk = {os.path.basename(p) for p in pack_files()}
    assert listed == on_disk, f"manifest drift: {listed} != {on_disk}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_eu_ai_act_packs.py -v`
Expected: FAIL / ERROR — `no packs found` (dir + packs do not exist yet).

- [ ] **Step 3: Create the dir and write `eu-ai-act-transparency.json`** (full worked example — all 5 Article 50 rules)

```json
{
  "pack_id": "eu-ai-act-transparency",
  "name": "EU AI Act — Transparency Obligations (Article 50)",
  "description": "Article 50 transparency duties for AI providers and deployers. Informational, not legal advice.",
  "version": "1.0",
  "framework": "EU AI Act (Regulation (EU) 2024/1689)",
  "category": "ai_governance",
  "effective_date": "2026-08-02",
  "rules": [
    {
      "rule_id": "EUAIA-TR-01",
      "severity": "high",
      "title": "Disclosure of AI interaction",
      "description": "Natural persons are informed when they interact with an AI system, unless it is obvious from the context.",
      "applies_to": ["provider"],
      "eu_ai_act_ref": "Article 50(1)",
      "check": {
        "type": "attestation",
        "question": "Are users clearly informed when they are interacting with an AI system (e.g., chatbot disclosure)?",
        "evidence_prompt": "Link to the UI disclosure, chatbot banner, or ToS clause.",
        "default_status": "not_assessed"
      },
      "remediation": "Add a clear, conspicuous notice that the user is interacting with AI at the start of the interaction.",
      "nist_ai_rmf_mapping": ["GOVERN 1.2", "MAP 5.1"]
    },
    {
      "rule_id": "EUAIA-TR-02",
      "severity": "high",
      "title": "Machine-readable marking of synthetic content",
      "description": "Outputs of AI systems that generate synthetic audio, image, video, or text are marked as artificially generated or manipulated in a machine-readable format.",
      "applies_to": ["provider"],
      "eu_ai_act_ref": "Article 50(2)",
      "check": {
        "type": "attestation",
        "question": "Is AI-generated synthetic audio/image/video/text marked in a machine-readable format (e.g., metadata, watermark) as artificially generated?",
        "evidence_prompt": "Link to the watermarking/metadata implementation or spec.",
        "default_status": "not_assessed"
      },
      "remediation": "Embed machine-readable provenance markers (e.g., C2PA, SynthID-style watermark) in all synthetic outputs.",
      "nist_ai_rmf_mapping": ["MEASURE 2.7"]
    },
    {
      "rule_id": "EUAIA-TR-03",
      "severity": "medium",
      "title": "Emotion recognition / biometric categorization notice",
      "description": "Persons exposed to an emotion-recognition or biometric-categorization system are informed of its operation.",
      "applies_to": ["deployer"],
      "eu_ai_act_ref": "Article 50(3)",
      "check": {
        "type": "attestation",
        "question": "Are individuals informed when they are subject to an emotion-recognition or biometric-categorization system?",
        "evidence_prompt": "Link to the notice shown to exposed persons.",
        "default_status": "not_assessed"
      },
      "remediation": "Provide a clear notice to exposed persons before any emotion-recognition or biometric-categorization processing.",
      "nist_ai_rmf_mapping": ["GOVERN 1.2"]
    },
    {
      "rule_id": "EUAIA-TR-04",
      "severity": "high",
      "title": "Deepfake disclosure",
      "description": "Content constituting a deepfake is disclosed as artificially generated or manipulated.",
      "applies_to": ["deployer"],
      "eu_ai_act_ref": "Article 50(4)",
      "check": {
        "type": "attestation",
        "question": "Is image/audio/video content that constitutes a deepfake disclosed as artificially generated or manipulated?",
        "evidence_prompt": "Link to the deepfake labelling shown to viewers.",
        "default_status": "not_assessed"
      },
      "remediation": "Label all deepfake content as artificially generated/manipulated in a way visible to the audience.",
      "nist_ai_rmf_mapping": ["MEASURE 2.7"]
    },
    {
      "rule_id": "EUAIA-TR-05",
      "severity": "medium",
      "title": "AI-generated public-interest text disclosure",
      "description": "AI-generated or manipulated text published to inform the public on matters of public interest is disclosed as AI-generated, absent human review and editorial responsibility.",
      "applies_to": ["deployer"],
      "eu_ai_act_ref": "Article 50(4)",
      "check": {
        "type": "attestation",
        "question": "Is AI-generated/manipulated text published on matters of public interest disclosed as AI-generated (where there is no human editorial review)?",
        "evidence_prompt": "Link to the AI-authorship disclosure / editorial policy.",
        "default_status": "not_assessed"
      },
      "remediation": "Disclose AI authorship on public-interest text unless a human holds editorial responsibility for the content.",
      "nist_ai_rmf_mapping": ["GOVERN 1.2"]
    }
  ]
}
```

- [ ] **Step 4: Write `_manifest.json`** (1 entry)

```json
{
  "framework": "EU AI Act (Regulation (EU) 2024/1689)",
  "version": "1.0",
  "packs": [
    {"file": "eu-ai-act-transparency.json", "pack_id": "eu-ai-act-transparency", "name": "EU AI Act — Transparency Obligations (Article 50)"}
  ]
}
```

- [ ] **Step 5: Write `README.md`**

```markdown
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
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_eu_ai_act_packs.py -v`
Expected: PASS (all tests green with 1 pack).

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tests/test_eu_ai_act_packs.py platform_v2/tools/security_network/rule_packs/eu_ai_act/
git commit -m "feat(compliance): EU AI Act transparency pack + validation harness (#1717)"
```

---

### Task 2: Risk-classification pack

**Files:**
- Create: `platform_v2/tools/security_network/rule_packs/eu_ai_act/eu-ai-act-risk-classification.json`
- Modify: `platform_v2/tools/security_network/rule_packs/eu_ai_act/_manifest.json`

**Interfaces:** Consumes the rule template + manifest shape from Task 1. Produces no new interfaces.

- [ ] **Step 1: Add the manifest entry first (red)** — append to `_manifest.json` `packs`:

```json
{"file": "eu-ai-act-risk-classification.json", "pack_id": "eu-ai-act-risk-classification", "name": "EU AI Act — Risk Classification"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_eu_ai_act_packs.py::test_manifest_matches_disk -v`
Expected: FAIL — manifest lists a file not on disk.

- [ ] **Step 3: Create `eu-ai-act-risk-classification.json`** — pack header per Global Constraints (`pack_id`="eu-ai-act-risk-classification", `name`="EU AI Act — Risk Classification"), `rules[]` = render each row below into the Global Constraints rule template. `evidence_prompt` = "Describe the system's purpose and link supporting analysis." `remediation` = for prohibited: "Do not place on the market or put into service — this practice is prohibited under Article 5."; for high-risk: "Treat as high-risk: comply with Chapter III (see the high-risk-requirements pack)."; for limited/minimal as noted.

| rule_id | applies_to | severity | eu_ai_act_ref | title | question |
|---|---|---|---|---|---|
| EUAIA-RC-01 | all | high | Article 5(1)(a) | Subliminal/manipulative techniques | Does the system deploy subliminal or purposefully manipulative/deceptive techniques that materially distort behavior and cause harm? |
| EUAIA-RC-02 | all | high | Article 5(1)(b) | Exploitation of vulnerabilities | Does the system exploit vulnerabilities due to age, disability, or social/economic situation to distort behavior and cause harm? |
| EUAIA-RC-03 | all | high | Article 5(1)(c) | Social scoring | Does the system evaluate or classify persons via social behavior leading to detrimental/unjustified treatment? |
| EUAIA-RC-04 | all | high | Article 5(1)(d) | Predictive policing by profiling | Does the system assess the risk of a person committing a crime based solely on profiling or personality traits? |
| EUAIA-RC-05 | all | high | Article 5(1)(e) | Untargeted facial-image scraping | Does the system create/expand facial-recognition databases via untargeted scraping of facial images? |
| EUAIA-RC-06 | all | high | Article 5(1)(f) | Emotion inference at work/school | Does the system infer emotions in the workplace or education settings (outside medical/safety)? |
| EUAIA-RC-07 | all | high | Article 5(1)(g) | Sensitive biometric categorization | Does the system categorize persons by biometric data to infer race, political opinions, religion, sexual orientation, etc.? |
| EUAIA-RC-08 | all | high | Article 5(1)(h) | Real-time remote biometric ID | Does the system perform real-time remote biometric identification in publicly accessible spaces for law enforcement (outside narrow exceptions)? |
| EUAIA-RC-09 | provider | high | Article 6(1) / Annex I | Safety component of regulated product | Is the AI a safety component of a product covered by Annex I Union harmonization law requiring third-party conformity assessment? |
| EUAIA-RC-10 | provider | high | Annex III §1 | Biometrics | Is the system used for biometric identification, categorization, or emotion recognition (non-prohibited)? |
| EUAIA-RC-11 | provider | high | Annex III §2 | Critical infrastructure | Is the system a safety component in the management/operation of critical digital infrastructure, road traffic, or utilities? |
| EUAIA-RC-12 | provider | high | Annex III §3 | Education & vocational training | Is the system used for admissions, evaluation of learning outcomes, or proctoring in education? |
| EUAIA-RC-13 | provider | high | Annex III §4 | Employment & worker management | Is the system used for recruitment, selection, promotion/termination, or task allocation/monitoring of workers? |
| EUAIA-RC-14 | provider | high | Annex III §5 | Access to essential services | Is the system used to evaluate eligibility for essential public benefits, creditworthiness, or insurance/emergency dispatch? |
| EUAIA-RC-15 | provider | high | Annex III §6 | Law enforcement | Is the system used by law enforcement for risk assessment, evidence evaluation, or profiling? |
| EUAIA-RC-16 | provider | high | Annex III §7 | Migration, asylum & border control | Is the system used for migration/asylum/border management (risk assessment, application examination)? |
| EUAIA-RC-17 | provider | high | Annex III §8 | Justice & democratic processes | Is the system used to assist judicial authorities or to influence elections/referenda? |
| EUAIA-RC-18 | all | low | Article 50 | Limited-risk transparency trigger | Does the system interact with people, generate synthetic content, or perform emotion/biometric categorization (→ see the transparency pack)? |
| EUAIA-RC-19 | all | low | Article 95 | Minimal-risk (voluntary) | If none of the above apply, is the system minimal-risk (voluntary codes of conduct only)? |

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_eu_ai_act_packs.py -v`
Expected: PASS (2 packs validated, manifest in sync, rule_ids unique).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/security_network/rule_packs/eu_ai_act/
git commit -m "feat(compliance): EU AI Act risk-classification pack (#1717)"
```

---

### Task 3: High-risk requirements pack

**Files:**
- Create: `platform_v2/tools/security_network/rule_packs/eu_ai_act/eu-ai-act-high-risk-requirements.json`
- Modify: `.../_manifest.json`

- [ ] **Step 1: Add manifest entry (red)**

```json
{"file": "eu-ai-act-high-risk-requirements.json", "pack_id": "eu-ai-act-high-risk-requirements", "name": "EU AI Act — High-Risk System Requirements"}
```

- [ ] **Step 2: Run `test_manifest_matches_disk` → expect FAIL** (file not on disk).

- [ ] **Step 3: Create `eu-ai-act-high-risk-requirements.json`** — header (`pack_id`="eu-ai-act-high-risk-requirements", `name`="EU AI Act — High-Risk System Requirements"); render each row into the rule template. `evidence_prompt` = "Link the relevant policy/record/technical document." `remediation` = "Implement and document the obligation under <eu_ai_act_ref> before placing the high-risk system on the market."

| rule_id | applies_to | severity | eu_ai_act_ref | title | question |
|---|---|---|---|---|---|
| EUAIA-HR-01 | provider | high | Article 9 | Risk-management system | Is there a continuous, iterative risk-management system across the AI lifecycle? |
| EUAIA-HR-02 | provider | high | Article 10 | Data & data governance | Are training/validation/testing datasets relevant, representative, and examined for bias? |
| EUAIA-HR-03 | provider | high | Article 11 | Technical documentation | Is Annex IV technical documentation drawn up and kept up to date? |
| EUAIA-HR-04 | provider | high | Article 12 | Record-keeping / logging | Does the system automatically record events (logs) over its lifetime for traceability? |
| EUAIA-HR-05 | provider | high | Article 13 | Transparency to deployers | Are clear instructions for use provided so deployers can interpret and use output correctly? |
| EUAIA-HR-06 | provider | high | Article 14 | Human oversight | Is the system designed for effective human oversight (including stop/override)? |
| EUAIA-HR-07 | provider | high | Article 15 | Accuracy, robustness & cybersecurity | Does the system meet appropriate accuracy, robustness, and cybersecurity levels? |
| EUAIA-HR-08 | provider | medium | Article 17 | Quality management system | Is a documented quality-management system in place? |
| EUAIA-HR-09 | provider | medium | Article 18 | Documentation retention | Is documentation retained for 10 years after the system is placed on the market? |
| EUAIA-HR-10 | provider | high | Article 43 | Conformity assessment | Has the system undergone the required conformity-assessment procedure? |
| EUAIA-HR-11 | provider | medium | Article 47 | EU declaration of conformity | Has an EU declaration of conformity been drawn up? |
| EUAIA-HR-12 | provider | medium | Article 48 | CE marking | Is the CE marking affixed (where applicable)? |
| EUAIA-HR-13 | provider | medium | Article 49 | EU-database registration | Is the high-risk system registered in the EU database before being placed on the market? |
| EUAIA-HR-14 | deployer | high | Article 26 | Deployer obligations | Does the deployer use the system per instructions, ensure human oversight, and monitor operation? |
| EUAIA-HR-15 | provider | high | Article 72 | Post-market monitoring | Is there a post-market monitoring system collecting and reviewing performance data? |
| EUAIA-HR-16 | provider | high | Article 73 | Serious-incident reporting | Are serious incidents reported to the relevant market-surveillance authority within the required timeframe? |

- [ ] **Step 4: Run the full suite → expect PASS** (3 packs).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/security_network/rule_packs/eu_ai_act/
git commit -m "feat(compliance): EU AI Act high-risk requirements pack (#1717)"
```

---

### Task 4: GPAI pack + completeness gate

**Files:**
- Create: `platform_v2/tools/security_network/rule_packs/eu_ai_act/eu-ai-act-gpai-obligations.json`
- Modify: `.../_manifest.json`
- Modify: `platform_v2/tests/test_eu_ai_act_packs.py` (add completeness check)

- [ ] **Step 1: Add manifest entry (red)**

```json
{"file": "eu-ai-act-gpai-obligations.json", "pack_id": "eu-ai-act-gpai-obligations", "name": "EU AI Act — GPAI Model Obligations"}
```

- [ ] **Step 2: Run `test_manifest_matches_disk` → expect FAIL.**

- [ ] **Step 3: Create `eu-ai-act-gpai-obligations.json`** — header (`pack_id`="eu-ai-act-gpai-obligations", `name`="EU AI Act — GPAI Model Obligations"); render each row into the rule template. `evidence_prompt` = "Link model documentation / policy / evaluation report." `remediation` = "Produce and maintain the artefact required under <eu_ai_act_ref>."

| rule_id | applies_to | severity | eu_ai_act_ref | title | question |
|---|---|---|---|---|---|
| EUAIA-GPAI-01 | gpai_provider | high | Article 53(1)(a) | Technical documentation | Is Annex XI technical documentation for the GPAI model drawn up and kept current? |
| EUAIA-GPAI-02 | gpai_provider | high | Article 53(1)(b) | Downstream-provider information | Is Annex XII information/documentation made available to downstream providers integrating the model? |
| EUAIA-GPAI-03 | gpai_provider | high | Article 53(1)(c) | Copyright policy | Is there a policy to comply with Union copyright law (including Art. 4(3) DSM opt-outs)? |
| EUAIA-GPAI-04 | gpai_provider | high | Article 53(1)(d) | Training-content summary | Is a sufficiently detailed public summary of training content published? |
| EUAIA-GPAI-05 | gpai_provider | medium | Article 54 | Authorized representative | Have non-EU providers appointed an EU authorized representative? |
| EUAIA-GPAI-06 | gpai_provider | high | Article 55(1)(a) | Model evaluation & adversarial testing | For systemic-risk models, is model evaluation incl. adversarial testing performed and documented? |
| EUAIA-GPAI-07 | gpai_provider | high | Article 55(1)(b) | Systemic-risk assessment & mitigation | Are systemic risks at Union level assessed and mitigated? |
| EUAIA-GPAI-08 | gpai_provider | high | Article 55(1)(c) | Serious-incident tracking | Are serious incidents tracked, documented, and reported to the AI Office without undue delay? |
| EUAIA-GPAI-09 | gpai_provider | high | Article 55(1)(d) | Cybersecurity protection | Is adequate cybersecurity protection for the model and its physical infrastructure ensured? |
| EUAIA-GPAI-10 | gpai_provider | low | Article 51 | Systemic-risk classification | Does the model have high-impact capabilities / exceed 10^25 FLOPs of training compute (→ systemic-risk obligations apply)? |

- [ ] **Step 4: Add the completeness gate to the test file** — append:

```python
def test_all_four_packs_present():
    expected = {
        "eu-ai-act-risk-classification",
        "eu-ai-act-high-risk-requirements",
        "eu-ai-act-gpai-obligations",
        "eu-ai-act-transparency",
    }
    found = {load(p)["pack_id"] for p in pack_files()}
    assert found == expected, f"missing/extra packs: {expected ^ found}"
```

- [ ] **Step 5: Run the full suite → expect PASS** (4 packs, completeness gate green).

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_eu_ai_act_packs.py -v`

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/security_network/rule_packs/eu_ai_act/ platform_v2/tests/test_eu_ai_act_packs.py
git commit -m "feat(compliance): EU AI Act GPAI pack + completeness gate (#1717)"
```

---

### Task 5: Ship — PR + Dev HQ close-out

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/1717-eu-ai-act-rule-packs
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base main --head feat/1717-eu-ai-act-rule-packs \
  --title "feat(compliance): EU AI Act compliance rule packs (#1717)" \
  --body "4 open-source EU AI Act JSON rule packs (risk-classification, high-risk requirements, GPAI, transparency) + validation test. Slice A of #1717. Spec: .claude/plans/2026-06-26-1717-eu-ai-act-compliance-pack-design.md. Out of scope: scanner/attestation UI, public badge, KSO copy (follow-ups)."
```

- [ ] **Step 3: F.O.R.G.E. review (canonical path, not the orphaning skill trigger)**

```bash
docker exec -w /app archie_platform python3 -c "from tools.repair_bay.services.pr_diff_analyzer import review_pr; import json; print(json.dumps(review_pr(<PR>), default=str)[:1500])"
```

- [ ] **Step 4: After merge — Dev HQ close-out**
- `mcp__archie__complete_task(1717, notes=...)`
- `mcp__archie__log_decision` — the `attestation` rule-pack schema extension (ADR).
- `mcp__archie__store_memory` (vault_note) — the open-source EU AI Act packs (searchable).
- File follow-up tasks: Option B (scanner/attestation UI), Option C (public badge), KSO copy + public-repo mirror.

---

## Self-Review

**1. Spec coverage:** Schema extension → Task 1 (template in Global Constraints + worked transparency JSON). 4 packs → Tasks 1–4 (full rule inventories, no gaps). README → Task 1 Step 5. `_manifest.json` → Tasks 1–4. Validation test → Task 1 + completeness gate Task 4. Placement (isolated subdir) → Global Constraints + all create paths. Out-of-scope follow-ups → Task 5 Step 4. ✅ every spec section maps to a task.

**2. Placeholder scan:** No TBD/TODO. Every rule has a concrete rule_id/severity/ref/title/question; `remediation` + `evidence_prompt` defaults are specified per pack. Test code is complete. ✅

**3. Type consistency:** `pack_files()`, `load()`, manifest shape `{packs:[{file,pack_id,name}]}`, rule_id regex `^EUAIA-[A-Z]+-\d{2}$`, prefixes TR/RC/HR/GPAI, severities low/medium/high, applies_to set — all consistent across tasks and the test. Manifest `file` keys match the create paths' basenames. ✅
