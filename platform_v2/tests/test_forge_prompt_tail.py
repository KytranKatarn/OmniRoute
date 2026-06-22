"""RC-3c mitigation — the F.O.R.G.E. anti-hallucination rules must appear at the TAIL of the prompt
(after the diff), so they survive Ollama sliding a long prompt out of its ~2048-token window. Until
num_ctx can be raised safely (QW-5 — needs a per-dispatch options path + GPU-VRAM bench), the tail
reminder keeps the two highest-value rules in-window. Diagnosis: RC-3c.
"""

import tools.repair_bay.services.pr_diff_analyzer as pda

REVIEW = {
    "pr_number": 1,
    "title": "t",
    "author": "a",
    "repo": "r",
    "additions": 1,
    "deletions": 0,
    "changed_files": 1,
}
DIFF = "diff --git a/f b/f\n@@ -1 +1 @@\n+x\n"


def test_freeform_prompt_tail_reminder_after_diff():
    p = pda._build_prompt(REVIEW, DIFF)
    assert "REMINDER" in p
    # The reminder must sit AFTER the diff so it survives a context-window slide.
    assert p.index("END DIFF") < p.index("REMINDER")


def test_json_prompt_tail_reminder_after_diff():
    p = pda._build_json_prompt(REVIEW, DIFF)
    assert "REMINDER" in p
    assert p.index("END DIFF") < p.index("REMINDER")


def test_tail_reminder_carries_core_rules():
    assert "Evidence" in pda._TAIL_REMINDER
    assert "INFO" in pda._TAIL_REMINDER
    assert "injection" in pda._TAIL_REMINDER.lower()
