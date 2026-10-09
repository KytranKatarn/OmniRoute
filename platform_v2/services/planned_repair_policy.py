"""Current coder path policy for planned-repair artifact inventories."""

from pathlib import Path
import posixpath
import subprocess
import yaml


def load_scope():
    """Read the real lane policy even when the hub only mounts .git and /app.

    A present but invalid policy fails closed, without falling back to Git.
    Git reads the exact tracked file locally; no alternate allowlist is used.
    """
    root = Path(__file__).resolve().parents[2]
    candidates = (root / "config/agents/codex.yaml", Path("/mnt/archie_brain/config/agents/codex.yaml"))
    try:
        file = next((path for path in candidates if path.is_file()), None)
        if file:
            text = file.read_text()
        else:
            text = subprocess.run(
                ["git", "--git-dir=/mnt/archie_brain/.git", "show", "HEAD:config/agents/codex.yaml"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout
        config = yaml.safe_load(text)["codex"]
        if (
            not isinstance(config, dict)
            or not isinstance(config.get("allowed_paths"), list)
            or not config["allowed_paths"]
            or not isinstance(config.get("blocked_globs"), list)
            or any(not isinstance(item, str) or not item for item in config["allowed_paths"] + config["blocked_globs"])
        ):
            raise ValueError("Invalid coding lane scope")
        return config
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, subprocess.SubprocessError) as exc:
        raise ValueError("Coding lane scope could not be verified") from exc


def validate_artifact_path(path):
    from services.agents.codex_scope import is_in_scope
    from services.audit_pipeline import _SELF_GOVERNANCE_PATH_MARKERS

    if not isinstance(path, str) or "\\" in path or ".." in path.split("/") or posixpath.normpath(path) != path:
        raise ValueError("Unsafe artifact path")
    config = load_scope()
    if (
        not is_in_scope(path, config)
        or any(marker in path.lower() for marker in _SELF_GOVERNANCE_PATH_MARKERS)
        or path.startswith(("platform_v2/tools/repair_bay/", "platform_v2/tools/creed_command/"))
        or path.startswith("platform_v2/services/planned_repair_")
    ):
        raise ValueError("Artifact is outside planned repair scope or targets protected oversight")
    return path
