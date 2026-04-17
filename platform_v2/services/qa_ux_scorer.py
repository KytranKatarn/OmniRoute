"""P.R.O.B.E. UX Scorer — Playwright screenshot + Department HQ vision dispatch.

Takes a screenshot of each configured breakpoint, sends it through the
canonical dispatch entry point with ``capability='vision'``, parses a
JSON score response, and persists the result to ``qa_ux_rubric_scores``.

Design doc: docs/superpowers/specs/2026-04-16-probe-capability-upgrade-design.md
Task: #2029 — follow-up to research task #2022.

YAML test spec::

    - name: ac-ux-score
      type: ux_score
      path: /tools/account-center/
      breakpoints: [1024]
      rubric: probe-ux-rubric-v1
      min_score: 3.5
      # Optional: override the default rubric prompt inline
      prompt: "..."

Execution model: called as a batch from qa_spec_runner via subprocess so
Playwright async runs in its own event loop while the Flask worker stays
sync, same pattern as visual_snapshot. Scores are stored keyed by run +
suite + breakpoint; summary pass/fail results also flow into
``qa_test_results`` via the normal runner pipeline.
"""

import base64
import json
import logging
import re

from playwright.async_api import async_playwright

logger = logging.getLogger("probe.ux")

# Default rubric prompt. Inlined rather than KB-fetched for simplicity —
# later we can move the rubric body into a vault_note keyed by version if
# we need revision history or multi-rubric support.
DEFAULT_RUBRIC_VERSION = "probe-ux-rubric-v1"
DEFAULT_RUBRIC_PROMPT = """You are a UX reviewer scoring a UI screenshot.

Rubric (each dimension on a 1-5 integer scale):

- navigation_clarity: Can you tell what's clickable and where you are
  in the app? (5 = crystal clear active tab and call-to-action,
  1 = confusing / everything looks static)
- information_density: Is the content density appropriate — not empty,
  not overloaded?
- accent_consistency: Are accent colors and frame elements used
  consistently with the LCARS theme?
- empty_state_handling: Are empty lists or blank panels handled
  gracefully (with a placeholder message, illustration, or helpful CTA)?

Return ONLY a JSON object with these exact keys, nothing outside the JSON:

{
  "navigation_clarity": <1-5>,
  "information_density": <1-5>,
  "accent_consistency": <1-5>,
  "empty_state_handling": <1-5>,
  "rationale": "<one sentence explaining the overall score>"
}
"""


def parse_score_json(text):
    """Extract the first JSON object from a vision-model reply.

    Tolerant of markdown code fences and leading/trailing prose.
    Returns ``None`` if no parseable JSON object is present.
    """
    if not text:
        return None
    stripped = re.sub(r"```(?:json)?\s*", "", text)
    stripped = stripped.replace("```", "")
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def _authenticate(context, base_url, auth):
    if not (auth and auth.get("username") and auth.get("password")):
        return
    page = await context.new_page()
    try:
        await page.goto(f"{base_url}/login", wait_until="networkidle", timeout=15000)
        await page.fill(
            'input[name="username"], #username, input[type="text"]',
            auth["username"],
        )
        await page.fill(
            'input[name="password"], #password, input[type="password"]',
            auth["password"],
        )
        await page.click('button[type="submit"], input[type="submit"], .btn-primary')
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as e:
        logger.warning("UX scorer auth failed: %s", e)
    finally:
        await page.close()


async def _screenshot_b64(context, base_url, path, breakpoint_px, max_dim=512):
    """Screenshot a page and return a base64-encoded PNG.

    Downscales so the longest edge is ``max_dim`` before encoding. A full
    1024px LCARS page pushes qwen2.5vl:7b past a 360s timeout on CPU-only
    inference; 512 px keeps enough detail for layout/token scoring while
    cutting inference time dramatically.
    """
    from io import BytesIO
    from PIL import Image

    page = await context.new_page()
    try:
        await page.set_viewport_size({"width": int(breakpoint_px), "height": 1024})
        await page.goto(f"{base_url}{path}", wait_until="networkidle", timeout=30000)
        raw = await page.screenshot(full_page=False)
    finally:
        await page.close()

    img = Image.open(BytesIO(raw))
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)
    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return base64.b64encode(out.getvalue()).decode()


async def execute_batch(tests, base_url, auth, suite_id, run_id):
    """Run every ux_score test at every configured breakpoint.

    Returns a list of result dicts for the parent ``qa_spec_runner`` to
    write into ``qa_test_results``. Detailed per-dimension scores are
    written to ``qa_ux_rubric_scores`` here.
    """
    from database import get_db_cursor
    from psycopg2.extras import Json

    # Local import — dispatch is resolved inside the subprocess that invokes
    # this function so sys.path is already set up for the caller.
    from tools.department_hq.services.department_dispatcher import dispatch

    all_results = []
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    try:
        context = await browser.new_context(ignore_https_errors=True)
        await _authenticate(context, base_url, auth)

        for test in tests:
            test_name_base = test.get("name", "unnamed_ux")
            path = test.get("path", "/")
            breakpoints = test.get("breakpoints") or [1024]
            min_score = float(test.get("min_score", 3.5))
            rubric_version = test.get("rubric") or DEFAULT_RUBRIC_VERSION
            prompt = test.get("prompt") or DEFAULT_RUBRIC_PROMPT

            for bp in breakpoints:
                test_name = f"{test_name_base}-bp{bp}"
                url = f"{base_url}{path}"
                try:
                    b64 = await _screenshot_b64(context, base_url, path, bp)
                except Exception as e:
                    all_results.append(
                        {
                            "test_name": test_name,
                            "test_type": "ux_score",
                            "status": "error",
                            "url": url,
                            "error_message": f"Screenshot failed: {e}"[:500],
                        }
                    )
                    continue

                try:
                    # Local 7B vision on CPU needs 3-5 min for real pages.
                    result = dispatch(
                        capability="vision",
                        prompt=prompt,
                        module_id="qa_ux_scorer",
                        images=[b64],
                        local_only=True,
                        timeout=360,
                    )
                except Exception as e:
                    all_results.append(
                        {
                            "test_name": test_name,
                            "test_type": "ux_score",
                            "status": "error",
                            "url": url,
                            "error_message": f"Dispatch failed: {e}"[:500],
                        }
                    )
                    continue

                if not result.success:
                    all_results.append(
                        {
                            "test_name": test_name,
                            "test_type": "ux_score",
                            "status": "error",
                            "url": url,
                            "error_message": (result.error or "Dispatch returned no response")[:500],
                        }
                    )
                    continue

                scores_obj = parse_score_json(result.response or "")
                if not scores_obj:
                    all_results.append(
                        {
                            "test_name": test_name,
                            "test_type": "ux_score",
                            "status": "error",
                            "url": url,
                            "error_message": ("Could not parse score JSON from: " f"{(result.response or '')[:200]}"),
                        }
                    )
                    continue

                dim_scores = {
                    k: float(v) for k, v in scores_obj.items() if k != "rationale" and isinstance(v, (int, float))
                }
                rationale = scores_obj.get("rationale")
                overall = round(sum(dim_scores.values()) / len(dim_scores), 2) if dim_scores else 0.0
                passed = overall >= min_score

                try:
                    with get_db_cursor(commit=True) as (_c, cur):
                        cur.execute(
                            """INSERT INTO qa_ux_rubric_scores
                               (run_id, suite_id, rubric_version, path,
                                breakpoint, scores, overall_score, passed,
                                model_used, rationale)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                run_id,
                                suite_id,
                                rubric_version,
                                path,
                                int(bp),
                                Json(dim_scores),
                                overall,
                                passed,
                                result.model_used,
                                rationale,
                            ),
                        )
                except Exception as e:
                    logger.warning("Failed to store UX rubric score: %s", e)

                all_results.append(
                    {
                        "test_name": test_name,
                        "test_type": "ux_score",
                        "status": "pass" if passed else "fail",
                        "url": url,
                        "error_message": (
                            None
                            if passed
                            else f"Overall score {overall} below threshold {min_score}. " f"{(rationale or '')[:180]}"
                        ),
                        "assertions": {
                            "scores": dim_scores,
                            "overall_score": overall,
                            "min_score": min_score,
                            "rationale": rationale,
                            "model": result.model_used,
                            "rubric_version": rubric_version,
                            "breakpoint": int(bp),
                        },
                    }
                )
    finally:
        try:
            await browser.close()
        except Exception:
            pass
        try:
            await pw.stop()
        except Exception:
            pass

    return all_results
