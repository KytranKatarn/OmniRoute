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
    "pack_id",
    "name",
    "description",
    "version",
    "framework",
    "category",
    "effective_date",
    "rules",
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


def test_all_four_packs_present():
    expected = {
        "eu-ai-act-risk-classification",
        "eu-ai-act-high-risk-requirements",
        "eu-ai-act-gpai-obligations",
        "eu-ai-act-transparency",
    }
    found = {load(p)["pack_id"] for p in pack_files()}
    assert found == expected, f"missing/extra packs: {expected ^ found}"
