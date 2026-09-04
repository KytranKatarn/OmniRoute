"""/platforms placeholder blocker text (#6272, Batch 9) — honesty correction.

The stored blocker text previously said parliament.mp_promises held 5,561
"rows of member commitments" waiting only to be linked to their source
document. Direct inspection of the table (row sample, not just a row count)
found the opposite: the rows are naive keyword-matched article snippets —
sampled content includes ad boilerplate and a comment-widget footer, not
actual quoted promises. The old text was generous to the point of being
misleading about what would need to happen to ship this page. This
corrects the copy; it does NOT change /platforms' status (still a
_COMING_SOON stub) or attempt to build the page.
"""

import pathlib

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"


def _platforms_blocker_text():
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index('"platforms": (')
    end = src.index("),", start)
    return src[start:end]


class TestBlockerTextIsHonest:
    def test_names_the_real_data_quality_problem(self):
        body = _platforms_blocker_text()
        assert "not verified commitments" in body
        assert "boilerplate" in body or "comment-widget" in body

    def test_still_names_the_table_and_row_count(self):
        body = _platforms_blocker_text()
        assert "parliament.mp_promises" in body
        assert "5,561" in body

    def test_no_longer_implies_the_data_just_needs_linking(self):
        """The old text framed this as a linking gap ('nothing yet links
        them to the platform text they came from'), which understated the
        problem — the rows themselves are not reliably promises at all."""
        body = _platforms_blocker_text()
        assert "nothing yet links them to the" not in body

    def test_platforms_is_still_a_coming_soon_stub(self):
        """This is a copy fix, not a graduation — /platforms must NOT have
        gained a real route."""
        src = ROUTES.read_text(encoding="utf-8")
        assert '@bp.get("/platforms")' not in src
