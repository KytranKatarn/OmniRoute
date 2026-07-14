/**
 * Unit tests for bias-logic.js (#3328). Run: node tests/bias-logic.test.js
 * No test framework — plain node:assert so it runs anywhere node is installed.
 */
const assert = require("node:assert");
const B = require("../bias-logic.js");

let passed = 0;
function t(name, fn) {
  fn();
  passed++;
  console.log("ok -", name);
}

t("biasLabelToClass maps the 5 WTF bands to 3 buckets", () => {
  assert.equal(B.biasLabelToClass("left"), "wtf-bias-left");
  assert.equal(B.biasLabelToClass("center-left"), "wtf-bias-left");
  assert.equal(B.biasLabelToClass("center"), "wtf-bias-centre");
  assert.equal(B.biasLabelToClass("center-right"), "wtf-bias-right");
  assert.equal(B.biasLabelToClass("right"), "wtf-bias-right");
  assert.equal(B.biasLabelToClass("CENTRE"), "wtf-bias-centre"); // case + spelling
  assert.equal(B.biasLabelToClass("garbage"), null);
  assert.equal(B.biasLabelToClass(""), null);
  assert.equal(B.biasLabelToClass(null), null);
});

t("biasScoreToClass buckets the numeric score", () => {
  assert.equal(B.biasScoreToClass(-0.9), "wtf-bias-left");
  assert.equal(B.biasScoreToClass(0.9), "wtf-bias-right");
  assert.equal(B.biasScoreToClass(0.0), "wtf-bias-centre");
  assert.equal(B.biasScoreToClass(-0.2), "wtf-bias-centre"); // boundary inclusive of centre
  assert.equal(B.biasScoreToClass(null), "wtf-bias-unknown");
  assert.equal(B.biasScoreToClass(undefined), "wtf-bias-unknown");
  assert.equal(B.biasScoreToClass("not a number"), "wtf-bias-unknown");
});

t("resolveBiasClass prefers band, then lean, then score", () => {
  // The calgaryherald case: band=center must win over a disagreeing lean/score.
  assert.equal(B.resolveBiasClass("center", "center-right", 0.5), "wtf-bias-centre");
  assert.equal(B.resolveBiasClass(null, "center-right", -0.9), "wtf-bias-right"); // lean
  assert.equal(B.resolveBiasClass(null, null, -0.9), "wtf-bias-left"); // score
  assert.equal(B.resolveBiasClass(null, null, null), "wtf-bias-unknown"); // nothing
});

t("extractDomain handles absolute, www, relative, and junk", () => {
  assert.equal(B.extractDomain("https://www.cbc.ca/news/story"), "cbc.ca");
  assert.equal(B.extractDomain("http://TheStar.com/x"), "thestar.com");
  assert.equal(B.extractDomain("/relative/path"), null);
  assert.equal(B.extractDomain("mailto:a@b.com"), null);
  assert.equal(B.extractDomain("javascript:void(0)"), null);
  assert.equal(B.extractDomain("not a url"), null);
});

t("buildBiasMap keys by normalised domain with score/lean/band", () => {
  const m = B.buildBiasMap([
    { domain: "www.CBC.ca", avg_score: -0.3, bias_lean: "center-left", band: "center-left", name: "CBC" },
    { domain: "nationalpost.com", bias_score: 0.4, band: "center-right" },
    { name: "no domain — skipped" },
  ]);
  assert.deepEqual(m["cbc.ca"], { score: -0.3, lean: "center-left", band: "center-left" });
  assert.equal(m["nationalpost.com"].score, 0.4);
  assert.equal(m["nationalpost.com"].band, "center-right");
  assert.equal(Object.keys(m).length, 2);
});

t("buildNameMap prefers name, falls back to outlet_name then domain", () => {
  const m = B.buildNameMap([
    { domain: "cbc.ca", name: "CBC News" },
    { domain: "ctvnews.ca", outlet_name: "CTV" },
    { domain: "example.ca" },
  ]);
  assert.equal(m["cbc.ca"], "CBC News");
  assert.equal(m["ctvnews.ca"], "CTV");
  assert.equal(m["example.ca"], "example.ca");
});

t("formatBandLabel + biasDirectionText are human-readable", () => {
  assert.equal(B.formatBandLabel("center-left"), "Center-left");
  assert.equal(B.formatBandLabel(""), "Unrated");
  assert.equal(B.biasDirectionText("wtf-bias-left"), "Left-leaning");
  assert.equal(B.biasDirectionText("wtf-bias-right"), "Right-leaning");
  assert.equal(B.biasDirectionText("wtf-bias-centre"), "Centre / Balanced");
  assert.equal(B.biasDirectionText("wtf-bias-unknown"), "Unrated");
});

t("extractDomainFromText resolves X t.co links from the display text (#4671)", () => {
  // X renders the real domain as the link text even though the href is t.co/...
  assert.equal(B.extractDomainFromText("nytimes.com/2024/…"), "nytimes.com");
  assert.equal(B.extractDomainFromText("https://www.cbc.ca/news/canada"), "cbc.ca");
  assert.equal(B.extractDomainFromText("theglobeandmail.com"), "theglobeandmail.com");
  assert.equal(B.extractDomainFromText("nationalpost.com/opinion "), "nationalpost.com");
  // Not a URL → null (don't badge junk text).
  assert.equal(B.extractDomainFromText("Read more"), null);
  assert.equal(B.extractDomainFromText("…"), null);
  assert.equal(B.extractDomainFromText(""), null);
  assert.equal(B.extractDomainFromText(null), null);
  // The shortener set is exported so content.js can detect t.co links.
  assert.ok(B.SHORTENER_DOMAINS.has("t.co"));
});

console.log(`\n${passed}/${passed} tests passed.`);
