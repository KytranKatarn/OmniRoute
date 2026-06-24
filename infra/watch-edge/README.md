# Watch-Series Edge Funnels

DIY regional edge/CDN for the Watch products, run on our own fleet (Beacon + outposts)
instead of a paid CDN. Design: `.claude/plans/2026-06-18-watch-edge-funnel-cdn-design.md`
(project #364, task #4319/#4320). Caches public feed data, rate-limits (per-IP + global),
and shields the origin — the defense against the distributed-scraper overload that took
what-the-fact.com down (KB mistake #273994).

## wtf/ — Funnel #0 (Phase 0, North-America / Beacon)

An **nginx** edge that fronts `what-the-fact.com`. **Phase-0 = validation only:** it runs on
Beacon on **test port 8088** (NOT :443) and the public DNS is **not** cut over, so it has
zero impact on live traffic or Beacon's host-Caddy front-door.

- **Node:** Beacon (`100.64.0.11`, public `2.25.170.252`). SSH `root@100.64.0.11`.
- **Origin:** wtf-consumer on Citadel over the mesh — `100.64.0.10:8103` (IP only, never a
  public hostname).
- **Cache:** anonymous `/news` only (origin sends `Vary: Cookie`; we bypass + never store any
  cookie-bearing request, so paywall/personalization can't leak), TTL 30s, serve-stale on
  origin error, collapse concurrent misses.
- **Rate-limit:** per-IP 5r/s (burst 20) + global 50r/s (burst 200) on `/news`.
- **Cache status:** `X-Edge-Cache` response header (`HIT`/`MISS`/`BYPASS`).

### Deploy / teardown (on Beacon, `/opt/archie-edge/wtf/`)
```bash
docker compose up -d        # start the edge on :8088
docker compose down         # instant teardown — zero impact on :443 front-door
```

### Validate (no public traffic touched)
```bash
# from Beacon: anon /news twice -> MISS then HIT; cookie -> BYPASS; health
python3 - <<'PY'
import urllib.request as u
def g(h):
    r=u.urlopen(u.Request("http://127.0.0.1:8088/news", headers=h), timeout=15);
    return r.status, r.headers.get("X-Edge-Cache")
print("anon1", g({"Host":"what-the-fact.com"}))
print("anon2", g({"Host":"what-the-fact.com"}))   # expect HIT
print("cookie", g({"Host":"what-the-fact.com","Cookie":"session=x"}))  # expect BYPASS
PY
```

## NOT done in Phase 0 (separately-approved later steps)
- Public DNS cutover (`what-the-fact.com` A-record → the edge). Instant rollback = revert it.
- Origin lockdown (restrict wtf-consumer to mesh/edge-only) — additive-then-flip.
- Layer-1 GeoDNS routing + regional funnels (UK/SG/LT) — owner picks the GeoDNS provider.
- Productionization: TLS at the edge, harden the nginx container, generalize to other Watch products.
