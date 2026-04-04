/* ==========================================================================
   Interactive Cost Calculator — js/calculator.js
   Loads pricing data, renders checkbox grid, calculates savings
   ========================================================================== */

var Calculator = (function () {
    'use strict';

    var container = null;
    var pricingData = null;
    var tiers = null;

    function init() {
        container = document.getElementById('costCalculator');
        if (!container) return;

        fetch('data/pricing.json')
            .then(function (res) { return res.json(); })
            .then(function (data) {
                pricingData = data.competitor_prices;
                tiers = data.tiers;
                render();
            })
            .catch(function (err) {
                console.error('Calculator: failed to load pricing data', err);
            });
    }

    function render() {
        if (!pricingData || !container) return;

        // Build checkbox grid
        var grid = document.createElement('div');
        grid.className = 'comp-calculator__grid';

        var keys = Object.keys(pricingData);
        keys.forEach(function (key) {
            var item = pricingData[key];
            var wrapper = document.createElement('label');
            wrapper.className = 'comp-calculator__item';

            var checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'comp-calculator__checkbox';
            checkbox.value = key;
            checkbox.checked = true;
            checkbox.addEventListener('change', recalculate);

            var labelBlock = document.createElement('span');
            labelBlock.className = 'comp-calculator__label';

            var labelText = document.createTextNode(item.label);
            labelBlock.appendChild(labelText);

            var toolSpan = document.createElement('span');
            toolSpan.className = 'comp-calculator__tool';
            toolSpan.textContent = item.tool;
            labelBlock.appendChild(toolSpan);

            var priceSpan = document.createElement('span');
            priceSpan.className = 'comp-calculator__price';
            priceSpan.textContent = '$' + item.price + '/' + item.period;

            wrapper.appendChild(checkbox);
            wrapper.appendChild(labelBlock);
            wrapper.appendChild(priceSpan);

            // Toggle visual state
            wrapper.addEventListener('click', function () {
                // Let the checkbox change event handle recalculation
                // Just toggle the visual class
                setTimeout(function () {
                    if (checkbox.checked) {
                        wrapper.classList.add('comp-calculator__item--checked');
                    } else {
                        wrapper.classList.remove('comp-calculator__item--checked');
                    }
                }, 0);
            });

            // Initial checked state
            wrapper.classList.add('comp-calculator__item--checked');

            grid.appendChild(wrapper);
        });

        // Build result area
        var result = document.createElement('div');
        result.className = 'comp-calculator__result';
        result.id = 'calculatorResult';

        container.appendChild(grid);
        container.appendChild(result);

        recalculate();
    }

    function recalculate() {
        var resultEl = document.getElementById('calculatorResult');
        if (!resultEl) return;

        // Clear previous result
        while (resultEl.firstChild) {
            resultEl.removeChild(resultEl.firstChild);
        }

        var checkboxes = container.querySelectorAll('.comp-calculator__checkbox');
        var totalCompetitor = 0;
        var checkedCount = 0;

        checkboxes.forEach(function (cb) {
            if (cb.checked) {
                var key = cb.value;
                var item = pricingData[key];
                if (item) {
                    totalCompetitor += item.price;
                    checkedCount++;
                }
            }
        });

        if (checkedCount === 0) {
            var emptyMsg = document.createElement('div');
            emptyMsg.className = 'comp-calculator__empty';
            emptyMsg.textContent = 'Check the features you need to see a cost comparison.';
            resultEl.appendChild(emptyMsg);
            return;
        }

        // Determine best Kytran tier
        var bestTier = findBestTier(checkedCount);
        var kytranPrice = bestTier ? bestTier.price : 0;
        var savings = totalCompetitor > 0
            ? Math.round(((totalCompetitor - kytranPrice) / totalCompetitor) * 100)
            : 0;

        // Their cost block
        var theirBlock = document.createElement('div');
        theirBlock.className = 'comp-calculator__their-cost';

        var theirLabel = document.createElement('div');
        theirLabel.className = 'comp-calculator__cost-label';
        theirLabel.textContent = 'Their cost (' + checkedCount + ' tools)';

        var theirValue = document.createElement('div');
        theirValue.className = 'comp-calculator__cost-value comp-calculator__cost-value--red';
        theirValue.textContent = '$' + totalCompetitor.toLocaleString() + '/mo';

        theirBlock.appendChild(theirLabel);
        theirBlock.appendChild(theirValue);

        // VS divider
        var vsDiv = document.createElement('div');
        vsDiv.className = 'comp-calculator__vs-divider';
        vsDiv.textContent = 'VS';

        // Our cost block
        var ourBlock = document.createElement('div');
        ourBlock.className = 'comp-calculator__our-cost';

        var ourLabel = document.createElement('div');
        ourLabel.className = 'comp-calculator__cost-label';
        ourLabel.textContent = 'Kytran ' + (bestTier ? bestTier.name : 'Platform');

        var ourValue = document.createElement('div');
        ourValue.className = 'comp-calculator__cost-value comp-calculator__cost-value--green';
        ourValue.textContent = kytranPrice === 0
            ? 'Free'
            : '$' + kytranPrice.toLocaleString() + '/mo';

        ourBlock.appendChild(ourLabel);
        ourBlock.appendChild(ourValue);

        resultEl.appendChild(theirBlock);
        resultEl.appendChild(vsDiv);
        resultEl.appendChild(ourBlock);

        // Savings badge
        if (savings > 0) {
            var savingsBadge = document.createElement('div');
            savingsBadge.className = 'comp-calculator__savings';
            savingsBadge.textContent = 'Save ' + savings + '%';

            // Wrap in full-width container
            var savingsRow = document.createElement('div');
            savingsRow.style.width = '100%';
            savingsRow.style.textAlign = 'center';
            savingsRow.appendChild(savingsBadge);
            resultEl.appendChild(savingsRow);
        }
    }

    function findBestTier(featureCount) {
        if (!tiers || tiers.length === 0) return null;

        // Simple mapping: more features selected = higher tier needed
        // 1-3 features -> Starter, 4-8 -> Professional, 9+ -> Enterprise
        var paidTiers = tiers.filter(function (t) {
            return t.price !== null && t.price > 0;
        });

        if (paidTiers.length === 0) return tiers[0];

        if (featureCount <= 3) {
            return paidTiers[0]; // Starter
        } else if (featureCount <= 8) {
            return paidTiers.length > 1 ? paidTiers[1] : paidTiers[0]; // Professional
        } else {
            return paidTiers.length > 2 ? paidTiers[2] : paidTiers[paidTiers.length - 1]; // Enterprise
        }
    }

    return {
        init: init
    };
})();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function () {
    Calculator.init();
});
