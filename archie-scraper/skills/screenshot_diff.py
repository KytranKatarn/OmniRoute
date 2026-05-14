"""Skill: screenshot_diff — Compare current screenshot to stored baseline."""
import logging
import os
from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)


def _compare_images(current_path: str, baseline_path: str) -> float:
    try:
        from PIL import Image, ImageChops
        img1 = Image.open(baseline_path).convert("RGB")
        img2 = Image.open(current_path).convert("RGB")
        if img1.size != img2.size:
            img2 = img2.resize(img1.size)
        diff = ImageChops.difference(img1, img2)
        pixels = list(diff.getdata())
        total = sum(sum(p) for p in pixels)
        max_possible = len(pixels) * 3 * 255
        return 1.0 - (total / max_possible) if max_possible > 0 else 1.0
    except Exception as exc:
        logger.warning("screenshot_diff compare failed: %s", exc)
        return -1.0


def run(page, url: str, params: dict, job_id: int) -> dict:
    baseline_path = params.get("baseline_path") or ""
    threshold = float(params.get("threshold") or 0.9)

    page.goto(url, wait_until="networkidle", timeout=30000)
    current_path_rel = save_screenshot(job_id, "current", page)
    screenshot_dir = os.getenv("SCREENSHOT_DIR", "/mnt/screenshots")
    current_abs = os.path.join(screenshot_dir, current_path_rel)

    similarity = -1.0
    has_baseline = baseline_path and os.path.exists(baseline_path)
    if has_baseline:
        similarity = _compare_images(current_abs, baseline_path)

    changed = has_baseline and similarity >= 0 and similarity < threshold
    screenshots = [screenshot_entry("current", current_path_rel, f"Current (similarity={similarity:.2%})")]
    findings = (
        f"Visual diff: similarity={similarity:.2%} — {'CHANGED' if changed else 'OK'}"
        if has_baseline
        else f"No baseline — saved current to {current_path_rel}"
    )
    return {
        "data": {
            "similarity": similarity,
            "threshold": threshold,
            "changed": changed,
            "has_baseline": has_baseline,
            "current_path": current_path_rel,
        },
        "screenshots": screenshots,
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
