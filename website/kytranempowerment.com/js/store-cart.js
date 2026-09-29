/* store-cart.js — shared localStorage cart for the Kytran Empowerment store
 * Cart holds { id, name, price, image, qty } keyed to real product IDs from
 * the live kbs_store public API (business.kytranempowerment.com/plugins/store/public).
 * No server-side cart — the whole cart is posted in one shot at checkout.
 */
var KECart = (function () {
    'use strict';

    var STORAGE_KEY = 'ke-cart';
    var API_ORIGIN = 'https://business.kytranempowerment.com';

    /* via.placeholder.com has been dead since 2023 — an inline SVG never
     * depends on a network call, so "no image" always renders something. */
    var PLACEHOLDER_IMAGE = 'data:image/svg+xml,' + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">' +
        '<rect width="100%" height="100%" fill="#1a1a2e"/>' +
        '<text x="50%" y="50%" fill="#666" font-family="sans-serif" font-size="18" ' +
        'text-anchor="middle" dominant-baseline="middle">No Image</text></svg>'
    );

    /* The public product API returns image paths relative to its own origin
     * (e.g. "/static/store/placeholder-tee.jpg") — set directly as <img src>
     * on kytranempowerment.com they'd resolve against the WRONG origin. */
    function resolveImageUrl(url) {
        if (!url) return '';
        if (/^https?:\/\//i.test(url)) return url;
        return API_ORIGIN + (url.charAt(0) === '/' ? url : '/' + url);
    }

    /* product.images[0] is NOT a stable shape across sources: locally-seeded
     * products store {url, alt} objects, Printful-synced products store bare
     * URL strings (that's what Printful's own thumbnail_url is). Handle both
     * rather than assuming one — this is the actual live API contract, not
     * a hypothetical. */
    function getProductImageUrl(product) {
        var imgs = product && product.images;
        if (Array.isArray(imgs) && imgs.length > 0) {
            var first = imgs[0];
            var raw = (typeof first === 'string') ? first : (first && first.url);
            if (raw) return resolveImageUrl(raw);
        }
        return PLACEHOLDER_IMAGE;
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
        /* Same-tab notice for the shared sitewide nav badge (nav.js), which
         * reads localStorage directly and doesn't require KECart to be
         * loaded on every page — this event is just its instant-update hook. */
        try {
            window.dispatchEvent(new CustomEvent('ke:cart-changed', { detail: { count: count } }));
        } catch (e) {}
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
        resolveImageUrl: resolveImageUrl,
        getProductImageUrl: getProductImageUrl,
        PLACEHOLDER_IMAGE: PLACEHOLDER_IMAGE
    };
})();
