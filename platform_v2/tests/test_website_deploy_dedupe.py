"""The website-deploy worker runs every 15 minutes, so it must not re-queue.

A queued deploy does NOT move `website_deploy_last_push_{domain}` — only
`mark_deploy_pushed()` does, because a queue is not a deploy. That is correct on
a daily cadence, where re-detecting one unpushed change once a day is harmless.
At 15 minutes it means a site awaiting a push re-detects the same files every
tick: up to 96 redundant queues a day for the same work.

So the worker records a hash of the changed-file set it queued
(`mark_deploy_queued`) and skips a tick whose set is identical — UNLESS the last
attempt failed, which must always retry or a transient error strands the site
forever, which is the exact failure the dedupe exists to prevent.

These read the real module via `inspect`, not a file path: the suite runs both
in the container (/app) and host-side, where the checkout root differs.

The pre-existing worker tests in test_website_deploy_worker.py pin the status
rules and must keep passing; their harness was extended with the new surface.
"""

import importlib
import inspect

ds = importlib.import_module("services.deploy_service")


def _worker_source() -> str:
    al = importlib.import_module("ai_bridge.agent_loop")
    return inspect.getsource(al.AgentLoop._website_deploy_worker)


# ── the hash helper ──────────────────────────────────────────────────────────


def test_hash_is_order_independent():
    assert ds.changed_files_hash(["b.txt", "a.txt"]) == ds.changed_files_hash(["a.txt", "b.txt"])


def test_hash_changes_when_the_set_changes():
    assert ds.changed_files_hash(["a.txt"]) != ds.changed_files_hash(["a.txt", "b.txt"])


def test_hash_of_empty_is_stable_and_not_none():
    # An empty set must hash to something, not None: None means "never queued",
    # and conflating the two would suppress the first real queue.
    assert ds.changed_files_hash([]) == ds.changed_files_hash([])
    assert ds.changed_files_hash(None) == ds.changed_files_hash([])


def test_hash_tolerates_none_entries():
    assert ds.changed_files_hash(["a.txt", None]) == ds.changed_files_hash([None, "a.txt"])


# ── the two watermarks must be different keys ────────────────────────────────


def test_queue_and_push_watermarks_are_different_keys():
    """If they shared a key, queuing would advance the push watermark.

    `changed_files_since()` would then stop seeing the very files still awaiting
    a push, and the site would report 'nothing to deploy' while genuinely
    unpushed — the inverse of the bug this is guarding.
    """
    q = inspect.getsource(ds.last_queued_hash)
    p = inspect.getsource(ds.last_push_iso)
    assert "website_deploy_queue_hash_" in q
    assert "website_deploy_last_push_" in p
    assert "website_deploy_queue_hash_" not in p
    assert "website_deploy_last_push_" not in q


def test_mark_deploy_queued_is_not_a_status_claim():
    """It must not write 'deployed'/'success' — only mark_deploy_pushed may."""
    src = inspect.getsource(ds.mark_deploy_queued)
    assert "deployed" not in src.lower().replace("mark_deploy_pushed", "")
    assert "success" not in src.lower()


# ── the worker's decision ────────────────────────────────────────────────────


def test_worker_has_the_dedupe_branch():
    body = _worker_source()
    assert "last_queued_hash" in body, "dedupe lookup removed from the worker"
    assert "changed_files_hash" in body, "dedupe compare removed from the worker"
    assert "mark_deploy_queued" in body, "queue is no longer stamped — the dedupe could never hit"


def test_a_failed_queue_is_always_retried():
    body = _worker_source()
    assert (
        "if _already_queued and not failed:" in body
    ), "a FAILED queue must always retry — deduping it would strand the site forever"


def test_dedupe_precedes_the_queue_call():
    """The skip must set nothing_to_do, which is what gates run_deploy_pipeline."""
    body = _worker_source()
    assert body.index("_already_queued") < body.index(
        "if not nothing_to_do:"
    ), "the dedupe runs after the queue gate, so it can never prevent a queue"


def test_worker_interval_is_15_minutes_not_daily():
    al = importlib.import_module("ai_bridge.agent_loop")
    src = inspect.getsource(al.AgentLoop)
    window = src[src.index('id="website_deploy_worker"') - 900 : src.index('id="website_deploy_worker"')]
    assert "IntervalTrigger" in window, "worker is not on an interval trigger"
    assert "minutes=15" in window, "interval is not 15 minutes"
    assert "CronTrigger(hour=3" not in window, "the daily 03:00 cron is still in place"
