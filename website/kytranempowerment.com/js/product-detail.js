/* product-detail.js — single product page. Fetches one product from the live
 * public API and wires the qty selector + Add to Cart button to KECart.
 * Real KBS products carry no variants (color/size) at this API surface —
 * intentionally simple, unlike the removed Printful-variant picker.
 * Re-invoked on every Barba transition into this page — see app.js initPageScripts().
 */
var ProductDetail = (function () {
    'use strict';

    var API_BASE = 'https://business.kytranempowerment.com/plugins/store/public';
    var currentProduct = null;
    var qty = 1;

    function getImageUrl(product) {
        var imgs = product.images;
        if (Array.isArray(imgs) && imgs.length > 0 && imgs[0].url) {
            return KECart.resolveImageUrl(imgs[0].url);
        }
        return 'https://via.placeholder.com/400?text=No+Image';
    }

    function renderQty() {
        var qtyEl = document.getElementById('quantity-value');
        if (qtyEl) qtyEl.textContent = String(qty);
    }

    function fetchProduct() {
        var loading = document.getElementById('product-loading');
        var errorEl = document.getElementById('product-error');
        var wrapper = document.getElementById('product-wrapper');
        var productId = new URLSearchParams(window.location.search).get('id');

        if (!loading || !wrapper) return;

        loading.style.display = 'block';
        if (errorEl) errorEl.style.display = 'none';
        wrapper.style.display = 'none';

        if (!productId) {
            loading.style.display = 'none';
            if (errorEl) { errorEl.style.display = 'block'; errorEl.textContent = 'Error: Product ID not found in URL.'; }
            return;
        }

        fetch(API_BASE + '/products/' + encodeURIComponent(productId))
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (product) {
                currentProduct = product;
                qty = 1;
                renderQty();

                document.getElementById('product-name').textContent = product.name || '';
                var descEl = document.getElementById('product-description');
                if (product.description) {
                    descEl.textContent = product.description;
                    descEl.classList.remove('hidden-description');
                } else {
                    descEl.classList.add('hidden-description');
                }
                document.getElementById('product-image').src = getImageUrl(product);
                document.getElementById('product-price').textContent = '$' + parseFloat(product.price).toFixed(2);

                loading.style.display = 'none';
                wrapper.style.display = 'flex';
            })
            .catch(function (err) {
                console.error('Error fetching product:', err);
                loading.style.display = 'none';
                if (errorEl) {
                    errorEl.style.display = 'block';
                    errorEl.textContent = 'Failed to load this product. Please try again later.';
                }
            });
    }

    function bindActions() {
        var decreaseBtn = document.getElementById('qty-decrease');
        var increaseBtn = document.getElementById('qty-increase');
        var addBtn = document.getElementById('add-to-cart-btn');

        if (decreaseBtn) decreaseBtn.onclick = function () { qty = Math.max(1, qty - 1); renderQty(); };
        if (increaseBtn) increaseBtn.onclick = function () { qty++; renderQty(); };
        if (addBtn) {
            addBtn.onclick = function () {
                if (!currentProduct) return;
                KECart.addToCart({
                    id: currentProduct.id,
                    name: currentProduct.name,
                    price: currentProduct.price,
                    image: getImageUrl(currentProduct)
                }, qty);

                var original = addBtn.textContent;
                addBtn.textContent = 'Added ✓';
                setTimeout(function () { addBtn.textContent = original; }, 1500);
            };
        }
    }

    function init() {
        bindActions();
        fetchProduct();
        KECart.updateCartBadges();
    }

    return { init: init };
})();
