"""TMX listed-company sector source for the Entity-Graph company layer (Phase 1).

Loads the FREE monthly "TSX & TSXV Listed Companies" workbook
(https://www.tsx.com/en/resource/571) and yields sector-tagged OPERATING issuers.

Why this exists: SEDAR+ gives the authoritative issuer identity but NO sector
(Radware-walled, ToU-no-scrape; KB #275885/#275934). TMX publishes a per-issuer
`Sector` column for free — we crosswalk its 11 operating sectors to a NAICS
2-digit sector (the benchmark axis). NAICS source = 'tmx_derived' (confidence
< 1.0; it is a sector-level map, not the issuer's self-stated 6-digit code).
ADR-EG-001 amendment (decision #843); product attribution = 'market-watch'.

⚠️ TMX market-data ToU: use the classification as a DERIVED INPUT only; do not
republish TMX's raw classification or market-cap quotes verbatim. (License
sanity-check is an open governance item before any commercial display.)

Pure stdlib (zipfile + xml regex) — the runtime has no openpyxl.
"""

from __future__ import annotations

import io
import re
import urllib.request
import zipfile

TMX_URL = "https://www.tsx.com/en/resource/571"
PRODUCT = "market-watch"
NAICS_SOURCE = "tmx_derived"

# TMX classes that are NOT operating companies (funds / shells / instruments) —
# excluded from the benchmark universe.
NON_OPERATING = frozenset({
    "ETP",                # exchange-traded products / ETFs
    "CDR",                # Canadian Depositary Receipts
    "Closed-End Funds",
    "SPAC",
    "CPC",                # Capital Pool Companies (TSXV shells)
})

# The 11 TMX operating sectors -> NAICS 2-digit sector (matches shared.naics_codes
# `sector_code`). `confidence` reflects how cleanly the TMX sector maps to a single
# NAICS sector: 0.9 = 1:1, 0.8 = dominant-of-a-few, 0.75 = broad (we pick the
# dominant). All >= the 0.75 write threshold (ADR-EG-001). Tunable like a lookup.
TMX_SECTOR_TO_NAICS = {
    "Mining":                              ("21", 0.90),  # 21 spans mining + oil&gas
    "Oil & Gas":                           ("21", 0.90),  #   (2-digit merges the two)
    "Financial Services":                  ("52", 0.90),
    "Real Estate":                         ("53", 0.90),
    "Comm. & Media":                       ("51", 0.90),
    "Technology":                          ("51", 0.85),  # software publishers = 51
    "Life Sciences":                       ("54", 0.80),  # biotech R&D = 54 (pharma mfg = 31-33)
    "Utilities & Pipelines":               ("22", 0.80),  # utilities dominate (pipelines = 48-49)
    "Clean Technology & Renewable Energy": ("22", 0.75),  # heterogeneous; renewable power gen
    "Industrial Products & Services":      ("31-33", 0.80),
    "Consumer Products & Services":        ("31-33", 0.75),
}

# NAICS sector labels (from shared.naics_codes / NAICS Canada 2022) — for provenance.
_NAICS_LABEL = {
    "21": "Mining, quarrying, and oil and gas extraction",
    "22": "Utilities",
    "31-33": "Manufacturing",
    "51": "Information and cultural industries",
    "52": "Finance and insurance",
    "53": "Real estate and rental and leasing",
    "54": "Professional, scientific and technical services",
}


def is_operating(tmx_sector: str) -> bool:
    """True if the TMX sector is an operating-company sector (not a fund/shell)."""
    s = (tmx_sector or "").strip()
    return bool(s) and s not in NON_OPERATING and s in TMX_SECTOR_TO_NAICS


def naics_for_tmx_sector(tmx_sector: str):
    """Map a TMX sector -> {naics_sector, naics_label, naics_confidence} or None.

    Returns None for non-operating classes and unknown sectors (caller leaves the
    company's sector NULL rather than guessing — benchmarks disclose coverage).
    """
    s = (tmx_sector or "").strip()
    hit = TMX_SECTOR_TO_NAICS.get(s)
    if not hit:
        return None
    sector_code, confidence = hit
    return {
        "naics_sector": sector_code,
        "naics_label": _NAICS_LABEL.get(sector_code, ""),
        "naics_confidence": confidence,
    }


# ── stdlib .xlsx reader ───────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Collapse whitespace (TMX headers carry embedded \\r\\n) + lowercase."""
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _unescape(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&#10;", "\n").replace("&#13;", "").replace("&quot;", '"')
            .replace("&apos;", "'"))


def _shared_strings(z: zipfile.ZipFile) -> list:
    try:
        xml = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
    except KeyError:
        return []
    return [_unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S)))
            for si in re.findall(r"<si>(.*?)</si>", xml, re.S)]


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _parse_sheet(z: zipfile.ZipFile, sheet_path: str, shared: list) -> list:
    """Return the sheet as a list of {normalized_header: value} dicts."""
    sheet = z.read(sheet_path).decode("utf-8", "ignore")
    parsed = []
    for rx in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        row = {}
        for m in re.finditer(r'<c r="([A-Z]+\d+)"(?:[^>]*\bt="([^"]+)")?[^>]*>(.*?)</c>', rx, re.S):
            ref, typ, inner = m.group(1), m.group(2), m.group(3)
            vm = re.search(r"<v>(.*?)</v>", inner, re.S)
            if typ == "s" and vm:
                val = shared[int(vm.group(1))]
            elif typ == "inlineStr":
                val = _unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", inner, re.S)))
            elif vm:
                val = _unescape(vm.group(1))
            else:
                val = ""
            row[_col_index(ref)] = val
        parsed.append(row)
    # header row = the first containing both 'name' and 'sector'
    hi = None
    for i, r in enumerate(parsed):
        vals = {_norm(v) for v in r.values()}
        if "name" in vals and "sector" in vals:
            hi = i
            break
    if hi is None:
        return []
    header = {idx: _norm(v) for idx, v in parsed[hi].items() if v}
    out = []
    for r in parsed[hi + 1:]:
        out.append({header.get(idx, str(idx)): v for idx, v in r.items()})
    return out


def _pick(row: dict, *candidates):
    for c in candidates:
        for k, v in row.items():
            if k == c or k.startswith(c):
                return v
    return None


def parse_tmx_workbook(xlsx_bytes: bytes) -> list:
    """Parse the workbook -> list of sector-tagged OPERATING-company records.

    Each record: name, ticker, exchange, tmx_sector, tmx_sub_sector, market_cap,
    hq_location, naics_sector, naics_label, naics_confidence.
    Non-operating classes (ETF/CDR/funds/SPAC/CPC) and rows without a name are
    dropped; rows whose sector has no crosswalk are dropped (sector unknown).
    """
    z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    shared = _shared_strings(z)
    sheets = sorted(n for n in z.namelist()
                    if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    records = []
    for sp in sheets:
        for row in _parse_sheet(z, sp, shared):
            name = (_pick(row, "name") or "").strip()
            if not name:
                continue
            tmx_sector = (_pick(row, "sector") or "").strip()
            naics = naics_for_tmx_sector(tmx_sector)
            if naics is None:           # non-operating or unmapped -> skip
                continue
            records.append({
                "name": name,
                "ticker": (_pick(row, "root ticker", "ticker") or "").strip(),
                "exchange": (_pick(row, "exchange") or "").strip(),
                "tmx_sector": tmx_sector,
                "tmx_sub_sector": (_pick(row, "sub sector", "subsector") or "").strip(),
                "market_cap": (_pick(row, "market cap") or "").strip(),
                "hq_location": (_pick(row, "hq location") or "").strip(),
                **naics,
            })
    return records


def fetch_tmx_bytes(url: str = TMX_URL, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ArchieEntityGraph/1.0"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def load_tmx_companies(url: str = TMX_URL) -> list:
    """Fetch + parse -> sector-tagged operating-company records (the Slice-B output)."""
    return parse_tmx_workbook(fetch_tmx_bytes(url))


if __name__ == "__main__":  # manual integration probe (hits the live TMX file)
    import collections
    recs = load_tmx_companies()
    by_ex = collections.Counter(r["exchange"] or "?" for r in recs)
    by_sec = collections.Counter(r["naics_sector"] for r in recs)
    print(f"operating companies: {len(recs)}  by_exchange={dict(by_ex)}")
    print("by NAICS sector:", dict(by_sec.most_common()))
