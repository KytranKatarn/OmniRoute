/* ==========================================================================
   Kytran News — Sidebar Collapsible Categories
   Handles expand/collapse of layer category groups
   ========================================================================== */
(function () {
    'use strict';

    function initSidebarCollapse() {
        var categories = document.querySelectorAll('.layer-category');
        categories.forEach(function (cat) {
            var header = cat.querySelector('.layer-category__header');
            if (!header) return;

            header.addEventListener('click', function (e) {
                e.preventDefault();
                var isOpen = cat.classList.contains('open');
                cat.classList.toggle('open');
                header.setAttribute('aria-expanded', String(!isOpen));
            });
        });
    }

    // Also handle sidebar mobile toggle (hamburger)
    function initSidebarToggle() {
        var toggle = document.getElementById('sidebar-toggle');
        var sidebar = document.querySelector('.sidebar');
        var backdrop = document.getElementById('sidebar-backdrop');
        if (!toggle || !sidebar) return;

        function openSidebar() {
            sidebar.classList.add('open');
            if (backdrop) backdrop.classList.add('open');
        }
        function closeSidebar() {
            sidebar.classList.remove('open');
            if (backdrop) backdrop.classList.remove('open');
        }

        toggle.addEventListener('click', function () {
            if (sidebar.classList.contains('open')) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });

        if (backdrop) {
            backdrop.addEventListener('click', closeSidebar);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            initSidebarCollapse();
            initSidebarToggle();
        });
    } else {
        initSidebarCollapse();
        initSidebarToggle();
    }
})();
