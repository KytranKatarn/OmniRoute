from urllib.parse import urlparse

_GOV_SUFFIXES = (
    ".gc.ca",
    ".canada.ca",
    ".gouv.qc.ca",
    ".seao.ca",
    ".bcbid.gov.bc.ca",
    ".canlii.org",
    ".tpsgc-pwgsc.gc.ca",
)


def select_egress(target_url: str, requested_tier: int = None) -> int:
    if requested_tier is not None:
        return requested_tier
    try:
        domain = urlparse(target_url).netloc.lower()
    except Exception:
        return 1
    for suffix in _GOV_SUFFIXES:
        if domain.endswith(suffix) or domain == suffix.lstrip("."):
            return 1
    return 1  # safe default: hub residential
