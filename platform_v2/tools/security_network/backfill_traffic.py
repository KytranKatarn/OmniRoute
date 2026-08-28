#!/usr/bin/env python3
"""
backfill_traffic.py — One-time import of historical ntopng host bandwidth data
into the network_traffic_stats table.

Usage:
    docker exec archie_platform python3 /app/tools/security_network/backfill_traffic.py

Strategy:
  1. Fetch all active hosts from ntopng (paginated, ifid=1).
  2. For each host, try to get hourly timeseries via get_host_traffic_history().
     - If timeseries data is available: store one row per time bucket.
     - If not (returns empty or unsupported): fall back to cumulative totals
       from get_host_details(), stored with current timestamp as the bucket.
  3. Upsert into network_traffic_stats with GREATEST() to avoid downgrading.
  4. Skip hosts with 0 bytes total.
"""

import os
import sys
import logging
from datetime import datetime, timezone

# Allow imports from the platform root (/app maps to platform_v2/ inside Docker)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.security_network.ntopng_service import NtopngService
from database import get_db_cursor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

IFID = 1
PER_PAGE = 100


def fetch_all_hosts(svc: NtopngService) -> list:
    """Paginate through all active hosts on ifid=1."""
    all_hosts = []
    page = 1
    while True:
        data = svc._get(
            "/lua/rest/v2/get/host/active.lua",
            {"ifid": IFID, "currentPage": page, "perPage": PER_PAGE},
        )
        rsp = data.get("rsp", {})

        # ntopng returns either {"data": [...], "currentPage": N} or a plain list
        if isinstance(rsp, dict) and "data" in rsp:
            hosts = rsp["data"]
        elif isinstance(rsp, list):
            hosts = rsp
        else:
            hosts = []

        all_hosts.extend(hosts)
        logger.info(f"  Page {page}: got {len(hosts)} hosts (total so far: {len(all_hosts)})")

        if len(hosts) < PER_PAGE:
            break
        page += 1
        if page > 50:  # safety cap: 5000 hosts max
            logger.warning("Hit page safety cap (50 pages). Stopping pagination.")
            break

    return all_hosts


def truncate_to_hour(ts: datetime) -> datetime:
    """Floor a datetime to the nearest hour."""
    return ts.replace(minute=0, second=0, microsecond=0)


def parse_timeseries(ts_data) -> list:
    """
    Parse ntopng timeseries response into list of (hour_bucket, bytes_in, bytes_out).

    ntopng /lua/rest/v2/get/host/ts.lua typically returns:
      {"rsp": {"series": [{"label":"bytes_rcvd","data":[...]}, {"label":"bytes_sent","data":[...]}],
               "start": <epoch>, "step": <seconds>}}
    or may return a flat list or dict depending on version.
    """
    results = []
    if not ts_data or not isinstance(ts_data, dict):
        return results

    start = ts_data.get("start") or ts_data.get("epoch_start")
    step = ts_data.get("step", 300)  # default 5-min RRD step
    series = ts_data.get("series", [])

    if not start or not series:
        return results

    # Build lookup by label
    label_map = {}
    for s in series:
        lbl = (s.get("label") or "").lower()
        label_map[lbl] = s.get("data", [])

    rcvd = label_map.get("bytes_rcvd") or label_map.get("rcvd") or []
    sent = label_map.get("bytes_sent") or label_map.get("sent") or []

    n = max(len(rcvd), len(sent))
    if n == 0:
        return results

    # Aggregate into hourly buckets
    hourly: dict[datetime, list] = {}
    for i in range(n):
        epoch = start + i * step
        dt = truncate_to_hour(datetime.fromtimestamp(epoch, tz=timezone.utc))
        b_in = rcvd[i] if i < len(rcvd) and rcvd[i] is not None else 0
        b_out = sent[i] if i < len(sent) and sent[i] is not None else 0
        if dt not in hourly:
            hourly[dt] = [0, 0]
        hourly[dt][0] += int(b_in)
        hourly[dt][1] += int(b_out)

    for bucket, (b_in, b_out) in sorted(hourly.items()):
        results.append((bucket, b_in, b_out))

    return results


def upsert_row(cur, ip: str, mac: str, bytes_in: int, bytes_out: int, hour_bucket: datetime):
    cur.execute(
        """
        INSERT INTO network_traffic_stats
            (device_ip, device_mac, bytes_in, bytes_out, protocol, hour_bucket)
        VALUES (%s, %s, %s, %s, 'all', %s)
        ON CONFLICT (device_ip, hour_bucket)
        DO UPDATE SET
            bytes_in  = GREATEST(network_traffic_stats.bytes_in,  EXCLUDED.bytes_in),
            bytes_out = GREATEST(network_traffic_stats.bytes_out, EXCLUDED.bytes_out),
            device_mac = COALESCE(EXCLUDED.device_mac, network_traffic_stats.device_mac)
        """,
        (ip, mac or None, bytes_in, bytes_out, hour_bucket),
    )


def main():
    svc = NtopngService()

    if not svc.is_healthy():
        logger.error("ntopng is not reachable — aborting backfill.")
        sys.exit(1)

    logger.info("=== ntopng Traffic Backfill ===")
    logger.info(f"Connecting to ntopng at {svc.base_url}, ifid={IFID}")

    # ── 1. Fetch all hosts ──────────────────────────────────────────────────
    logger.info("Fetching all active hosts...")
    hosts = fetch_all_hosts(svc)
    logger.info(f"Total hosts found: {len(hosts)}")

    if not hosts:
        logger.warning("No hosts returned from ntopng. Nothing to backfill.")
        return

    # ── 2. Process each host ────────────────────────────────────────────────
    stats = {
        "hosts_processed": 0,
        "hosts_skipped_zero": 0,
        "hosts_timeseries": 0,
        "hosts_snapshot": 0,
        "rows_inserted": 0,
        "errors": 0,
    }

    now_bucket = truncate_to_hour(datetime.now(tz=timezone.utc))

    with get_db_cursor(commit=True) as (conn, cur):
        for host in hosts:
            ip = host.get("ip") or host.get("name", "")
            if not ip:
                continue

            mac = host.get("mac") or host.get("mac_address") or ""
            # Normalise MAC
            if mac and len(mac) < 17:
                mac = ""

            try:
                # ── 2a. Try timeseries first ────────────────────────────────
                ts_raw = svc._get(
                    "/lua/rest/v2/get/host/ts.lua",
                    {"ifid": IFID, "host": ip},
                )
                ts_rsp = ts_raw.get("rsp", {})
                buckets = parse_timeseries(ts_rsp)

                if buckets:
                    # Filter out zero rows
                    non_zero = [(b, bi, bo) for (b, bi, bo) in buckets if bi > 0 or bo > 0]
                    if not non_zero:
                        stats["hosts_skipped_zero"] += 1
                        continue

                    for bucket, b_in, b_out in non_zero:
                        upsert_row(cur, ip, mac, b_in, b_out, bucket)
                        stats["rows_inserted"] += 1

                    stats["hosts_timeseries"] += 1
                    logger.info(
                        f"  {ip}: timeseries → {len(non_zero)} hourly rows"
                        f" ({non_zero[0][0].date()} → {non_zero[-1][0].date()})"
                    )

                else:
                    # ── 2b. Fall back to cumulative snapshot ────────────────
                    details = svc.get_host_details(ip, ifid=IFID)

                    # ntopng stores bytes_rcvd/bytes_sent at host level
                    b_in = int(details.get("bytes_rcvd") or details.get("rcvd", {}).get("bytes", 0) or 0)
                    b_out = int(details.get("bytes_sent") or details.get("sent", {}).get("bytes", 0) or 0)

                    # Also try top-level bytes field
                    if b_in == 0 and b_out == 0:
                        total = int(details.get("bytes", 0) or 0)
                        b_in = total // 2
                        b_out = total - b_in

                    if b_in == 0 and b_out == 0:
                        stats["hosts_skipped_zero"] += 1
                        continue

                    # Try to get MAC from host details if not already set
                    if not mac:
                        mac = details.get("mac") or details.get("mac_address") or ""
                        if mac and len(mac) < 17:
                            mac = ""

                    upsert_row(cur, ip, mac, b_in, b_out, now_bucket)
                    stats["rows_inserted"] += 1
                    stats["hosts_snapshot"] += 1
                    logger.info(f"  {ip}: snapshot → {b_in:,} in / {b_out:,} out bytes")

                stats["hosts_processed"] += 1

            except Exception as e:
                logger.error(f"  {ip}: ERROR — {e}")
                stats["errors"] += 1
                continue

    # ── 3. Summary ──────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=== Backfill Complete ===")
    logger.info(f"  Hosts processed:      {stats['hosts_processed']}")
    logger.info(f"  Hosts (timeseries):   {stats['hosts_timeseries']}")
    logger.info(f"  Hosts (snapshot):     {stats['hosts_snapshot']}")
    logger.info(f"  Hosts skipped (0B):   {stats['hosts_skipped_zero']}")
    logger.info(f"  Rows upserted:        {stats['rows_inserted']}")
    logger.info(f"  Errors:               {stats['errors']}")
    logger.info("")
    logger.info("Verify with:")
    logger.info(
        '  docker exec archie_database psql -U archie -d archie -c "'
        "SELECT COUNT(*) as rows, COUNT(DISTINCT device_ip) as devices, "
        "MIN(hour_bucket) as oldest, MAX(hour_bucket) as newest, "
        "pg_size_pretty(SUM(bytes_in + bytes_out)) as total_traffic "
        'FROM network_traffic_stats;"'
    )


if __name__ == "__main__":
    main()
