"""Skill: price_monitor — Track product/competitor prices over time."""
import logging
import re

logger = logging.getLogger(__name__)

_CURRENCY_RE = re.compile(r"[\$£€¥₹CAD\s]*[\d,]+\.?\d*")


def _parse_price(text: str) -> str:
    text = text.strip()
    match = _CURRENCY_RE.search(text)
    return match.group(0).strip() if match else text


def run(page, url: str, params: dict, job_id: int) -> dict:
    price_sel = params.get("price_selector") or ".price,#price,[class*='price']"
    title_sel = params.get("title_selector") or "h1,[class*='product-title']"
    stock_sel = params.get("stock_selector") or "[class*='stock'],[class*='availability']"
    max_items = int(params.get("max_items") or 10)

    page.goto(url, wait_until="networkidle", timeout=30000)
    price_els = page.query_selector_all(price_sel)[:max_items]
    title_els = page.query_selector_all(title_sel)[:max_items]
    stock_els = page.query_selector_all(stock_sel)[:max_items]

    items = []
    for i in range(max(len(price_els), 1)):
        price_text = price_els[i].inner_text().strip() if i < len(price_els) else ""
        title_text = title_els[i].inner_text().strip() if i < len(title_els) else ""
        stock_text = stock_els[i].inner_text().strip() if i < len(stock_els) else ""
        items.append({
            "title": title_text[:200],
            "price_raw": price_text,
            "price": _parse_price(price_text),
            "in_stock": "out" not in stock_text.lower() if stock_text else None,
            "source": url,
        })

    findings = f"Monitored {len(items)} item(s) from {url}: " + ", ".join(
        f"{i['title'][:20] or 'item'} @ {i['price']}" for i in items[:3]
    )
    return {
        "data": {"items": items, "source": url},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
