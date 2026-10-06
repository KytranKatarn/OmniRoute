"""The probe-now button must not splice a database value into its onclick JavaScript.

`escapeHtml` turns ' into &#39;, but the browser decodes the attribute BEFORE the JavaScript in it
runs, so `probeProviderNow('<escaped key>', this)` lets a key containing a quote break out of the
string. The key travels in a data attribute and the handler reads `this.dataset.providerKey`.
(Found by the automated security review on PR #3669; provider_key is admin-managed so exploitability
was low, but the pattern is wrong.)
"""

import pathlib
import re
import unittest

JS = pathlib.Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "static" / "js" / "department-hq.js"


def _button_source(src):
    i = src.index('contractor-btn-probe" title=')
    return src[i : src.index("</button>';", i)]


class TestProbeButtonKeyHandling(unittest.TestCase):
    def setUp(self):
        self.src = JS.read_text(encoding="utf-8")
        self.btn = _button_source(self.src)

    def test_the_key_is_carried_in_a_data_attribute(self):
        self.assertIn("data-provider-key=", self.btn)
        self.assertIn("providerKey", self.btn)

    def test_the_handler_reads_the_dataset(self):
        self.assertIn("probeProviderNow(this.dataset.providerKey, this)", self.btn)

    def test_no_value_is_spliced_into_the_onclick_javascript(self):
        onclick = re.search(r'onclick="([^"]*)"', self.btn.replace("' + '", ""))
        # the handler body must be a fixed string: no concatenation inside the quotes
        handler = self.btn[self.btn.index('onclick="') :]
        handler = handler[: handler.index('">')]
        self.assertNotIn("escapeHtml(", handler)
        self.assertNotIn("p.provider_key", handler)
        self.assertIsNotNone(onclick)

    def test_the_old_splice_is_gone_from_the_file(self):
        self.assertNotIn("probeProviderNow(\\'' + escapeHtml", self.src)

    def test_the_key_comes_from_the_rows_own_key_not_a_field_the_payload_lacks(self):
        """The list payload names the provider `p.provider`; the row derives `providerKey` from it
        and the other buttons use that. `p.provider_key` does not exist there, so the probe button
        shipped with an EMPTY key on all 30 rows (found live, not by a source-text test)."""
        self.assertIn("data-provider-key=\"' + providerKey + '\"", self.btn)
        self.assertNotIn("p.provider_key", self.btn)
        self.assertRegex(self.src, r"var providerKey = escapeHtml\(p\.provider \|\| p\.name \|\| ''\);")


if __name__ == "__main__":
    unittest.main()
