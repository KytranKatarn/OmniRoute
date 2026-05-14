"""Skill: contact_harvest — Extract contact information from business site."""
import logging
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

_CONTACT_SCRIPT = r"""() => {
    const text = document.body.innerText;
    const emailRe = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g;
    const phoneRe = /[\+]?[(]?[0-9]{3}[)]?[\s.\-]?[0-9]{3}[\s.\-]?[0-9]{4}/g;
    const emails = [...new Set(text.match(emailRe) || [])].slice(0, 20);
    const phones = [...new Set(text.match(phoneRe) || [])].slice(0, 10);
    const addresses = [];
    document.querySelectorAll('address').forEach(el => { const a = el.textContent.trim(); if (a.length > 10) addresses.push(a.slice(0, 200)); });
    const team = [];
    document.querySelectorAll('[class*="team"],[class*="member"]').forEach(el => {
        const name = el.querySelector('h3,h4,.name')?.textContent?.trim();
        const title = el.querySelector('p,.title')?.textContent?.trim();
        if (name) team.push({name, title});
    });
    return {emails, phones, addresses: [...new Set(addresses)], team: team.slice(0, 20)};
}"""

_CONTACT_PAGES = ["/contact", "/about", "/team", "/contact-us"]


def run(page, url: str, params: dict, job_id: int) -> dict:
    all_data: dict = {"emails": [], "phones": [], "addresses": [], "team": []}
    seen_emails: set = set()

    for page_url in [url] + [urljoin(url, p) for p in _CONTACT_PAGES]:
        try:
            page.goto(page_url, wait_until="networkidle", timeout=20000)
            result = page.evaluate(_CONTACT_SCRIPT)
            for email in result.get("emails", []):
                if email not in seen_emails:
                    seen_emails.add(email)
                    all_data["emails"].append(email)
            for phone in result.get("phones", []):
                if phone not in all_data["phones"]:
                    all_data["phones"].append(phone)
            all_data["addresses"].extend(result.get("addresses", []))
            all_data["team"].extend(result.get("team", []))
        except Exception:
            continue

    all_data["addresses"] = list(dict.fromkeys(all_data["addresses"]))[:10]
    all_data["team"] = all_data["team"][:30]
    findings = f"Harvested {len(all_data['emails'])} emails, {len(all_data['phones'])} phones from {url}"
    return {
        "data": all_data,
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
