# Triage — the 152 remaining suite failures

**Measured** 2026-08-24 on `main` at 8 GiB via `scripts/run_tests.sh`:
`3,706 passed · 152 failed · 28 skipped · 11 errors` in ~2 min.
149 of the 163 failure/error lines produced a parseable traceback block.

This is the **first complete failure list the repo has ever had** — until #5998 the suite
could not finish. Everything below was invisible before that.

## Headline

**No confirmed production defect yet.** Every family identified so far is a *test-side* or
*environment* problem. That is a finding, not an assumption — but it is also **not proven for
the 51 unclassified**, which nobody has read.

## Families

| n | family | verdict | action |
|---|---|---|---|
| 15 | **Runner mounts** — `.claude/`, `database/`, `/var/run/docker.sock` absent | **NOT a defect.** Proven: 14 failed → 4 failed → **25 passed** as mounts were added | fix `run_tests.sh`; see the docker.sock caveat |
| 13 | **#5994** — `REPO_ROOT` resolves to `/`, so tests stat `/scripts/dr/...` | test bug, already filed | #5994 |
| 12 | **DB seed** — `archie_test` missing FK rows (`users`, `qa_test_suites`) | test-env | seed or fixture-create |
| 12 | HTTP **401/403** — auth/session fixture | likely test-env | needs a read |
| 8 | **Stale mock** — `telegram_service` has no `send_with_buttons` / `_log_message` / `send` | **same family as #5993**: production moved, tests didn't | mechanical |
| 7 | HTTP **404** — route missing or not registered | **unknown — could be real** | needs a read |
| 6 | `unittest.mock` **`issubclass() arg 1 must be a class`** (`test_approved_hire_lands_correctly.py`) | test-side: fails inside `mock.py:425` constructing the mock, never reaches production | mechanical |
| 5 | HTTP **500** — route raised | **unknown — most likely place for a real bug** | needs a read |
| 51 | **UNCLASSIFIED** | unknown | **read these** |

## The unclassified 51 — what pytest actually showed

| n | signature | note |
|---|---|---|
| 13 | `assert None` | all `ERROR at setup of` — a fixture returns None. One root cause, probably one fix. |
| 7 | `Use -v to get more diff` | pytest **truncated** the diff. Cannot be triaged from this run — re-run those with `-vv`. |
| 3 | `assert False is True` | |
| 3 | `- N` (numeric diff) | |
| 2 | `'NoneType' object is not subscriptable` | |
| 2 | `Expected 'mock' to have been called once. Called N times.` | |
| ~21 | long tail, mostly one-offs | |

## ⚠️ Caveats on this triage

- **The clustering is by error signature, not by cause.** Two tests can share
  `assert None` for different reasons. Treat the counts as a work-ordering aid, not a
  diagnosis.
- **`Use -v to get more diff` (7) is a hole** — the run was `-q`, so those assertions are
  unreadable. They are counted but *not* triaged.
- **The "MagicMock" bucket was initially over-captured** by a substring match and has been
  narrowed to the 6 that genuinely share `issubclass() arg 1`. A regex bucket that matches
  incidental mentions produces a confident wrong triage.
- **`docker.sock` is not a free fix.** Mounting it gives the test container root-equivalent
  control of the host. The 4 tests needing it inspect live containers
  (`test_platform_registry_services.py`). Options: mount it (accept the exposure), run those
  4 elsewhere, or mark them `needs_docker` and skip by default. **Owner's call — measured,
  deliberately not adopted.**

## Recommended order

1. **Runner mounts** (15) — largest, cheapest, and removes noise from every future run.
2. **#5994** (13) — already filed and understood.
3. **`assert None` fixture** (13) — one fixture, likely one fix.
4. **Stale telegram mocks** (8) + **issubclass** (6) — mechanical, same shape as #5993.
5. **HTTP 500 (5) then 404 (7)** — do these *before* the 401/403 bulk: a 500 is the most
   likely place a genuine production defect is hiding.
6. **DB seed** (12), **401/403** (12), then the remaining tail.
