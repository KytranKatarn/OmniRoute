/* store-cart.js — shared localStorage cart for the Kytran Empowerment store
 * Cart holds { id, name, price, image, qty } keyed to real product IDs from
 * the live kbs_store public API (business.kytranempowerment.com/plugins/store/public).
 * No server-side cart — the whole cart is posted in one shot at checkout.
 */
var KECart = (function () {
    'use strict';

    var STORAGE_KEY = 'ke-cart';
    var API_ORIGIN = 'https://business.kytranempowerment.com';

    /* The public product API returns image paths relative to its own origin
     * (e.g. "/static/store/placeholder-tee.jpg") — set directly as <img src>
     * on kytranempowerment.com they'd resolve against the WRONG origin. */
    function resolveImageUrl(url) {
        if (!url) return '';
        if (/^https?:\/\//i.test(url)) return url;
        return API_ORIGIN + (url.charAt(0) === '/' ? url : '/' + url);
    }

    function getCart() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            var parsed = raw ? JSON.parse(raw) : [];
            return Array.isArray(parsed) ? parsed : [];
        } catch (e) {
            return [];
        }
    }

    function setCart(items) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
        } catch (e) {
            console.error('KECart: failed to persist cart', e);
        }
        updateCartBadges(items);
        return items;
    }

    function addToCart(product, qty) {
        qty = qty || 1;
        var cart = getCart();
        var existing = null;
        for (var i = 0; i < cart.length; i++) {
            if (cart[i].id === product.id) { existing = cart[i]; break; }
        }
        if (existing) {
            existing.qty += qty;
        } else {
            cart.push({
                id: product.id,
                name: product.name,
                price: parseFloat(product.price),
                image: product.image || '',
                qty: qty
            });
        }
        return setCart(cart);
    }

    function removeFromCart(id) {
        var cart = getCart().filter(function (item) { return item.id !== id; });
        return setCart(cart);
    }

    function updateQty(id, qty) {
        qty = Math.max(1, qty);
        var cart = getCart().map(function (item) {
            if (item.id !== id) return item;
            return { id: item.id, name: item.name, price: item.price, image: item.image, qty: qty };
        });
        return setCart(cart);
    }

    function cartCount(cart) {
        cart = cart || getCart();
        return cart.reduce(function (t, item) { return t + item.qty; }, 0);
    }

    function cartTotal(cart) {
        cart = cart || getCart();
        return cart.reduce(function (t, item) { return t + item.qty * item.price; }, 0);
    }

    function updateCartBadges(cart) {
        var count = cartCount(cart);
        var els = document.querySelectorAll('[data-cart-count]');
        for (var i = 0; i < els.length; i++) els[i].textContent = String(count);
    }

    return {
        getCart: getCart,
        setCart: setCart,
        addToCart: addToCart,
        removeFromCart: removeFromCart,
        updateQty: updateQty,
        cartCount: cartCount,
        cartTotal: cartTotal,
        updateCartBadges: updateCartBadges,
        resolveImageUrl: resolveImageUrl
    };
})();
