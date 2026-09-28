/* checkout-page.js — real guest checkout. POSTs the cart + shipping info to
 * the live kbs_store guest_checkout endpoint, which creates a Stripe Checkout
 * Session and returns a checkout_url. We redirect the browser there — Stripe's
 * own hosted page collects payment, so no card fields ever touch this site
 * (avoids handling raw card data / PCI scope entirely).
 *
 * success_url/cancel_url are validated server-side against an allowlist that
 * already includes kytranempowerment.com (public_routes.py _safe_redirect_url).
 *
 * Re-invoked on every Barba transition into this page — see app.js initPageScripts().
 */
var CheckoutPage = (function () {
    'use strict';

    var API_BASE = 'https://business.kytranempowerment.com/plugins/store/public';
    var SUCCESS_URL = 'https://kytranempowerment.com/order-success.html';
    var CANCEL_URL = 'https://kytranempowerment.com/cart.html';

    function renderSummary() {
        var cart = KECart.getCart();
        var itemsContainer = document.getElementById('order-summary-items');
        var emptyMsg = document.getElementById('summary-empty-message');
        var subtotalEl = document.getElementById('summary-subtotal');
        var totalEl = document.getElementById('summary-total');
        var placeOrderButton = document.getElementById('place-order-button');
        if (!itemsContainer) return cart;

        itemsContainer.textContent = '';

        if (cart.length === 0) {
            if (emptyMsg) emptyMsg.style.display = 'block';
            if (placeOrderButton) placeOrderButton.disabled = true;
            if (subtotalEl) subtotalEl.textContent = '$0.00';
            if (totalEl) totalEl.textContent = '$0.00';
            return cart;
        }

        if (emptyMsg) emptyMsg.style.display = 'none';
        if (placeOrderButton) placeOrderButton.disabled = false;

        var frag = document.createDocumentFragment();
        cart.forEach(function (item) {
            var row = document.createElement('div');
            row.className = 'order-item-summary';
            var nameSpan = document.createElement('span');
            nameSpan.textContent = item.name + ' × ' + item.qty;
            var priceSpan = document.createElement('span');
            priceSpan.textContent = '$' + (item.qty * item.price).toFixed(2);
            row.appendChild(nameSpan);
            row.appendChild(priceSpan);
            frag.appendChild(row);
        });
        itemsContainer.appendChild(frag);

        var total = KECart.cartTotal(cart);
        if (subtotalEl) subtotalEl.textContent = '$' + total.toFixed(2);
        if (totalEl) totalEl.textContent = '$' + total.toFixed(2);

        return cart;
    }

    function handleSubmit(event) {
        event.preventDefault();

        var form = document.getElementById('checkout-form');
        var placeOrderButton = document.getElementById('place-order-button');
        var loadingMsg = document.getElementById('checkout-loading-message');
        var errorMsg = document.getElementById('checkout-error-message');
        var cart = KECart.getCart();

        if (errorMsg) { errorMsg.style.display = 'none'; errorMsg.textContent = ''; }

        if (cart.length === 0) {
            if (errorMsg) { errorMsg.style.display = 'block'; errorMsg.textContent = 'Your cart is empty.'; }
            return;
        }

        var formData = new FormData(form);
        var data = Object.fromEntries(formData.entries());

        var payload = {
            email: data.email,
            name: data.fullName,
            items: cart.map(function (item) { return { product_id: item.id, quantity: item.qty }; }),
            shipping_address: {
                address1: data.address1,
                address2: data.address2 || '',
                city: data.city,
                state: data.state,
                zip: data.zip,
                country: data.country,
                phone: data.phone || ''
            },
            success_url: SUCCESS_URL,
            cancel_url: CANCEL_URL
        };

        if (placeOrderButton) { placeOrderButton.disabled = true; placeOrderButton.classList.add('disabled'); }
        if (loadingMsg) loadingMsg.style.display = 'block';

        fetch(API_BASE + '/checkout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (response) {
                return response.json().then(function (result) {
                    if (!response.ok) throw new Error(result.error || 'HTTP ' + response.status);
                    return result;
                });
            })
            .then(function (result) {
                if (!result.checkout_url) throw new Error('No checkout URL returned.');
                window.location.href = result.checkout_url;
            })
            .catch(function (err) {
                console.error('Checkout error:', err);
                if (loadingMsg) loadingMsg.style.display = 'none';
                if (errorMsg) { errorMsg.style.display = 'block'; errorMsg.textContent = 'Checkout failed: ' + err.message; }
                if (placeOrderButton) { placeOrderButton.disabled = false; placeOrderButton.classList.remove('disabled'); }
            });
    }

    function init() {
        renderSummary();
        KECart.updateCartBadges();

        var form = document.getElementById('checkout-form');
        if (form) form.addEventListener('submit', handleSubmit);
    }

    return { init: init };
})();
