"""Local-time day bucketing for the forecast-accuracy queries (task 7226).

A "day" for a forecast check is the CITY's local day. Grouping by the UTC date puts a western city's warm evening into the NEXT UTC date
(Winnipeg, five hours behind: the evening of 10 Oct becomes part of 11 Oct), so a forecast of 9C for "today" was scored against 18C and showed up
as the worst call of the month. Measured on Winnipeg same-day (119 pairs): average miss 1.45 (old) vs 1.30 (local), worst miss 9.1 vs 5.7.

Pure and stdlib-only, like aurora_verify. The 13 codes are exactly the source_prov values of wtf.aurora_city_site (checked 2026-10-14). A site whose
province is missing or unknown falls back to the old behaviour (zone "UTC"), never a guess.
"""

from datetime import timezone

# One IANA zone per province/territory, chosen for the cities actually in the 25-site set:
#   SK  Regina and Saskatoon stay on CST all year, so America/Regina, not Winnipeg.
#   YT  Whitehorse is permanently on MST since 2020.
#   NT  Yellowknife is Mountain with DST (America/Edmonton rules).
#   NU  Iqaluit is Eastern with DST.
#   QC  Montreal and Quebec City are Eastern (the Atlantic-time east of the province has no site here).
PROV_TZ = {
    "BC": "America/Vancouver",
    "AB": "America/Edmonton",
    "SK": "America/Regina",
    "MB": "America/Winnipeg",
    "ON": "America/Toronto",
    "QC": "America/Toronto",
    "NB": "America/Moncton",
    "NS": "America/Halifax",
    "PE": "America/Halifax",
    "NL": "America/St_Johns",
    "YT": "America/Whitehorse",
    "NT": "America/Edmonton",
    "NU": "America/Iqaluit",
}
DEFAULT_TZ = timezone.utc.tzname(None)  # the old behaviour; a zone NAME for the database, never a label shown to anyone


def site_tz_cte(schema):
    """SQL for a `site_tz(site_code, tz)` CTE. Built only from the constants above (never user input).

    Use as `WITH <site_tz_cte(S)>, other AS (...)` and `LEFT JOIN site_tz st ON st.site_code = ...`, then
    `AT TIME ZONE COALESCE(st.tz, 'UTC')`: a site absent from aurora_city_site keeps the old behaviour instead of vanishing.
    """
    values = ", ".join(f"('{p}', '{tz}')" for p, tz in sorted(PROV_TZ.items()))
    return (
        f"site_tz AS (SELECT s.site_code, COALESCE(m.tz, '{DEFAULT_TZ}') AS tz "
        f"FROM {schema}.aurora_city_site s "
        f"LEFT JOIN (VALUES {values}) AS m(prov, tz) ON m.prov = upper(trim(s.source_prov)))"
    )
