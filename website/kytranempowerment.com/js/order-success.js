/* order-success.js — landing page after a completed Stripe Checkout redirect.
 * Payment already happened on Stripe's own hosted page before the browser
 * gets here, so this page needs no order lookup — it just clears the local
 * cart and shows a static confirmation, matching the Design handoff intent.
 * Re-invoked on every Barba transition into this page — see app.js initPageScripts().
 */
var OrderSuccess = (function () {
    'use strict';

    function init() {
        KECart.setCart([]);
    }

    return { init: init };
})();
