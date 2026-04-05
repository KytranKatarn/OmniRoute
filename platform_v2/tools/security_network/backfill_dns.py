"""
One-time backfill script: imports historical DNS query data from AdGuard's
query log into the device_dns_history table.

Usage (inside archie_platform container):
    python3 /app/tools/security_network/backfill_dns.py

Or from host:
    docker exec archie_platform python3 /app/tools/security_network/backfill_dns.py
"""

import json
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime

# Ensure /app is on sys.path when run as a script
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from database import get_db_cursor


def _parse_hour_bucket(timestamp_str):
    """Parse ISO 8601 timestamp (with nanoseconds) and truncate to hour."""
    # AdGuard uses nanosecond precision: 2026-02-18T19:37:21.846782395Z
    # Python can only handle microseconds, so trim if needed
    ts = timestamp_str.rstrip("Z")
    # Trim sub-second beyond 6 digits (microseconds)
    if "." in ts:
        date_part, frac = ts.split(".", 1)
        frac = frac[:6]  # keep only microseconds
        ts = f"{date_part}.{frac}"
    dt = datetime.fromisoformat(ts)
    return dt.replace(minute=0, second=0, microsecond=0)


def _should_skip_ip(ip):
    """Skip Docker bridge and localhost IPs."""
    if not ip:
        return True
    return ip.startswith("172.") or ip.startswith("127.")


def _flush_buckets(buckets):
    """Write aggregated buckets to the database via batch upsert."""
    if not buckets:
        return 0

    rows = []
    for (ip, domain, hour_str), data in buckets.items():
        rows.append((ip, domain, data["count"], data["blocked"], hour_str))

    inserted = 0
    # Batch in chunks of 5000 for the execute
    chunk_size = 5000
    with get_db_cursor(commit=True) as (conn, cur):
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            # Use executemany-style with VALUES list for performance
            args_list = []
            placeholders = []
            for row in chunk:
                placeholders.append("(%s, %s, %s, %s, %s)")
                args_list.extend(row)

            sql = """
                INSERT INTO device_dns_history (device_ip, domain, query_count, blocked, hour_bucket)
                VALUES {}
                ON CONFLICT (device_ip, domain, hour_bucket)
                DO UPDATE SET
                    query_count = device_dns_history.query_count + EXCLUDED.query_count,
                    blocked = device_dns_history.blocked OR EXCLUDED.blocked
            """.format(
                ", ".join(placeholders)
            )
            cur.execute(sql, args_list)
            inserted += len(chunk)

    return inserted


def run_backfill():
    """Main backfill entry point."""
    print("=" * 60)
    print("DNS History Backfill — AdGuard Query Log Import")
    print("=" * 60)

    # Stream the query log from the AdGuard container
    print("\nStreaming query log from network_adguard container...")
    proc = subprocess.Popen(
        [
            "docker",
            "exec",
            "network_adguard",
            "cat",
            "/opt/adguardhome/work/data/querylog.json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1024 * 1024,
    )

    # Aggregation state
    buckets = defaultdict(lambda: {"count": 0, "blocked": False})
    total_entries = 0
    skipped_ip = 0
    skipped_missing = 0
    errors = 0
    flush_threshold = 500_000  # flush buckets every 500K entries

    start_time = time.time()

    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            errors += 1
            continue

        # Extract fields
        # CP is often empty; IP holds the actual client address
        timestamp_str = entry.get("T")
        domain = entry.get("QH")
        client_ip = entry.get("CP") or entry.get("IP")

        # Skip entries missing required fields
        if not timestamp_str or not domain or not client_ip:
            skipped_missing += 1
            continue

        # Skip Docker bridge and localhost
        if _should_skip_ip(client_ip):
            skipped_ip += 1
            total_entries += 1
            if total_entries % 500_000 == 0:
                print(f"Processing... {total_entries:,} entries " f"({len(buckets):,} unique buckets)")
            continue

        # Parse blocked status
        result = entry.get("Result", {})
        is_blocked = bool(result.get("IsFiltered", False))

        # Compute hour bucket
        try:
            hour_bucket = _parse_hour_bucket(timestamp_str)
        except (ValueError, TypeError):
            errors += 1
            continue

        hour_str = hour_bucket.strftime("%Y-%m-%d %H:%M:%S")

        # Aggregate
        key = (client_ip, domain, hour_str)
        buckets[key]["count"] += 1
        if is_blocked:
            buckets[key]["blocked"] = True

        total_entries += 1

        # Progress reporting
        if total_entries % 500_000 == 0:
            print(f"Processing... {total_entries:,} entries " f"({len(buckets):,} unique buckets)")

        # Flush to DB periodically to manage memory
        if total_entries % flush_threshold == 0 and len(buckets) > 100_000:
            print(f"  Flushing {len(buckets):,} buckets to database...")
            _flush_buckets(buckets)
            buckets.clear()

    # Wait for subprocess to finish
    proc.stdout.close()
    proc.wait()

    # Final flush
    if buckets:
        print(f"Final flush: {len(buckets):,} buckets to database...")
        _flush_buckets(buckets)

    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 60)
    print("BACKFILL COMPLETE")
    print("=" * 60)
    print(f"Total entries processed:  {total_entries:,}")
    print(f"Skipped (Docker/localhost): {skipped_ip:,}")
    print(f"Skipped (missing fields):   {skipped_missing:,}")
    print(f"Errors (malformed JSON):    {errors:,}")
    print(f"Time elapsed:               {elapsed:.1f}s")
    print(f"Rate:                        {total_entries / max(elapsed, 1):.0f} entries/s")
    print("=" * 60)


if __name__ == "__main__":
    run_backfill()
