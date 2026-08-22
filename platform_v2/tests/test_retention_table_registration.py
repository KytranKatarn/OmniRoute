"""Every _TABLES entry must be fully WIRED, not merely declared (#5917).

Why this guard exists
---------------------
"Declared but never applied" is the single most repeated retention defect here:

  * the `vps` tier was declared for all 10 components in retention_prune.py while
    the string "vps" appeared NOWHERE else in the file — never pruned, outpost-us
    reached 100% disk on 2026-08-02 (#5616);
  * the gdrive tier had RETENTION tuples that `main()` never walked — the 15 GB
    free-tier account filled and the 1.5 GB DB dump was rejected
    `storageQuotaExceeded` for ~3 weeks (#5092).

`retention_prune.py` grew `test_every_tier_in_retention_has_a_pruner` after the
first one. `dispatch_retention_service.py` had no equivalent — this is it.

The failure mode here is DIFFERENT and worse than a silent skip. `run_retention`
does::

    for table, spec in _TABLES.items():
        keep_days = cfg[spec["keep_key"]]     # <- DIRECT index, no .get()

and the whole loop sits inside ONE outer ``try/except Exception``. So a `_TABLES`
entry whose `keep_key` is missing from `DEFAULTS` raises `KeyError`, the except
swallows it, and **retention is skipped for EVERY table** — not just the new one —
while the function returns ``{"enabled": None, "deleted": {}}``, which reads a lot
like "nothing to do". `_record_last_run` never fires either.
"""

import sys

sys.path.insert(0, "/app")

import services.dispatch_retention_service as drs  # noqa: E402


def test_every_table_has_a_default_keep_days():
    """The pairing that, if broken, takes down retention for ALL tables."""
    missing = [(t, spec["keep_key"]) for t, spec in drs._TABLES.items() if spec["keep_key"] not in drs.DEFAULTS]
    assert not missing, f"_TABLES entries with no DEFAULTS key (KeyError at prune time): {missing}"


def test_every_table_keep_days_is_overridable_from_platform_settings():
    """A keep_days nobody can tune without a deploy is a policy in name only."""
    tunable = set(drs._PS_KEYS.values())
    missing = [(t, spec["keep_key"]) for t, spec in drs._TABLES.items() if spec["keep_key"] not in tunable]
    assert not missing, f"_TABLES entries absent from _PS_KEYS (not tunable live): {missing}"


def test_every_table_spec_is_complete():
    for table, spec in drs._TABLES.items():
        assert spec.get("age_col"), f"{table}: no age_col — nothing to prune on"
        assert "statuses" in spec, f"{table}: statuses must be explicit (None = age-only)"
        assert spec.get("keep_key"), f"{table}: no keep_key"


def test_defaults_are_positive_ints_or_the_disable_sentinel():
    for table, spec in drs._TABLES.items():
        v = drs.DEFAULTS[spec["keep_key"]]
        assert isinstance(v, int), f"{table}: keep_days default must be int, got {type(v)}"
        # <=0 is the documented "skip this table" sentinel, so it is legal — but it
        # must be a deliberate int, never None (None would skip silently forever).
        assert v is not None


def test_model_placement_log_is_registered_and_age_only():
    """#5917 specifically — the observer table shipped in #5273 must be bounded."""
    spec = drs._TABLES.get("model_placement_log")
    assert spec is not None, "the #5273 observer table is unbounded — that is the #5616 bug again"
    assert spec["age_col"] == "created_at"
    assert spec["statuses"] is None, "append-only: every row is a completed decision"
    assert drs.DEFAULTS[spec["keep_key"]] > 0, "a 0 default would silently never prune it"


def test_a_table_missing_its_default_would_be_caught():
    """Proves this file can fail: simulate the exact mistake and confirm detection."""
    broken = dict(drs._TABLES)
    broken["some_new_table"] = {
        "age_col": "created_at",
        "statuses": None,
        "keep_key": "some_new_table_keep_days",  # deliberately absent from DEFAULTS
    }
    missing = [(t, s["keep_key"]) for t, s in broken.items() if s["keep_key"] not in drs.DEFAULTS]
    assert missing == [("some_new_table", "some_new_table_keep_days")]
