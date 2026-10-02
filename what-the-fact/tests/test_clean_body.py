"""clean_body: read-time cleaner for stored article bodies. Plain Python — run with
`python3 tests/test_clean_body.py`. Every furniture case below is from LIVE output
quoted in ingest/content_kind.py, not invented."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ingest.content_kind import clean_body

PROSE = ("The mayor said the transit plan will cost $4 million over three years. "
         "Council voted 7 to 4 to approve the first phase on Tuesday. "
         "Residents along the corridor said they were worried about construction noise. "
         "A report from city staff recommended a phased rollout starting in the spring.")


def test_prose_passes_unchanged():
    out = clean_body(PROSE)
    assert out == PROSE                        # nothing invented, nothing lost
    assert "recommended" in out                # ordinary prose word is NOT furniture


def test_saltwire_sidebar_sentence_is_dropped():
    body = PROSE + " …Sea-to-Sky corridor 1 hour ago Lifestyle Made in Canada: Five back to school wardrobe staples. " + PROSE
    out = clean_body(body)
    assert "wardrobe" not in out and "1 hour ago" not in out
    assert "Council voted 7 to 4" in out


def test_recommendation_rail_is_dropped():
    body = PROSE + " MORE ON POLITICS MORE VIDEOS Doug Ford's symbolic Lake Ontario sign cost $25k: Premier's office. "
    out = clean_body(body)
    assert "MORE ON POLITICS" not in out and "symbolic" not in out


def test_subscribe_cookie_and_timestamp_furniture():
    body = PROSE + " Sign up for our newsletter. We use cookies on this site. 5 min read. Photo by Getty Images."
    out = clean_body(body)
    for bad in ("newsletter", "cookies", "min read", "Getty"):
        assert bad not in out


def test_repeated_pull_quote_kept_once():
    q = "Council voted 7 to 4 to approve the first phase on Tuesday."
    out = clean_body(PROSE + " " + q)
    assert out.count("Council voted 7 to 4") == 1


def test_paragraph_breaks_kept_when_present():
    out = clean_body(PROSE.split(". ")[0] + ".\n\n" + ". ".join(PROSE.split(". ")[1:]))
    assert "\n\n" in out


def test_mostly_page_returns_empty_not_a_guess():
    junk = " ".join(["MORE ON POLITICS MORE VIDEOS Sign up now."] * 8) + " The mayor spoke briefly."
    assert clean_body(junk) == ""


def test_too_short_or_empty_returns_empty():
    assert clean_body(None) == "" and clean_body("") == ""
    assert clean_body("The mayor spoke.") == ""


def test_max_chars_cuts_on_a_sentence_boundary():
    out = clean_body(PROSE, max_chars=170)
    assert out.endswith(".") and len(out) <= 170
    assert out.startswith("The mayor said the transit plan")
    assert clean_body(PROSE, max_chars=20) == ""      # no partial sentence ever


def test_input_is_not_mutated_and_output_is_verbatim_spans():
    body = PROSE + " Sign up for our newsletter."
    out = clean_body(body)
    assert all(s in body for s in out.split(". ") if s.strip(". "))   # only verbatim text


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
