import os
from pathlib import Path

SCREENSHOT_DIR = os.getenv("SCREENSHOT_DIR", "/mnt/screenshots")


def save_screenshot(job_id: int, step: str, page) -> str:
    """Take full-page screenshot, return relative path string."""
    job_dir = Path(SCREENSHOT_DIR) / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / f"{step}.png"
    page.screenshot(path=str(path), full_page=True)
    return f"{job_id}/{step}.png"


def screenshot_entry(step: str, path: str, caption: str = "") -> dict:
    return {"step": step, "path": path, "caption": caption}
