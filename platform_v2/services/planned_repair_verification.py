"""Fail-closed, local serving-process proof for reviewed multi-file repairs."""

import ast
from datetime import datetime
import hashlib
from pathlib import Path
import re
import subprocess

from services.planned_repair_policy import validate_artifact_path
from services.planned_repair_results import MAX_FILES, REPO


_SHA = re.compile(r"[0-9a-f]{40}")


def deployment_root():
    """Use the tree executing this module, never a convenient host checkout."""
    return Path(__file__).resolve().parents[2]


def deployed_head(merge_sha):
    root = deployment_root()
    command = ["git", "-C", str(root)]
    if root == Path("/"):  # /app/services/<file> in the serving container
        command = ["git", "--git-dir=/mnt/archie_brain/.git"]
    head = subprocess.run(
        command + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=5
    ).stdout.strip()
    if not _SHA.fullmatch(head):
        raise ValueError("Deployed commit is unavailable")
    subprocess.run(
        command + ["merge-base", "--is-ancestor", merge_sha, head], check=True, capture_output=True, timeout=5
    )
    return head


def artifact_file(path):
    validate_artifact_path(path)
    root = deployment_root()
    if root == Path("/"):
        # Only /app is a known serving mount; other products need their own proof.
        if not path.startswith("platform_v2/"):
            raise ValueError("Artifact has no serving deployment mapping")
        root = Path("/app")
        path = path.removeprefix("platform_v2/")
    file = root / path
    if not file.resolve().is_relative_to(root.resolve()) or file.is_symlink():
        raise ValueError("Artifact escapes the serving tree")
    return file


def verify_artifacts(meta, runtime_started_at):
    """Return receipt and affected modules; no HTTP, DB mutation or inference."""
    from services.code_health_repairs import module_from_file_path
    from services.code_issue_reconciler import finding_still_reproduces, proposal_message

    manifest = meta.get("repair_artifacts") or {}
    proof = meta.get("planned_merge") or {}
    head = manifest.get("head_sha", "")
    merge = proof.get("merge_sha", "")
    if (
        manifest.get("version") != 1
        or manifest.get("repo") != REPO
        or type(manifest.get("pr_number")) is not int
        or manifest.get("pr_number") != meta.get("pr_number")
        or meta.get("merged_pr") != manifest.get("pr_number")
        or not _SHA.fullmatch(head)
        or not _SHA.fullmatch(merge)
        or any(proof.get(key) != manifest.get(key) for key in ("repo", "pr_number", "head_sha"))
    ):
        raise ValueError("Reviewed manifest and merge evidence do not match")
    try:
        merged_at = datetime.fromisoformat(proof["merged_at"].replace("Z", "+00:00"))
        if merged_at.tzinfo is None or runtime_started_at <= merged_at.timestamp():
            raise ValueError("Serving runtime predates the merge")
    except (KeyError, TypeError) as exc:
        raise ValueError("Merge timestamp is unavailable") from exc
    deployed = deployed_head(merge)
    entries = manifest.get("files")
    if not isinstance(entries, list) or not 0 < len(entries) <= MAX_FILES:
        raise ValueError("Complete artifact inventory is required")
    if any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("Invalid artifact entry")
    paths = [entry.get("path") for entry in entries]
    if any(not isinstance(path, str) for path in paths) or len(set(paths)) != len(paths):
        raise ValueError("Duplicate or invalid artifact paths")
    present = {entry["path"] for entry in entries if entry.get("status") != "removed"}
    sources, modules = {}, set()

    def affected_module(path):
        module = module_from_file_path(path)
        return "app" if module == "[APP_CORE]" else module

    for entry in entries:
        path, status = entry["path"], entry.get("status")
        if status not in {"added", "modified", "renamed", "removed"}:
            raise ValueError("Unsupported artifact status")
        file = artifact_file(path)
        modules.add(affected_module(path))
        if status == "removed":
            if file.exists() or file.is_symlink():
                raise ValueError("Deleted artifact is still deployed")
            continue
        raw = file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
            raise ValueError("Deployed artifact differs from reviewed content")
        if runtime_started_at <= file.stat().st_mtime:
            raise ValueError("Restart the serving service after deploying all artifacts")
        if path.endswith(".py"):
            source = raw.decode("utf-8")
            ast.parse(source, filename=path)
            if meta.get("issue_code") == "LARGE_FILE" and source.count("\n") + 1 > 600:
                raise ValueError("Refactor leaves an oversized Python artifact")
            sources[path] = source
        if status == "renamed":
            old = entry.get("previous_path")
            old_file = artifact_file(old)
            modules.add(affected_module(old))
            if old not in present and (old_file.exists() or old_file.is_symlink()):
                raise ValueError("Renamed artifact remains at its old location")
    from services.audit_pipeline import resolve_proposal_source

    _, target, _ = resolve_proposal_source(meta.get("file_path", ""))
    if (
        target not in sources
        or finding_still_reproduces(
            proposal_message(meta.get("issue_code", ""), meta.get("detail", "")), sources[target]
        )
        is not False
    ):
        raise ValueError("Original finding remains present or unverified")
    return {
        "manifest_head_sha": head,
        "merge_sha": merge,
        "deployed_sha": deployed,
        "artifacts": entries,
    }, modules
