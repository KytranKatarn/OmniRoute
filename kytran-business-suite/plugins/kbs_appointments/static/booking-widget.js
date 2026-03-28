/**
 * Kytran Business Suite — Embeddable Booking Widget
 *
 * Usage:
 *   <div id="kbs-booking"></div>
 *   <script src="https://book.kytranempowerment.com/static/appointments_public/booking-widget.js"
 *           data-slug="your-business-slug"
 *           data-accent="#00e5ff"
 *           data-width="100%"
 *           data-height="700px">
 *   </script>
 *
 * Or programmatically:
 *   KBSBooking.init({ slug: 'your-slug', target: '#my-container' });
 */
(function () {
    "use strict";

    var BOOKING_HOST = "https://book.kytranempowerment.com";

    function getScriptData() {
        var scripts = document.getElementsByTagName("script");
        var current = scripts[scripts.length - 1];
        return {
            slug: current.getAttribute("data-slug") || "",
            accent: current.getAttribute("data-accent") || "#00e5ff",
            width: current.getAttribute("data-width") || "100%",
            height: current.getAttribute("data-height") || "700px",
            target: current.getAttribute("data-target") || "kbs-booking",
        };
    }

    function createIframe(config) {
        var container = document.getElementById(config.target);
        if (!container) {
            console.error("[KBS Booking] Target element #" + config.target + " not found.");
            return;
        }

        if (!config.slug) {
            console.error("[KBS Booking] data-slug attribute is required.");
            return;
        }

        var iframe = document.createElement("iframe");
        iframe.src = BOOKING_HOST + "/" + config.slug + "?embed=1";
        iframe.style.width = config.width;
        iframe.style.height = config.height;
        iframe.style.border = "none";
        iframe.style.borderRadius = "8px";
        iframe.style.overflow = "hidden";
        iframe.setAttribute("loading", "lazy");
        iframe.setAttribute("title", "Book an appointment");
        iframe.setAttribute("allow", "payment");

        container.appendChild(iframe);

        // Listen for resize messages from the iframe
        window.addEventListener("message", function (e) {
            if (e.data && e.data.type === "kbs-booking-resize") {
                iframe.style.height = e.data.height + "px";
            }
        });
    }

    // Auto-initialize when script is loaded with data attributes
    var config = getScriptData();
    if (config.slug) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", function () {
                createIframe(config);
            });
        } else {
            createIframe(config);
        }
    }

    // Expose public API
    window.KBSBooking = {
        init: function (opts) {
            createIframe({
                slug: opts.slug || "",
                accent: opts.accent || "#00e5ff",
                width: opts.width || "100%",
                height: opts.height || "700px",
                target: (opts.target || "#kbs-booking").replace("#", ""),
            });
        },
    };
})();
