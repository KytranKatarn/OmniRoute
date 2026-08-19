# What The Fact — Bias Ratings (Browser Extension)

A Chrome (MV3) extension that shows **What The Fact** bias ratings as a small coloured dot
next to Canadian-news links while you browse social media.

- 🔵 **Left-leaning** · ⚪ **Centre / Balanced** · 🔴 **Right-leaning** · 🟡 **Unrated**
- Hover a dot for the outlet name, WTF bias band, and score.
- Active on: **X/Twitter · Facebook · LinkedIn · Reddit**.

Bias data comes live from WTF's public, CORS-open API
(`https://what-the-fact.com/api/edu/v1/sources`) and is cached locally for 6 hours.

## Install (load unpacked — Chrome / Edge / Brave)

1. Open `chrome://extensions`.
2. Toggle **Developer mode** (top-right) on.
3. Click **Load unpacked** and select this `extension/` folder.
4. Browse X/Reddit/etc. — dots appear next to links pointing at rated Canadian outlets.

## Packaging

**Never zip this folder by hand.** Build it:

```bash
python3 build.py            # writes wtf-bias-extension.zip
python3 build.py --check    # exit 1 if the zip on disk is stale; writes nothing
```

The payload is read out of `manifest.json`, so a newly referenced script, stylesheet
or icon is picked up automatically and can never be left out of the package (Chrome
rejects the whole extension over one missing file). `tests/`, this README and the zip
itself are unreachable from the manifest and so are excluded by construction.

The archive is byte-reproducible — same sources in, identical file out — which is what
lets `--check` and `tests/test_extension_package.py` answer "is this current?" by
comparison instead of by trusting a modification time.

> A hand-built zip drifted 9 days behind source for six weeks (task #5752) and was
> missing the #4671 X/Twitter fix. Uploading it would have shipped an extension that
> badges nothing on X — it loads fine and silently does nothing, so a store review
> would not have caught it.

## How it works

- `bias-logic.js` — pure logic (domain parsing, bias mapping, lookups). Loaded first; also
  unit-tested in Node.
- `content.js` — scans page links (`a[href]`), matches their domain to a rated outlet, and
  injects the badge. A debounced `MutationObserver` re-scans as SPAs load new content.
- `background.js` — refreshes the outlet cache every 6 hours (`alarms` permission).
- Bias precedence: WTF's computed **`band`** → `bias_lean` → numeric `avg_score` bucket.

## Known limitations (v0.1.0)

- **X/Twitter `t.co` wrapping:** X rewrites external links to `t.co/…` in the `href`, so those
  links can't be domain-matched until X exposes the real URL. Badges appear reliably where the
  `href` is the real outlet domain (much of Reddit/Facebook/direct links). Resolving `t.co`
  redirects is a follow-up.
- **Chrome only** for now — Firefox (MV3 differences) is a follow-up.
- **Coverage:** the 46 Canadian outlets WTF currently rates (grows automatically as WTF adds
  outlets — no extension update needed).

## Development / tests

```bash
# Unit tests (pure logic):
node tests/bias-logic.test.js

# Real-DOM test: serve this folder and open tests/dom-test.html in a browser —
# it loads the real bias-logic.js + content.js with chrome/fetch stubbed and
# badges two sample links (see the page for expected results).
python3 -m http.server 8899   # then visit http://localhost:8899/tests/dom-test.html
```

`tests/` is for development only and is excluded from the packaged `.zip`.
