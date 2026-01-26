/**
 * A.R.C.H.I.E. Theme System
 * Platform-wide theme management for light/dark mode toggle
 *
 * Features:
 * - localStorage persistence
 * - System preference detection
 * - Custom event dispatch for component reactions
 * - Language placeholder for future i18n
 */

(function() {
    'use strict';

    const THEME_KEY = 'archie-theme';
    const LANG_KEY = 'archie-lang';

    /**
     * Initialize theme from localStorage or system preference
     * Called on page load
     */
    function initTheme() {
        // Guard against running before body exists
        if (!document.body) return;

        const saved = localStorage.getItem(THEME_KEY);

        if (saved === 'light') {
            document.body.classList.add('light-mode');
        } else if (saved === 'dark') {
            document.body.classList.remove('light-mode');
        } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
            // No saved preference, use system preference
            document.body.classList.add('light-mode');
        }

        updateThemeIcon();

        // Listen for system theme changes
        if (window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
                // Only auto-switch if no user preference saved
                if (!localStorage.getItem(THEME_KEY)) {
                    if (e.matches) {
                        document.body.classList.add('light-mode');
                    } else {
                        document.body.classList.remove('light-mode');
                    }
                    updateThemeIcon();
                }
            });
        }
    }

    /**
     * Toggle between light and dark themes
     * Saves preference to localStorage
     */
    window.toggleTheme = function() {
        document.body.classList.toggle('light-mode');
        const isLight = document.body.classList.contains('light-mode');
        localStorage.setItem(THEME_KEY, isLight ? 'light' : 'dark');
        updateThemeIcon();

        // Dispatch custom event for components that need to react
        window.dispatchEvent(new CustomEvent('themechange', {
            detail: {
                theme: isLight ? 'light' : 'dark',
                timestamp: Date.now()
            }
        }));

        // Update any matrix rain canvases
        updateMatrixRain();
    };

    /**
     * Update theme toggle icon to reflect current state
     */
    function updateThemeIcon() {
        if (!document.body) return;
        const icon = document.getElementById('themeIcon');
        if (icon) {
            const isLight = document.body.classList.contains('light-mode');
            icon.setAttribute('data-lucide', isLight ? 'moon' : 'sun');

            // Reinitialize Lucide icons if available
            if (window.lucide && typeof lucide.createIcons === 'function') {
                lucide.createIcons();
            }
        }
    }

    /**
     * Update matrix rain colors for theme change
     * The matrix rain draw function checks body.classList on each frame
     */
    function updateMatrixRain() {
        // Matrix rain canvas will check light-mode class on next draw cycle
        // No additional action needed - the draw() function in each page handles this
    }

    /**
     * Get current theme
     * @returns {string} 'light' or 'dark'
     */
    window.getArchieTheme = function() {
        return document.body.classList.contains('light-mode') ? 'light' : 'dark';
    };

    /**
     * Set theme programmatically
     * @param {string} theme - 'light' or 'dark'
     */
    window.setArchieTheme = function(theme) {
        if (theme === 'light') {
            document.body.classList.add('light-mode');
        } else {
            document.body.classList.remove('light-mode');
        }
        localStorage.setItem(THEME_KEY, theme);
        updateThemeIcon();

        window.dispatchEvent(new CustomEvent('themechange', {
            detail: { theme, timestamp: Date.now() }
        }));
    };

    /**
     * Show language selection menu
     * Placeholder for future i18n implementation
     */
    window.showLanguageMenu = function() {
        // Create notification toast
        const notification = document.createElement('div');
        notification.className = 'theme-notification';
        notification.innerHTML = '<strong>LANGUAGE</strong><br>Multi-language support coming soon!';
        notification.style.cssText = `
            position: fixed;
            top: 80px;
            right: 20px;
            padding: 16px 24px;
            background: var(--archie-bg-secondary, #0d1117);
            border: 1px solid var(--archie-cyan, #00ffff);
            border-radius: 8px;
            color: var(--archie-cyan, #00ffff);
            font-family: var(--archie-font-mono, 'JetBrains Mono', monospace);
            font-size: 0.875rem;
            z-index: 10000;
            animation: fadeInUp 0.3s ease;
            box-shadow: 0 4px 20px rgba(0, 255, 255, 0.2);
        `;

        document.body.appendChild(notification);

        // Auto-remove after 3 seconds
        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transition = 'opacity 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    };

    /**
     * Get current language
     * @returns {string} Language code (default: 'en')
     */
    window.getArchieLanguage = function() {
        return localStorage.getItem(LANG_KEY) || 'en';
    };

    /**
     * Set language (placeholder for future i18n)
     * @param {string} lang - Language code
     */
    window.setArchieLanguage = function(lang) {
        localStorage.setItem(LANG_KEY, lang);
        // Future: trigger page translation
    };

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTheme);
    } else {
        initTheme();
    }

    // Also run immediately to prevent flash of wrong theme
    initTheme();

})();
