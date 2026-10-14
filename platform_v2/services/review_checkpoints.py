"""Bounded interrupted-review checkpoints in existing Repair Bay metadata."""

import hashlib
import json
import re

from database import get_db_cursor
from psycopg2.extras import Json

VERSION = 1
MAX_PASSES = 100
MAX_SUMMARY = 16000


def persist_checkpoint(pr_number, repo, head_sha, payload):
    """No new store/schema; never update a different head or terminal review."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET metadata=jsonb_set(COALESCE(metadata,'{}'::jsonb), "
            "'{review_pass_checkpoint}', %s::jsonb, true) "
            "WHERE pr_number=%s AND repo=%s AND review_status='in_progress' "
            "AND metadata->>'head_sha'=%s",
            (Json(payload), pr_number, repo, head_sha),
        )
        return cur.rowcount > 0


class ReviewCheckpoint:
    def __init__(self, key, pr_number, repo, head_sha, previous=None):
        self.key, self.pr_number, self.repo, self.head_sha = key, pr_number, repo, head_sha
        self.passes = {}
        if (
            isinstance(previous, dict)
            and previous.get("version") == VERSION
            and previous.get("context_key") == key
            and previous.get("complete") is False
            and isinstance(previous.get("passes"), dict)
            and len(previous["passes"]) <= MAX_PASSES
        ):
            self.passes = dict(previous["passes"])

    def lookup(self, chunk, cap):
        entry = self.passes.get(hashlib.sha256(chunk.encode()).hexdigest())
        if not isinstance(entry, dict):
            return None
        summary = entry.get("summary")
        if (
            not isinstance(summary, str)
            or not 0 < len(summary) <= MAX_SUMMARY
            or entry.get("cap") != cap
            or entry.get("summary_sha256") != hashlib.sha256(summary.encode()).hexdigest()
        ):
            return None
        return summary

    def remember(self, chunk, summary, cap):
        if not isinstance(summary, str) or not 0 < len(summary) <= MAX_SUMMARY or len(self.passes) >= MAX_PASSES:
            return
        self.passes[hashlib.sha256(chunk.encode()).hexdigest()] = {
            "summary": summary,
            "summary_sha256": hashlib.sha256(summary.encode()).hexdigest(),
            "cap": cap,
        }
        self.save(False)

    def save(self, complete):
        try:
            return persist_checkpoint(
                self.pr_number,
                self.repo,
                self.head_sha,
                {"version": VERSION, "context_key": self.key, "complete": complete, "passes": self.passes},
            )
        except Exception:
            return False  # A cache outage must never manufacture or block a review.


def checkpoint_for(review, diff, repo, pr_number, policy, reviewer, wide=False):
    """Require fresh head/base identity, named reviewer, full diff and policy context."""
    identity = review.get("_checkpoint_identity")
    if wide or not pr_number or not repo or not reviewer or not isinstance(identity, dict):
        return None
    if not all(
        re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", str(identity.get(k, ""))) for k in ("head_sha", "base_sha")
    ):
        return None
    metadata = review.get("metadata") or {}
    if not isinstance(metadata, dict):
        return None
    context = {
        "identity": identity,
        "diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "repo": repo,
        "pr": pr_number,
        "policy": policy,
        "reviewer": reviewer,
        "title": review.get("title"),
        "author": review.get("author"),
        "reference": review.get("repository_context", ""),
    }
    key = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    return ReviewCheckpoint(key, pr_number, repo, identity["head_sha"], metadata.get("review_pass_checkpoint"))
