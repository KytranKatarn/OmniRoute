"""Family Tree — DNA parsing, ethnicity estimation, and profile storage."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

import psycopg2

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ancestry-Informative Markers (AIMs)
# Each entry maps an rsid to population-specific alleles.
# Populations: EUR=European, AFR=Sub-Saharan African, EAS=East Asian,
#              SAS=South Asian, NAM=Native American
# weight = how informative this marker is (0-1)
# ---------------------------------------------------------------------------
ANCESTRY_MARKERS = [
    {"rsid": "rs1426654", "chr": "15", "pop": "EUR", "allele": "A", "weight": 1.0},
    {"rsid": "rs16891982", "chr": "5", "pop": "EUR", "allele": "G", "weight": 0.9},
    {"rsid": "rs2228479", "chr": "16", "pop": "EAS", "allele": "A", "weight": 0.8},
    {"rsid": "rs885479", "chr": "16", "pop": "EAS", "allele": "T", "weight": 0.8},
    {"rsid": "rs1800414", "chr": "15", "pop": "EAS", "allele": "T", "weight": 0.7},
    {"rsid": "rs3827760", "chr": "2", "pop": "EAS", "allele": "A", "weight": 0.9},
    {"rsid": "rs12913832", "chr": "15", "pop": "EUR", "allele": "G", "weight": 0.7},
    {"rsid": "rs1545397", "chr": "15", "pop": "AFR", "allele": "A", "weight": 0.8},
    {"rsid": "rs1834640", "chr": "15", "pop": "AFR", "allele": "A", "weight": 0.7},
    {"rsid": "rs10843104", "chr": "12", "pop": "AFR", "allele": "T", "weight": 0.6},
    {"rsid": "rs2814778", "chr": "1", "pop": "AFR", "allele": "C", "weight": 1.0},
    {"rsid": "rs3737576", "chr": "11", "pop": "SAS", "allele": "G", "weight": 0.7},
    {"rsid": "rs1800407", "chr": "15", "pop": "EUR", "allele": "T", "weight": 0.6},
    {"rsid": "rs12203592", "chr": "6", "pop": "EUR", "allele": "T", "weight": 0.6},
    {"rsid": "rs6548616", "chr": "3", "pop": "NAM", "allele": "T", "weight": 0.7},
    {"rsid": "rs3811801", "chr": "1", "pop": "SAS", "allele": "G", "weight": 0.65},
    {"rsid": "rs1042602", "chr": "11", "pop": "EUR", "allele": "A", "weight": 0.7},
    {"rsid": "rs4918664", "chr": "10", "pop": "NAM", "allele": "C", "weight": 0.6},
    {"rsid": "rs260690", "chr": "2", "pop": "AFR", "allele": "A", "weight": 0.65},
    {"rsid": "rs17822931", "chr": "16", "pop": "EAS", "allele": "T", "weight": 0.8},
]

POP_LABELS = {
    "EUR": "European",
    "AFR": "Sub-Saharan African",
    "EAS": "East Asian",
    "SAS": "South Asian",
    "NAM": "Native American",
}

VALID_ALLELES = set("ACGT")


class SnpRecord(TypedDict):
    chr: str
    pos: int
    genotype: str


class ParsedDnaData(TypedDict):
    snps: dict[str, SnpRecord]
    snp_count: int


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _validate_genotype(genotype: str, *, rsid: str, line_number: int | None = None) -> str:
    """Return a normalized genotype or raise for invalid allele data."""
    location = f"Line {line_number}: " if line_number is not None else ""
    normalized = genotype.upper().strip()
    if not normalized:
        raise ValueError(f"{location}missing genotype for SNP {rsid}.")
    if any(allele not in VALID_ALLELES for allele in normalized):
        raise ValueError(f"{location}invalid genotype for SNP {rsid}; " "alleles must contain only A, C, G, or T.")
    if len(normalized) > 2:
        raise ValueError(f"{location}genotype for SNP {rsid} must contain one or two alleles.")
    return normalized


def parse_dna_file(file_content: str, provider: str) -> ParsedDnaData:
    """Parse a raw DNA CSV/TSV file from 23andMe or AncestryDNA.

    Returns dict with keys: snps (dict rsid->{chr, pos, genotype}), snp_count (int).
    """
    if not isinstance(file_content, str):
        raise ValueError("DNA file content must be text.")
    if not isinstance(provider, str):
        raise ValueError("DNA provider must be a string.")

    provider = provider.lower().strip()
    if provider not in ("23andme", "ancestrydna"):
        raise ValueError(f"Unsupported provider: {provider}. Use '23andme' or 'ancestrydna'.")

    snps: dict[str, SnpRecord] = {}
    lines = file_content.splitlines()

    for line_number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split("\t")

        # Column header, skipped BEFORE any column-count or rsID check.
        #
        # Both later attempts to catch it were unreachable for a REAL export:
        #   * the skip inside `if len(parts) < 4:` only runs when the header has the WRONG
        #     number of columns — a genuine 23andMe header has exactly 4;
        #   * the skip inside `if not rsid.startswith("rs"):` never runs either, because
        #     "rsid".startswith("rs") is TRUE. It was dead code for the one value it names.
        #
        # So a well-formed header fell through to the data path and raised
        # "invalid position 'position' for SNP rsid" — i.e. parse_dna_file could not read an
        # actual 23andMe or AncestryDNA export, only one with a malformed header.
        if parts and parts[0].strip().lower() in ("rsid", "rs#", "snp"):
            continue

        if provider == "23andme":
            # Format: rsid  chromosome  position  genotype
            if len(parts) < 4:
                if parts and parts[0].strip().lower() in ("rsid", "rs#", "snp"):
                    continue
                raise ValueError(f"Line {line_number}: expected 4 tab-separated columns for 23andMe data.")
            rsid, chrom, pos, genotype = parts[0], parts[1], parts[2], parts[3]
        else:
            # AncestryDNA: rsid  chromosome  position  allele1  allele2
            if len(parts) < 5:
                if parts and parts[0].strip().lower() in ("rsid", "rs#", "snp"):
                    continue
                raise ValueError(f"Line {line_number}: expected 5 tab-separated columns for AncestryDNA data.")
            rsid, chrom, pos = parts[0], parts[1], parts[2]
            genotype = parts[3] + parts[4]

        # Skip non-rs identifiers and header rows
        if not rsid.startswith("rs"):
            if rsid.strip().lower() in ("rsid", "rs#", "snp"):
                continue
            raise ValueError(f"Line {line_number}: invalid SNP identifier '{rsid}'; expected an rsID.")

        try:
            pos_int = int(pos)
        except ValueError:
            raise ValueError(f"Line {line_number}: invalid position '{pos}' for SNP {rsid}.") from None

        genotype = _validate_genotype(genotype, rsid=rsid, line_number=line_number)

        snps[rsid] = {"chr": chrom, "pos": pos_int, "genotype": genotype}

    return {"snps": snps, "snp_count": len(snps)}


# ---------------------------------------------------------------------------
# Ethnicity estimation
# ---------------------------------------------------------------------------


def estimate_ethnicity(snp_data: dict[str, Any]) -> dict[str, Any]:
    """Estimate ethnicity from parsed SNP data using ancestry-informative markers.

    Returns dict like {"European": 0.65, "Sub-Saharan African": 0.10, ...}
    plus a disclaimer string.
    """
    if not isinstance(snp_data, dict):
        raise ValueError("SNP data must be a dictionary returned by parse_dna_file().")

    snps = snp_data.get("snps", {})
    if not isinstance(snps, dict):
        raise ValueError("SNP data must include a 'snps' dictionary.")
    if not snps:
        raise ValueError("SNP data is empty; cannot estimate ethnicity without parsed SNPs.")

    scores = {code: 0.0 for code in POP_LABELS}
    total_weight = 0.0

    for marker in ANCESTRY_MARKERS:
        rsid = marker["rsid"]
        if rsid not in snps:
            continue

        snp = snps[rsid]
        if not isinstance(snp, dict):
            raise ValueError(f"SNP {rsid} must be a dictionary with a genotype.")

        genotype = _validate_genotype(str(snp.get("genotype", "")), rsid=rsid)
        target_allele = marker["allele"].upper()
        pop = marker["pop"]
        weight = marker["weight"]

        # Count how many copies of the target allele (0, 1, or 2)
        match_count = genotype.count(target_allele)
        if match_count > 0:
            scores[pop] += weight * (match_count / 2.0)
            total_weight += weight * (match_count / 2.0)

    # Normalise to percentages
    estimates = {}
    if total_weight > 0:
        for code, label in POP_LABELS.items():
            estimates[label] = round(scores[code] / total_weight, 4)
    else:
        # No markers matched — return uniform
        even = round(1.0 / len(POP_LABELS), 4)
        for label in POP_LABELS.values():
            estimates[label] = even

    # Ensure they sum to 1.0
    total = sum(estimates.values())
    if total > 0 and abs(total - 1.0) > 0.001:
        for k in estimates:
            estimates[k] = round(estimates[k] / total, 4)

    return {
        "estimates": estimates,
        "markers_found": sum(1 for m in ANCESTRY_MARKERS if m["rsid"] in snps),
        "markers_total": len(ANCESTRY_MARKERS),
        "disclaimer": (
            "This is a simplified estimation using ~20 ancestry-informative markers. "
            "Real genetic ancestry services use hundreds of thousands of markers and "
            "sophisticated statistical models. These results are for educational and "
            "entertainment purposes only and should NOT be used for medical or legal decisions."
        ),
    }


# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------


def save_dna_profile(
    user_id: int,
    provider: str,
    snp_count: int,
    ethnicity_estimates: dict,
    upload_filename: str = None,
) -> int:
    """Store a DNA profile in the database. Returns the new profile id."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO family_dna_profiles
                (user_id, provider, snp_count, ethnicity_estimates, upload_filename)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id,
                provider,
                snp_count,
                psycopg2.Json(ethnicity_estimates),
                upload_filename,
            ),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_dna_profile(user_id: int) -> list:
    """Retrieve all DNA profiles for a user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, provider, snp_count, ethnicity_estimates,
                   upload_filename, uploaded_at
            FROM family_dna_profiles
            WHERE user_id = %s
            ORDER BY uploaded_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "provider": r[1],
                "snp_count": r[2],
                "ethnicity_estimates": r[3] or {},
                "upload_filename": r[4],
                "uploaded_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]


def delete_dna_profile(user_id: int, profile_id: int) -> bool:
    """Delete a DNA profile. Returns True if deleted, False if not found."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM family_dna_profiles WHERE id = %s AND user_id = %s",
            (profile_id, user_id),
        )
        return cur.rowcount > 0
