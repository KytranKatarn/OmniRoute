/* Salon plugin — minimal JS bootstrap */
(function () {
    const BASE = '/plugins/industry-salon';
    const tabs = [
        { id: 'bookings', label: 'Bookings' },
        { id: 'services', label: 'Services' },
        { id: 'stylists', label: 'Stylists' },
        { id: 'inventory', label: 'Inventory' },
        { id: 'history',  label: 'Client History' },
    ];

    function api(path) {
        return fetch(BASE + path).then(r => r.json());
    }

    function buildTabs() {
        const container = document.getElementById('salon-tabs');
        if (!container) return;
        tabs.forEach((t, i) => {
            const btn = document.createElement('button');
            btn.className = 'salon-tab-btn' + (i === 0 ? ' active' : '');
            btn.textContent = t.label;
            btn.addEventListener('click', () => {
                document.querySelectorAll('.salon-tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                document.querySelectorAll('.salon-panel').forEach(p => { p.style.display = 'none'; });
                const panel = document.getElementById('tab-' + t.id);
                if (panel) { panel.style.display = 'block'; }
            });
            container.appendChild(btn);
        });
    }

    function buildStatCard(label, value) {
        const card = document.createElement('div');
        card.className = 'salon-stat-card';
        const val = document.createElement('div');
        val.className = 'stat-value';
        val.textContent = String(value);
        const lbl = document.createElement('div');
        lbl.className = 'stat-label';
        lbl.textContent = label;
        card.appendChild(val);
        card.appendChild(lbl);
        return card;
    }

    function loadStats() {
        api('/api/stats').then(data => {
            const el = document.getElementById('salon-stats');
            if (!el) return;
            el.textContent = '';
            const items = [
                { label: 'Bookings Today',      value: data.bookings_today },
                { label: 'Completed This Week', value: data.completed_this_week },
                { label: 'Low Stock Products',  value: data.low_stock_products },
                { label: 'Revenue This Month',  value: '$' + (data.revenue_this_month || 0).toFixed(2) },
            ];
            items.forEach(i => el.appendChild(buildStatCard(i.label, i.value)));
        }).catch(() => {});
    }

    document.addEventListener('DOMContentLoaded', () => {
        buildTabs();
        loadStats();
        if (typeof feather !== 'undefined') { feather.replace(); }
    });
})();
