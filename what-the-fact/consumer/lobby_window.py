"""The /lobbying "Last 30 days" tile: a real zero versus data that simply does not reach the window.

Pure and stdlib-only. The registry's monthly communication reports arrive with a lag, so the newest filing can be weeks old. Counting filings dated
in the last 30 days then yields 0, and "0" reads as "nobody lobbied this month" when the truth is "the feed has nothing for this month yet".
"""

from datetime import date

WINDOW_DAYS = 30


def last_30d_tile(last_30d, last_seen, today: date) -> dict:
    """{'value': int | '—', 'detail': str | None}.

    * filings in the window            -> that count, no caveat
    * none, and the data reaches today -> a genuine 0
    * none, and the newest filing is older than the window, or there are no filings at all -> '—' and the date the data actually runs to
    """
    if last_30d:
        return {"value": int(last_30d), "detail": None}
    if last_seen is None:
        return {"value": "—", "detail": "no filings on record"}
    if (today - last_seen).days > WINDOW_DAYS:
        return {"value": "—", "detail": f"registry data ends {last_seen.isoformat()}"}
    return {"value": 0, "detail": None}
