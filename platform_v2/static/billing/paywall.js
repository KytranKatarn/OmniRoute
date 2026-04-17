/**
 * kytran-paywall — reusable upgrade overlay for Watch products and any
 * Kytran tier-gated feature. Uses safe DOM methods (createElement +
 * textContent) — no innerHTML anywhere, so untrusted option values
 * can't inject markup.
 *
 * Usage (any browser page):
 *   <link rel="stylesheet" href="https://platform.kytranempowerment.com/static/billing/paywall.css">
 *   <script src="https://platform.kytranempowerment.com/static/billing/paywall.js"></script>
 *   <script>
 *     KytranPaywall.show({
 *       productName: "Legal Watch",
 *       requiredTierSlug: "starter",
 *       requiredTierLabel: "Starter",
 *       currentTierLabel: "Explorer (Free)",
 *       blurb: "Custom alerts and full jurisdictional coverage are included on Starter and above.",
 *       features: [
 *         { label: "Daily news digest",      free: true,  starter: true,  professional: true  },
 *         { label: "All jurisdictions",      free: false, starter: true,  professional: true  },
 *         { label: "Custom alerts",          free: false, starter: true,  professional: true  },
 *         { label: "API access",             free: false, starter: false, professional: true  },
 *         { label: "Team workspaces",        free: false, starter: false, professional: true  }
 *       ],
 *       tiers: [
 *         { key: "free",         label: "Free" },
 *         { key: "starter",      label: "Starter" },
 *         { key: "professional", label: "Pro" }
 *       ],
 *       kbsBaseUrl: "https://business.kytranempowerment.com" // optional
 *     });
 *
 *   // Dismiss programmatically: KytranPaywall.hide();
 */

(function (global) {
    "use strict";

    var DEFAULT_KBS = "https://business.kytranempowerment.com";
    var OVERLAY_ID = "kp-overlay-singleton";

    function _el(tag, className, text) {
        var n = document.createElement(tag);
        if (className) n.className = className;
        if (text != null) n.textContent = String(text);
        return n;
    }

    function _buildCompareTable(opts) {
        var tiers = Array.isArray(opts.tiers) ? opts.tiers : [];
        var features = Array.isArray(opts.features) ? opts.features : [];
        if (!tiers.length || !features.length) return null;

        var table = _el("table", "kp-tier-compare");
        var thead = document.createElement("thead");
        var headRow = document.createElement("tr");
        headRow.appendChild(_el("th", null, "Feature"));
        tiers.forEach(function (t) {
            headRow.appendChild(_el("th", null, t.label));
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        var tbody = document.createElement("tbody");
        features.forEach(function (f) {
            var row = document.createElement("tr");
            row.appendChild(_el("td", null, f.label));
            tiers.forEach(function (t) {
                var has = !!f[t.key];
                var cell = _el("td", has ? "kp-check-yes" : "kp-check-no", has ? "\u2713" : "\u2013");
                row.appendChild(cell);
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        return table;
    }

    function _checkoutUrl(opts) {
        var base = (opts.kbsBaseUrl || DEFAULT_KBS).replace(/\/+$/, "");
        var params = [
            "tier=" + encodeURIComponent(opts.requiredTierSlug || ""),
            "return_url=" + encodeURIComponent(global.location ? global.location.href : "")
        ];
        if (opts.productSlug) {
            params.push("product=" + encodeURIComponent(opts.productSlug));
        }
        return base + "/plugins/billing/checkout?" + params.join("&");
    }

    function show(opts) {
        opts = opts || {};
        hide();

        var overlay = _el("div", "kp-overlay");
        overlay.id = OVERLAY_ID;

        var card = _el("div", "kp-card");

        var productName = opts.productName || "this feature";
        var requiredLabel = opts.requiredTierLabel || opts.requiredTierSlug || "a paid tier";
        var currentLabel = opts.currentTierLabel || "your current plan";
        var blurb =
            opts.blurb ||
            "This feature is included on " +
                requiredLabel +
                " and above. You're on " +
                currentLabel +
                " right now.";
        var dismissLabel = opts.dismissLabel || "Not now";
        var upgradeLabel = opts.upgradeLabel || "Upgrade to " + requiredLabel;

        card.appendChild(_el("div", "kp-eyebrow", productName));
        card.appendChild(_el("h2", "kp-title", "Unlock " + productName));
        card.appendChild(_el("p", "kp-body", blurb));

        var compare = _buildCompareTable(opts);
        if (compare) card.appendChild(compare);

        var actions = _el("div", "kp-actions");
        var dismissBtn = _el("button", "kp-btn kp-btn-secondary", dismissLabel);
        dismissBtn.type = "button";
        dismissBtn.setAttribute("data-kp-dismiss", "");
        actions.appendChild(dismissBtn);

        var upgradeLink = _el("a", "kp-btn kp-btn-primary", upgradeLabel);
        upgradeLink.target = "_blank";
        upgradeLink.rel = "noopener";
        upgradeLink.href = _checkoutUrl(opts);
        actions.appendChild(upgradeLink);

        card.appendChild(actions);
        overlay.appendChild(card);

        overlay.addEventListener("click", function (e) {
            if (e.target === overlay) hide();
        });
        dismissBtn.addEventListener("click", hide);
        document.addEventListener("keydown", _onEsc);

        document.body.appendChild(overlay);
        return overlay;
    }

    function hide() {
        var existing = document.getElementById(OVERLAY_ID);
        if (existing && existing.parentNode) {
            existing.parentNode.removeChild(existing);
        }
        document.removeEventListener("keydown", _onEsc);
    }

    function _onEsc(e) {
        if (e.key === "Escape") hide();
    }

    global.KytranPaywall = {
        show: show,
        hide: hide,
        _buildCompareTable: _buildCompareTable,
        _checkoutUrl: _checkoutUrl
    };
})(typeof window !== "undefined" ? window : this);
