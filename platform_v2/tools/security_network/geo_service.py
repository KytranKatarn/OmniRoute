"""geo_service.py — IP geolocation service with DB caching.

Uses free ip-api.com (45 req/min, no key needed) with local DB cache.
Batch endpoint: POST http://ip-api.com/batch (up to 100 IPs per request).
Cache lifetime: 30 days (IPs rarely change geo location).
"""

import ipaddress
import logging
import time

import requests

from database import get_db_cursor

logger = logging.getLogger("agent_loop")

GEO_API_SINGLE = "http://ip-api.com/json/{ip}?fields=status,country,countryCode,city,isp,org"
GEO_API_BATCH = "http://ip-api.com/batch"
CACHE_DAYS = 30


def _is_private_ip(ip: str) -> bool:
    """Return True if the IP is private, loopback, link-local, or otherwise non-routable."""
    try:
        return ipaddress.ip_address(ip).is_private
    except (ValueError, TypeError):
        return True


def get_cached(ip: str) -> dict | None:
    """Return cached geo data for an IP, or None if not cached / expired."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT country, country_code, city, isp, org
                FROM ip_geolocation_cache
                WHERE ip = %s
                  AND cached_at > NOW() - INTERVAL '%s days'
                """,
                (ip, CACHE_DAYS),
            )
            row = cur.fetchone()
            if row:
                return {
                    "country": row["country"],
                    "country_code": row["country_code"],
                    "city": row["city"],
                    "isp": row["isp"],
                    "org": row["org"],
                }
    except Exception as e:
        logger.debug("geo_service.get_cached(%s) error: %s", ip, e)
    return None


def cache_result(ip: str, data: dict) -> None:
    """Store geo lookup result in the DB cache."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO ip_geolocation_cache (ip, country, country_code, city, isp, org, cached_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (ip) DO UPDATE SET
                    country = EXCLUDED.country,
                    country_code = EXCLUDED.country_code,
                    city = EXCLUDED.city,
                    isp = EXCLUDED.isp,
                    org = EXCLUDED.org,
                    cached_at = NOW()
                """,
                (
                    ip,
                    data.get("country"),
                    data.get("country_code"),
                    data.get("city"),
                    data.get("isp"),
                    data.get("org"),
                ),
            )
    except Exception as e:
        logger.debug("geo_service.cache_result(%s) error: %s", ip, e)


def lookup_ip(ip: str) -> dict | None:
    """Look up a single IP — cache first, then API. Returns dict or None."""
    if _is_private_ip(ip):
        return None

    cached = get_cached(ip)
    if cached:
        return cached

    try:
        resp = requests.get(GEO_API_SINGLE.format(ip=ip), timeout=5)
        if resp.status_code == 200:
            payload = resp.json()
            if payload.get("status") == "success":
                result = {
                    "country": payload.get("country"),
                    "country_code": payload.get("countryCode"),
                    "city": payload.get("city"),
                    "isp": payload.get("isp"),
                    "org": payload.get("org"),
                }
                cache_result(ip, result)
                return result
    except Exception as e:
        logger.debug("geo_service.lookup_ip(%s) API error: %s", ip, e)
    return None


def batch_lookup(ips: list[str]) -> dict[str, dict]:
    """Look up multiple IPs via the ip-api.com batch endpoint (max 100 per call).

    Returns a dict mapping IP -> geo data for successful lookups.
    Private IPs and already-cached IPs are handled efficiently.
    """
    results: dict[str, dict] = {}

    # Filter out private IPs and check cache first
    to_fetch: list[str] = []
    for ip in ips:
        if _is_private_ip(ip):
            continue
        cached = get_cached(ip)
        if cached:
            results[ip] = cached
        else:
            to_fetch.append(ip)

    if not to_fetch:
        return results

    # ip-api.com batch: max 100 per request
    for i in range(0, len(to_fetch), 100):
        chunk = to_fetch[i : i + 100]
        try:
            payload = [{"query": ip, "fields": "status,country,countryCode,city,isp,org"} for ip in chunk]
            resp = requests.post(GEO_API_BATCH, json=payload, timeout=15)
            if resp.status_code == 200:
                for item in resp.json():
                    if item.get("status") == "success":
                        ip_addr = item.get("query", "")
                        data = {
                            "country": item.get("country"),
                            "country_code": item.get("countryCode"),
                            "city": item.get("city"),
                            "isp": item.get("isp"),
                            "org": item.get("org"),
                        }
                        cache_result(ip_addr, data)
                        results[ip_addr] = data
            elif resp.status_code == 429:
                # Rate limited — wait and stop processing further chunks
                logger.warning("geo_service.batch_lookup: rate limited (429), stopping")
                break
        except Exception as e:
            logger.warning("geo_service.batch_lookup chunk error: %s", e)

        # Small delay between chunks to respect rate limits
        if i + 100 < len(to_fetch):
            time.sleep(2)

    return results
