# Phase 5 — TTY lanes in the cockpit

**Status:** design, awaiting owner review
**Date:** 2026-09-10
**Program:** master-command interface, project #343. Build order slice 5, after 4a (Crew + Code Builder) and 4b (Work pane + Apply), both live.
**Owner decisions recorded in this document:** four, marked ⓞ.

---

## 1. What this builds

A fifth pane, **Terminal**, in the cockpit at `archie.kytranempowerment.com/cockpit`. It shows the coder lanes that already exist on this host and lets the owner work in them without leaving the cockpit.

ⓞ **The terminal is embedded in the page, not a link out.**

ⓞ **The pane appears at every width, as a fifth tab** — desktop and phone. A terminal at 390px is cramped, but being able to see what a running session is doing from a phone is worth more than the tidiness of a four-tab bar.

## 2. The lanes — two, not three

Prior notes described three coder lanes (claude, codex, engine). Measured on the host, only two are terminals:

| lane | what it is | backend | gate |
|---|---|---|---|
| **claude** | the real `claude` CLI running **on the host** as user `kytran`, inside tmux session `claude-code`. No container boundary. No viewer cap, so it is already the "one shared session" the original directive asked for. | ttyd `127.0.0.1:17681` | `ttyd_auth_proxy.py` on `:7681` |
| **codex** | `codex` running **inside a container** (`archie_codex_terminal`), `--max-clients 1`, own volumes, scoped tokens, on a bridge network with no reach to any platform container. | ttyd `127.0.0.1:17682` | a second instance of the same proxy on `:7683` |

**The engine is not a lane.** `archie_engine` publishes only `127.0.0.1:9090`, a websocket API with bearer auth — there is no shell behind it. It is excluded, and this document says so explicitly so nobody re-adds it from the old three-lane note.

The two lanes have **very different blast radii** and the pane must not imply otherwise: codex is a sandbox, claude is the host. §6 covers how that is surfaced.

## 3. Authentication — the proxy stays the only gate

ⓞ **The cockpit mints a one-time token; the pane points at the existing proxy.** The cockpit never proxies terminal bytes and never becomes a second gate for shell access.

The reason this shape was chosen: the cockpit never becomes a second gate for shell access. Terminal bytes flow browser → proxy → ttyd; the cockpit's only involvement is minting a token.

> **Correction, recorded because it drove a decision.** An earlier draft of this section claimed the cockpit's `_require_session` admits *any logged-in comms user* while the proxies require an admin, and framed embedding as widening access. **That was wrong.** `archie-comms/app_comms.py:131` rejects any SSO login whose `role != "admin"` — it discards the session and redirects to `/login` — and `session["user_id"]` is set in exactly one place (`:141`), inside that accepted path. There is no other session-establishing path and no dev bypass. So every logged-in comms user is already an admin and the cockpit gate has been admin-equivalent all along.
>
> The claim came from reading the cockpit's session helper without reading the login path that fills the session. The design is unchanged — pointing at the proxy is still right, because it avoids inventing a second gate — but the *risk* of embedding is smaller than first stated: the people who can reach the cockpit today are the same people who can already reach the terminal.

### 3.1 A correction found by testing, not by reading

The one-time token path already exists (`terminal_auth_tokens`, `validate_token()`), and **as it stands it authenticates exactly one request**. Measured against the live proxy:

| request | result |
|---|---|
| first, with `?token=…` | HTTP 200, row immediately flipped `used = true` |
| second, same token | HTTP 401, Basic challenge |
| an asset, no token | HTTP 401, Basic challenge |

A ttyd page is not one request — it is the document, then its scripts and styles, then a websocket upgrade. Auth in `ttyd_auth_proxy.py` is **per connection with no cookie handling at all**, so only the first would succeed and the pane would sit empty or prompt for a password inside the cockpit.

### 3.2 The addition

On a **valid token**, the proxy sets a short-lived signed cookie and accepts that cookie on subsequent connections. Everything else about the proxy is unchanged.

- ⓞ **Lifetime: 15 minutes, sliding.** It renews while the terminal is in use and lapses quickly once idle. Invisible during real work; a stolen cookie is short-lived.
- Cookie is `HttpOnly`, `Path=/`, `Secure`, `SameSite=None`, and signed with a host-side secret (never in the repo). **See the correction in §11.3 — an earlier draft said `SameSite=Strict` and *not* `Secure`, which would have made the cookie undeliverable in the very iframe it exists for.**
- The existing Basic Auth fallback stays. It is how the terminal is reached outside the cockpit today.
- Token minting stays one-time. The cookie, not the token, carries the session.

### 3.3 The mint route must be admin-gated

`POST /api/cockpit/terminal/<lane>/token` returns `{token, expires_at}`.

**It checks `session["role"] == "admin"` explicitly, in addition to `_require_session`.** Today that is redundant — see the correction in §3 — and it is required anyway, for two reasons. First, the proxy validates a token without knowing who requested it, so the mint step is where the requester's authority is established. Second, and the real point: without an explicit check the terminal's protection would rest on a property of the SSO login path rather than on anything the terminal code states. A future change admitting non-admins to comms for some unrelated feature would silently hand out shells. The check makes the requirement local and visible.

Rate-limited per user, and every mint is logged with the requesting user id and lane.

## 4. Data flow

```
cockpit pane (admin)                    hub                      ttyd proxy            ttyd
   |  POST /api/cockpit/terminal/claude/token
   |------------------------------------>|  (admin check, insert row)
   |<-- {token, expires_at} -------------|
   |
   |  iframe src = https://terminal.kytranempowerment.com/?token=…   (§11.2)
   |------------------------------------------------------------>|  validate + consume
   |                                                              |  Set-Cookie (15 min)
   |<------------------------------------------------------------ 200 + page
   |  assets, then websocket, carrying the cookie
   |------------------------------------------------------------>|  cookie accepted
   |                                                              |------------------->|
```

## 5. Cockpit surface

- `cockpit_routes.py`: 19 rules → 21. One mint route, one lane-status route.
- `GET /api/cockpit/terminal/lanes` → per lane: `{lane, label, reachable, sandboxed, busy}`. `reachable` is a real probe of the proxy, not a guess. `busy` covers codex's single seat.
- `services/cockpit_proxy.py`: a status helper only. **No terminal bytes pass through the proxy module** — it stays the JSON pass-through it is today.
- Template: a fifth `<section id="pane-terminal">` plus a lane switcher. The pane holds an iframe per lane, only the selected one mounted.
- The Phase 4b layout invariant extends: `#pane-terminal` must be `display: none` by default in the desktop block, the way `#pane-work` is, so a stale tab flag cannot put two panes in one grid cell after a resize. The existing structural CSS test is extended to cover it.

## 6. What the owner sees when things are wrong

Every state below is explicit text, never a blank frame:

| state | shown |
|---|---|
| lane proxy unreachable | "claude lane is not responding" + when it was last reachable |
| codex seat taken | "codex allows one viewer and someone is attached" |
| session lapsed | an inline "reconnect" control that mints a fresh token; no silent reload |
| mint refused (not admin) | "a terminal needs an admin account" — the honest reason, not a generic error |
| tmux session absent | the lane reports it rather than showing an empty terminal |

The **claude lane carries a persistent marker that it is the host, not a sandbox**, next to the codex lane's sandbox marker. The two look identical otherwise and the difference matters more than any other label on the page.

## 7. Testing

Static tests cover: the two new rules exist and the mint route rejects a non-admin session; the lane list shape; the CSS invariant. These are text and route assertions and are honest about their reach — they cannot show that a terminal renders.

**The live drive is the proof**, and it is the only thing that settles this phase:

1. A non-admin cockpit session cannot mint a token.
2. A minted token loads the pane **and its assets and its websocket** — the failure §3.1 documents.
3. Typing in the pane reaches the shared session, and the same session is visible from the standalone terminal URL.
4. The session lapses after 15 idle minutes and the reconnect control recovers it.
5. Codex reports its seat as busy when it is.
6. Both widths: 390 and 1280, exactly one pane visible, no horizontal scroll.

## 8. Prerequisites — done before this design was written

All three were found while gathering context for this phase, and all are already merged:

- **The claude ttyd was bound to every interface**, publishing a writable terminal attached to the shared session on `0.0.0.0:17681` with no credentials, bypassing its own proxy. Rebound to loopback and verified: LAN refuses, loopback serves, proxy still gates. (#3282, `1c10ccc4e`; KB #314310.)
- **A dead plaintext credential** in a tracked systemd unit, removed after proving it matched no live account. (#3283, `d2bb174a1`.)
- **`claude_proxy.py` on `:7682`** accepted an unauthenticated POST and ran `claude -p --dangerously-skip-permissions` as the host user — unauthenticated action on the host, not merely subscription abuse. ⓞ Fixed now with a shared-secret header. (branch `fix/claude-proxy-auth`.)

The pattern across all three: **prose describing a protection the code did not implement.** The ttyd script said "localhost" in three places while binding to everything. This is the same family as Phase 4b's deny-status bug and is why §3.1 exists — the token mechanism was verified by driving it rather than by reading its docstring.

## 9. Explicitly out of scope

- Containerising the claude lane. It would bound the blast radius, but it is not the shared session the owner works in, and swapping that is a separate decision.
- Retiring the standalone terminal hostnames. The pane is an addition.
- Any engine "lane". §2.
- Multi-user terminals. One owner, one shared claude session, codex single-seat.

## 10. Open question for review

The claude lane is a **host shell with no container boundary**, now one tab away inside a page that is already open.

Access does not widen: per §3, comms admits only admins, and those are exactly the people who can already open the terminal directly. What changes is *convenience* — a host shell becomes markedly easier to reach, and convenience is how a boundary erodes.

**Owner reviewed and accepted this as written** (2026-09-10), including embedding the claude lane. Recorded here so a later reader sees it was a decision rather than an oversight. The alternative, still available later, is to embed only the sandboxed codex lane and keep claude a link-out.

---

## 11. Corrections found while writing the plan (2026-09-10)

Four things this document asserted or assumed did not survive measurement against the
running host. The design shape is unchanged — embed both lanes, point at the existing
proxy, mint a token — but these four details are load-bearing and three of them would
have shipped a broken or unsafe pane. Recorded here rather than silently edited, in
keeping with §3 and §3.1.

### 11.1 The mint route already exists — do not build a second one

`POST /api/terminal/token` already lives at `archie-comms/app_comms.py:1243`. It inserts
into `terminal_auth_tokens` with a 5-minute expiry and is already consumed by a working
terminal drawer (`TerminalDrawer._loadIframe` in `static/js/archie-chat.js`).

§5 proposed a *new* `POST /api/cockpit/terminal/<lane>/token`. Two minting routes with
different gates is precisely the "second gate" §3 exists to avoid. **The plan extends the
existing route through one shared helper** rather than adding a parallel path.

Its current gate is `session["user_id"]` only — it has **no explicit admin check**, so the
requirement §3.3 argues for is genuinely absent today, not merely redundant. Adding it is a
real change, not a formality.

### 11.2 The lane URL is a public HTTPS host, not `http://<host>:7681`

The existing route returns `https://terminal.kytranempowerment.com?token=…`, fronted by
Citadel's ingress. §4's `http://<host>:7681` was wrong, and the difference decides §11.3.
The codex lane's counterpart hostname must be confirmed against the live Caddyfile at
implementation time; the proxy itself is on `:7683`.

### 11.3 The cookie attributes in §3.2 were wrong in both directions

`SameSite` is evaluated against the **top-level site**, not the iframe's origin. The owner
reaches the cockpit at `http://192.168.1.200:3002` (a bare IP is its own site), while the
terminal is `terminal.kytranempowerment.com`. That is a **cross-site** iframe, so a
`Strict` — or `Lax` — cookie is never sent, and the pane fails exactly the way §3.1
predicts, for an entirely different reason. `Secure` was also declined on a false premise:
the embed path is HTTPS, so `Secure` costs nothing there.

Corrected: **`Secure; SameSite=None`**, which is the only combination a cross-site iframe
will carry.

⚠️ **`SameSite=None` must not ship alone.** It means any site can embed the terminal and
have the browser attach the cookie. It is paired with a **`Content-Security-Policy:
frame-ancestors` allowlist** on the proxy's responses, restricting embedding to the cockpit
origins. The cookie says who you are; `frame-ancestors` says who may ask on your behalf.

The plain-HTTP LAN route (`http://192.168.1.200:7681`) cannot carry a `Secure` cookie and
deliberately keeps the Basic Auth fallback §3.2 already preserves.

### 11.4 A token is not bound to a lane — a sandbox token opens the host shell

**Severity, stated precisely — an earlier draft of this section overstated it.**
The only mint path is `/api/terminal/token`, which requires `session["user_id"]`, and that
key is set in exactly one place: the branch of the SSO login that has already rejected
`role != "admin"` (`app_comms.py:131`). So **every token holder is already an admin, and an
admin can open the claude lane directly anyway** — via the same route, or by Basic Auth at
the proxy. The gap therefore grants access to **nobody who does not already have it**.

It is a least-privilege / defence-in-depth failure, not a privilege escalation — and it
becomes load-bearing the moment the pane starts *asserting* that codex is sandboxed (§6),
because that label would then be false. Fix it as Task 1, before the pane makes the claim;
it does not warrant an out-of-band emergency fix tonight.

`terminal_auth_tokens` has columns
`id, user_id, token, created_at, expires_at, used` — and **no lane**. Both proxies run the
same `scripts/ttyd_auth_proxy.py` against the same table, differing only in
`PROXY_PORT`/`TTYD_PORT`. Nothing binds a token to the lane it was minted for.

So a token minted for **codex** — the sandboxed lane — is accepted by the **claude** proxy,
which is the host shell with no container boundary, and the reverse. §2 calls the two lanes'
blast radii "very different" and §6 makes the host/sandbox marker the most important label
on the page; an unbound token silently defeats both.

The plan adds a `lane` column, a `PROXY_LANE` env per proxy instance, and an exact-match
check that **fails closed on a NULL or mismatched lane**. Existing rows are one-time and
five-minute-lived, so failing closed on legacy NULLs costs nothing.
