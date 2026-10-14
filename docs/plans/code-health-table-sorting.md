# Code Health table sorting

Module Breakdown, Standalone Products and Websites default to Lines descending,
including infrastructure modules in the same ordering. Click column headings to
sort names, profiles, statuses, issues, files and lines; click again to reverse.
Audit Progress defaults to newest date and also supports trigger/proposal sorting.
Each section keeps its own selection through in-page data refreshes. A browser
reload restores defaults; no backend preference or production data is changed.

Numeric sorting understands comma-separated line counts. Status sorting groups
attention first: issues, in repair, findings, attention, stale, unaudited, clean.
Audit dates use raw timestamps rather than relative-age labels; missing dates
stay last in both directions. Pattern Compliance summary rows remain pinned at
the bottom. Sorting moves existing DOM nodes to preserve action handlers and
current search visibility. Buttons support keyboard activation, direction arrows,
accessible next-action labels and `aria-sort` on column headings.

## Validation

```bash
node --check platform_v2/static/js/consciousness.js
PYTHONPATH=platform_v2:ai_bridge python3 -m pytest --noconftest \
  -p tests.review_test_bootstrap -p no:cacheprovider -q \
  platform_v2/tests/test_code_health_table_sorting.py
git diff --check
```

Eight offline Playwright checks exercise the actual renderers: numeric direction,
all three module sections, keyboard activation, independent refresh state,
search/action preservation, audit date/issues ordering, missing dates and pinned
summary rows. The old renderer in a throwaway browser fails the largest-first
assertion. Screenshots are saved to `/tmp/code-health-table-sorting/` (before,
after, after-mobile). Fixture data and blocked network; not authenticated live QA.

Human merge and normal frontend release/provenance checks remain required. No
scanner run, inference, migrations, service restart or deployment is part of
this PR. Roll back by reverting its JavaScript/CSS and refreshing those assets;
no data or schema rollback is required.
