"""LinkedIn group join — request to join a group (or confirm already a member).

A group requiring approval shows an "Ask to join" / "Request to join" CTA; an
open group shows "Join". After clicking, an approval group flips to
"Pending"/"Requested"; an open group flips to member (composer / "Leave group").

Honesty-gated: success is reported ONLY when the post-click page state confirms
the request landed (Pending/Requested/Withdraw) or membership (Leave group /
composer). A bare button click that doesn't change state => click_unverified.

Params: group_id (required, the numeric id from linkedin.com/groups/<id>/)
Returns: {success, result, group_id} where result is one of
  already_member | request_pending | request_sent | join_button_not_found |
  click_unverified
"""

SKILL_NAME = "linkedin_group_join"
PLATFORMS = ["linkedin"]
MUTATING = True


def _body_text(page) -> str:
    try:
        return (page.evaluate("() => document.body.innerText || ''") or "")
    except Exception:
        return ""


def _has_any(text: str, needles) -> bool:
    low = text.lower()
    return any(n.lower() in low for n in needles)


def execute(page, params: dict) -> dict:
    group_id = str(params.get("group_id", "")).strip()
    if not group_id:
        raise ValueError("group_id is required")

    url = f"https://www.linkedin.com/groups/{group_id}/"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(3500)

    text = _body_text(page)

    # Already a member? (composer present, or member-only chrome)
    member_markers = ["Leave group", "You're a member", "Share what you", "Start a post"]
    if _has_any(text, member_markers):
        return {"success": True, "result": "already_member", "group_id": group_id}
    try:
        if page.get_by_text("Start a post", exact=False).first.is_visible(timeout=1500):
            return {"success": True, "result": "already_member", "group_id": group_id}
    except Exception:
        pass

    # Request already pending?
    if _has_any(text, ["Pending", "Requested", "Withdraw request"]):
        return {"success": True, "result": "request_pending", "group_id": group_id}

    # Click the join CTA. An INVITED user sees a standalone "Accept" button
    # (screenshot-proven on 342, 2026-07-02) — try that first. Then the explicit
    # approval-CTAs; "Join" exact only as a last resort (the recommended-groups
    # rail renders "Join <other group>").
    clicked = False
    for fn in [
        lambda: page.get_by_role("button", name="Accept", exact=False).first.click(timeout=5000),
        lambda: page.get_by_text("Accept", exact=True).first.click(timeout=4000),
        lambda: page.get_by_role("button", name="Ask to join", exact=False).first.click(timeout=6000),
        lambda: page.get_by_role("button", name="Request to join", exact=False).first.click(timeout=6000),
        lambda: page.get_by_role("button", name="Join", exact=True).first.click(timeout=6000),
        lambda: page.get_by_text("Ask to join", exact=False).first.click(timeout=4000),
    ]:
        try:
            fn()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        return {"success": False, "result": "join_button_not_found", "group_id": group_id}

    page.wait_for_timeout(2800)
    after = _body_text(page)
    confirmed = _has_any(
        after,
        ["Pending", "Requested", "Withdraw", "You're a member", "Leave group"],
    )
    if not confirmed:
        # Accepting an INVITE grants membership instantly server-side, but the
        # member chrome (composer / Leave group) only renders after a reload
        # (proven live 2026-07-02: click_unverified, then already_member on
        # the next fresh load).
        try:
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            confirmed = _has_any(
                _body_text(page),
                ["Pending", "Requested", "Withdraw", "You're a member",
                 "Leave group", "Start a post"],
            )
        except Exception:
            pass
    return {
        "success": bool(confirmed),
        "result": "request_sent" if confirmed else "click_unverified",
        "group_id": group_id,
    }
