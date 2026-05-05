# Timezone Conventions (Established 2026-05-05)

The platform has ONE rule: **storage in UTC, user-facing in EDT.** Everything else is just enforcement of that rule.

## TL;DR for new code

```python
from services.time_utils import now_utc, now_local_str, format_local

# Storage / internals — aware UTC
row["created_at"] = now_utc()                                   # ✅
ttl = now_utc() + timedelta(hours=1)                            # ✅

# User-facing — America/Toronto with EDT/EST suffix
msg = f"Report generated at {now_local_str()}"                  # ✅
expires = format_local(row["expires_at"])                       # ✅
```

## Forbidden

| ❌ Don't | ✅ Use |
|---|---|
| `datetime.utcnow()` | `now_utc()` (deprecated in Python 3.12, returns NAIVE) |
| `datetime.now().strftime(...)` (in user output) | `now_local_str()` |
| `dt.strftime("%Y-%m-%d %H:%M UTC")` (literal "UTC" in user output) | `format_local(dt)` |
| `<span>{{ row.created_at }}</span>` (raw render in template) | `<span>{{ row.created_at \|localtime }}</span>` |
| `new Date().toISOString()` (raw render in JS UI) | `ArchieTime.format(iso, 'datetime')` |

## Storage layer (don't change)

* Postgres `timezone=UTC` (`SHOW timezone;`)
* All datetime columns use `TIMESTAMPTZ`
* psycopg2 returns timezone-aware UTC datetimes for these columns — that's correct, don't strip it

## Display layer (the fix)

| Surface | Mechanism |
|---|---|
| Server-rendered Jinja2 templates | `{{ value\|localtime }}` filter — emits `<span data-utc="..." data-fmt="...">fallback</span>` |
| Browser-side dynamic content | `archie-time.js` (`ArchieTime.format`, `ArchieTime.age`, etc.) — converts UTC → user's browser TZ |
| Backend-built strings going to user (Telegram, HTML reports, exported docs, KB vault notes) | `services.time_utils` helpers |
| Filenames / IDs / internal log markers | `now_utc()` is fine; format with `FMT_FILENAME_TIMESTAMP` if you need digits |

## Cron / schedulers

Every `CronTrigger(...)` in platform Python code MUST include
`timezone="America/Toronto"`. Container TZ inheritance is no longer the
contract (PR #543, Phase 2). Exception: NYSE-tied jobs (e.g.
`market_watch_cycle`) keep `timezone="America/New_York"`.

## Container TZ

`docker-compose.yml` and `docker-compose.sandbox.yml` declare
`TZ=America/Toronto` on every service. ComfyUI is the only one that
needs `/etc/localtime` + `/usr/share/zoneinfo` bind-mounts (its image
ships without `tzdata`).

## When you talk to the user (Claude / agents)

**EDT first, UTC only in parentheses for cross-checking server logs.**
"3:31 AM your time" beats "07:31 UTC" every time. Per
`feedback_timezone-communication.md` — Kytran is in Eastern, asking for
math is rude.

## How to spot drift

```bash
# Should always be empty (only docstrings excepted):
grep -rn 'datetime\.utcnow()' platform_v2/ ai_bridge/ --include='*.py' \
  | grep -v __pycache__ | grep -v migrations

# Should always be empty:
grep -rEn "['\"][^'\"]* UTC[^'\"]*['\"]" platform_v2/ ai_bridge/ \
  --include='*.py' --include='*.html' --include='*.js' \
  | grep -vE 'tzinfo|timezone\("UTC"\)|test_|migrations'

# Every CronTrigger should have timezone= kwarg:
grep -rEn 'CronTrigger\(' platform_v2/ ai_bridge/ --include='*.py' \
  | grep -v 'timezone=' | grep -v '^[^:]*:[^:]*:[[:space:]]*#'
```

The pre-commit hook `scripts/check_timezone_drift.py` runs the
first two checks on staged files.

## When in doubt

If you don't know whether a datetime will be shown to a user, use
`now_utc()` for the storage path and let the template filter or
`ArchieTime` JS handle the display layer. Default-safe: storage is
always UTC, display is always converted at the edge.
