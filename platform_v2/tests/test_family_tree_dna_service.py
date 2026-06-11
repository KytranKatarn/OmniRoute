"""Tests for Family Tree DNA parsing and ethnicity validation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from tools.family_tree.services.dna_service import estimate_ethnicity, parse_dna_file


def test_parse_23andme_normalizes_valid_genotype():
    parsed = parse_dna_file(
        "\n".join(
            [
                "# comment",
                "rsid\tchromosome\tposition\tgenotype",
                "rs1426654\t15\t48426484\taa",
            ]
        ),
        "23andme",
    )

    assert parsed["snp_count"] == 1
    assert parsed["snps"]["rs1426654"] == {
        "chr": "15",
        "pos": 48426484,
        "genotype": "AA",
    }


def test_parse_ancestrydna_builds_genotype_from_two_alleles():
    parsed = parse_dna_file("rs1426654\t15\t48426484\tA\tG", "ancestrydna")

    assert parsed["snp_count"] == 1
    assert parsed["snps"]["rs1426654"]["genotype"] == "AG"


def test_parse_rejects_invalid_allele_with_line_number():
    with pytest.raises(ValueError, match="Line 1: invalid genotype for SNP rs1426654"):
        parse_dna_file("rs1426654\t15\t48426484\tAX", "23andme")


def test_parse_rejects_malformed_data_row():
    with pytest.raises(ValueError, match="Line 1: expected 4 tab-separated columns"):
        parse_dna_file("rs1426654\t15\t48426484", "23andme")


def test_parse_rejects_invalid_position():
    with pytest.raises(ValueError, match="Line 1: invalid position 'not-a-number'"):
        parse_dna_file("rs1426654\t15\tnot-a-number\tAA", "23andme")


def test_estimate_ethnicity_rejects_empty_snps():
    with pytest.raises(ValueError, match="SNP data is empty"):
        estimate_ethnicity({"snps": {}, "snp_count": 0})


def test_estimate_ethnicity_rejects_invalid_stored_genotype():
    with pytest.raises(ValueError, match="invalid genotype for SNP rs1426654"):
        estimate_ethnicity({"snps": {"rs1426654": {"genotype": "AN"}}})
