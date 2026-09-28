/* store.js — Store grid page. Fetches the live public product catalog from
 * business.kytranempowerment.com/plugins/store/public/products (CORS already
 * scoped to kytranempowerment.com server-side) and renders product cards.
 * Re-invoked on every Barba transition into this page — see app.js initPageScripts().
 */
var Store = (function () {
    'use strict';

    var API_BASE = 'https://business.kytranempowerment.com/plugins/store/public';

    function esc(str) {
        var div = document.createElement('div');
        div.textContent = str || '';
        return div.textContent;
    }

    function getImageUrl(product) {
        var imgs = product.images;
        if (Array.isArray(imgs) && imgs.length > 0 && imgs[0].url) {
            return KECart.resolveImageUrl(imgs[0].url);
        }
        return 'https://via.placeholder.com/400x260?text=No+Image';
    }

    function createProductCard(product) {
        var imageUrl = getImageUrl(product);
        var name = product.name || 'Untitled';
        var price = product.price ? '$' + parseFloat(product.price).toFixed(2) : '';

        var card = document.createElement('div');
        card.className = 'product-card';

        var img = document.createElement('img');
        img.className = 'product-card__img';
        img.src = imageUrl;
        img.alt = esc(name);
        img.loading = 'lazy';
        card.appendChild(img);

        var body = document.createElement('div');
        body.className = 'product-card__body';

        var h3 = document.createElement('h3');
        h3.className = 'product-card__name';
        h3.textContent = name;
        body.appendChild(h3);

        var p = document.createElement('p');
        p.className = 'product-card__price';
        p.textContent = price;
        body.appendChild(p);

        var btn = document.createElement('a');
        btn.className = 'product-card__btn';
        btn.href = 'product-detail.html?id=' + encodeURIComponent(product.id);
        btn.setAttribute('data-barba-prevent', 'self');
        btn.textContent = 'View Details';
        body.appendChild(btn);

        card.appendChild(body);
        return card;
    }

    function fetchProducts() {
        var grid = document.getElementById('productGrid');
        var countEl = document.getElementById('productCount');
        if (!grid) return;

        fetch(API_BASE + '/products')
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (data) {
                var products = data.products || [];
                grid.textContent = '';

                if (products.length === 0) {
                    var msg = document.createElement('p');
                    msg.className = 'store-loading';
                    msg.textContent = 'No products available right now. Check back soon.';
                    grid.appendChild(msg);
                    if (countEl) countEl.textContent = '';
                    return;
                }

                if (countEl) countEl.textContent = products.length + ' product' + (products.length !== 1 ? 's' : '');
                products.forEach(function (product) {
                    grid.appendChild(createProductCard(product));
                });
            })
            .catch(function (err) {
                console.error('Fetch products error:', err);
                grid.textContent = '';
                var errMsg = document.createElement('p');
                errMsg.className = 'store-error';
                errMsg.textContent = 'Failed to load products. Please try again later.';
                grid.appendChild(errMsg);
                if (countEl) countEl.textContent = '';
            });
    }

    function init() {
        fetchProducts();
        KECart.updateCartBadges();
    }

    return { init: init };
})();
