/* cart-page.js — renders the localStorage cart on cart.html: qty adjust,
 * remove, subtotal. No backend call — the cart only becomes a real order
 * at checkout (see checkout-page.js). Re-invoked on every Barba transition
 * into this page — see app.js initPageScripts().
 */
var CartPage = (function () {
    'use strict';

    function buildCartItemElement(item) {
        var itemTotal = item.qty * item.price;

        var row = document.createElement('div');
        row.className = 'cart-item';

        var img = document.createElement('img');
        img.src = item.image || 'https://via.placeholder.com/90x90?text=No+Image';
        img.alt = item.name;
        img.className = 'cart-item-image';
        row.appendChild(img);

        var details = document.createElement('div');
        details.className = 'cart-item-details';
        var h3 = document.createElement('h3');
        h3.textContent = item.name;
        details.appendChild(h3);
        var pPrice = document.createElement('p');
        pPrice.textContent = '$' + item.price.toFixed(2) + ' each';
        details.appendChild(pPrice);
        row.appendChild(details);

        var qtyWrap = document.createElement('div');
        qtyWrap.className = 'cart-item-quantity';

        var btnMinus = document.createElement('button');
        btnMinus.className = 'cart-qty-btn';
        btnMinus.textContent = '−';
        btnMinus.setAttribute('aria-label', 'Decrease quantity');
        btnMinus.addEventListener('click', function () {
            KECart.updateQty(item.id, item.qty - 1);
            renderCart();
        });
        qtyWrap.appendChild(btnMinus);

        var qtyVal = document.createElement('span');
        qtyVal.className = 'cart-qty-value';
        qtyVal.textContent = String(item.qty);
        qtyWrap.appendChild(qtyVal);

        var btnPlus = document.createElement('button');
        btnPlus.className = 'cart-qty-btn';
        btnPlus.textContent = '+';
        btnPlus.setAttribute('aria-label', 'Increase quantity');
        btnPlus.addEventListener('click', function () {
            KECart.updateQty(item.id, item.qty + 1);
            renderCart();
        });
        qtyWrap.appendChild(btnPlus);
        row.appendChild(qtyWrap);

        var priceEl = document.createElement('div');
        priceEl.className = 'cart-item-price';
        priceEl.textContent = '$' + itemTotal.toFixed(2);
        row.appendChild(priceEl);

        var removeBtn = document.createElement('button');
        removeBtn.className = 'cart-item-remove';
        removeBtn.textContent = 'Remove';
        removeBtn.addEventListener('click', function () {
            KECart.removeFromCart(item.id);
            renderCart();
        });
        row.appendChild(removeBtn);

        return row;
    }

    function renderCart() {
        var container = document.getElementById('cart-items-container');
        var loading = document.getElementById('cart-loading-message');
        var empty = document.getElementById('cart-empty-message');
        var summary = document.getElementById('cart-summary');
        var actions = document.getElementById('cart-actions');
        if (!container) return;

        if (loading) loading.style.display = 'none';
        container.textContent = '';

        var cart = KECart.getCart();

        if (cart.length === 0) {
            if (empty) empty.style.display = 'block';
            if (summary) summary.style.display = 'none';
            if (actions) actions.style.display = 'none';
            return;
        }

        if (empty) empty.style.display = 'none';

        var frag = document.createDocumentFragment();
        cart.forEach(function (item) { frag.appendChild(buildCartItemElement(item)); });
        container.appendChild(frag);

        var total = KECart.cartTotal(cart);
        var subtotalEl = document.getElementById('cart-subtotal');
        var totalEl = document.getElementById('cart-total');
        if (subtotalEl) subtotalEl.textContent = '$' + total.toFixed(2);
        if (totalEl) totalEl.textContent = '$' + total.toFixed(2);

        if (summary) summary.style.display = 'flex';
        if (actions) actions.style.display = 'flex';
    }

    function init() {
        renderCart();
        KECart.updateCartBadges();
    }

    return { init: init };
})();
