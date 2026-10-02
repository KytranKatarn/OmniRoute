"""Every compose service that builds from a Dockerfile declaring GIT_SHA must pass the build args.

Regression (2026-10-01): wtf-ingest-api builds Dockerfile.consumer and tags the SAME image as
wtf-consumer, but passed no args. `deploy.sh all` builds it last, re-tagging the image unstamped, so
the consumer came up reporting git_sha=unknown and the drift monitor was blind.
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _services():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def _stamped(dockerfile: str) -> bool:
    return bool(re.search(r"^ARG GIT_SHA", (ROOT / dockerfile).read_text(encoding="utf-8"), re.M))


def test_every_service_building_a_stamped_dockerfile_passes_the_stamp():
    missing = []
    for name, svc in _services().items():
        b = svc.get("build")
        if not isinstance(b, dict) or not b.get("dockerfile") or not _stamped(b["dockerfile"]):
            continue
        args = b.get("args") or {}
        if "GIT_SHA" not in args or "BUILD_TIME" not in args:
            missing.append(name)
    assert not missing, f"unstamped builds of a stamped Dockerfile: {missing}"


def test_services_sharing_an_image_tag_agree_on_their_build_args():
    by_image: dict[str, list[tuple[str, dict]]] = {}
    for name, svc in _services().items():
        if isinstance(svc.get("build"), dict) and svc.get("image"):
            by_image.setdefault(svc["image"], []).append((name, svc["build"].get("args") or {}))
    for image, group in by_image.items():
        assert all(a == group[0][1] for _, a in group), f"{image} is built with different args by {[n for n, _ in group]}"
