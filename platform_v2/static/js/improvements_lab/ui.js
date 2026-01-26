/**
 * Improvements Lab UI Utilities
 * Notifications, modals, and common UI functions
 */

const ImprovementsUI = {
    // ==================== NOTIFICATIONS ====================

    /**
     * Show a notification toast
     */
    notify(message, type = 'info', duration = 4000) {
        const colors = {
            success: { bg: '#0d1117', border: '#00ff41', icon: '✓', glow: 'rgba(0,255,65,0.3)' },
            error: { bg: '#0d1117', border: '#ff4136', icon: '✗', glow: 'rgba(255,65,54,0.3)' },
            warning: { bg: '#0d1117', border: '#FFAA00', icon: '⚠', glow: 'rgba(255,170,0,0.3)' },
            info: { bg: '#0d1117', border: '#00FFFF', icon: 'ℹ', glow: 'rgba(0,255,255,0.3)' }
        };

        const style = colors[type] || colors.info;

        // Create container if not exists
        let container = document.getElementById('notification-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'notification-container';
            container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:10000;display:flex;flex-direction:column;gap:10px;max-width:400px;';
            document.body.appendChild(container);
        }

        // Create notification
        const notification = document.createElement('div');
        notification.className = 'notification-toast';
        notification.style.cssText = `
            background: ${style.bg};
            border: 1px solid ${style.border};
            border-left: 4px solid ${style.border};
            padding: 12px 16px;
            border-radius: 4px;
            display: flex;
            align-items: flex-start;
            gap: 10px;
            animation: slideIn 0.3s ease;
            box-shadow: 0 0 15px ${style.glow};
            font-family: 'JetBrains Mono', monospace;
        `;

        notification.innerHTML = `
            <span style="font-size:1.2em;color:${style.border};">${style.icon}</span>
            <span style="flex:1;color:#fff;font-size:0.9rem;">${message}</span>
            <button onclick="this.parentElement.remove()" style="background:none;border:none;color:#666;cursor:pointer;font-size:1.2em;padding:0;transition:color 0.2s;" onmouseenter="this.style.color='${style.border}'" onmouseleave="this.style.color='#666'">&times;</button>
        `;

        container.appendChild(notification);

        // Auto remove
        if (duration > 0) {
            setTimeout(() => {
                notification.style.animation = 'slideOut 0.3s ease';
                setTimeout(() => notification.remove(), 300);
            }, duration);
        }

        return notification;
    },

    success(message, duration) { return this.notify(message, 'success', duration); },
    error(message, duration) { return this.notify(message, 'error', duration); },
    warning(message, duration) { return this.notify(message, 'warning', duration); },
    info(message, duration) { return this.notify(message, 'info', duration); },

    // ==================== MODALS ====================

    /**
     * Show a modal dialog
     */
    showModal(options = {}) {
        const {
            title = '',
            content = '',
            size = 'medium', // small, medium, large, full
            closable = true,
            onClose = null
        } = options;

        const widths = {
            small: '400px',
            medium: '600px',
            large: '900px',
            full: '95vw'
        };

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.9);
            z-index: 9999;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            animation: fadeIn 0.2s ease;
        `;

        // Create modal
        const modal = document.createElement('div');
        modal.className = 'modal-content';
        modal.style.cssText = `
            background: #0d1117;
            border: 2px solid #00FFFF;
            border-radius: 8px;
            max-width: ${widths[size]};
            width: 100%;
            max-height: 90vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            animation: slideUp 0.3s ease;
            font-family: 'JetBrains Mono', monospace;
        `;

        // Header
        if (title || closable) {
            const header = document.createElement('div');
            header.style.cssText = `
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 15px 20px;
                border-bottom: 1px solid #00FFFF;
                background: rgba(0, 255, 255, 0.05);
            `;
            header.innerHTML = `
                <h3 style="margin:0;color:#00FFFF;font-family:'Orbitron',sans-serif;font-size:1rem;">${title}</h3>
                ${closable ? '<button class="modal-close-btn" style="background:none;border:none;color:#FF6B6B;font-size:1.5rem;cursor:pointer;padding:0;line-height:1;">&times;</button>' : ''}
            `;
            modal.appendChild(header);

            if (closable) {
                header.querySelector('.modal-close-btn').onclick = () => this.closeModal(overlay, onClose);
            }
        }

        // Body
        const body = document.createElement('div');
        body.className = 'modal-body';
        body.style.cssText = 'padding: 20px; overflow-y: auto; flex: 1; color: #00ff41;';
        if (typeof content === 'string') {
            body.innerHTML = content;
        } else {
            body.appendChild(content);
        }
        modal.appendChild(body);

        overlay.appendChild(modal);

        // Click outside to close
        if (closable) {
            overlay.onclick = (e) => {
                if (e.target === overlay) {
                    this.closeModal(overlay, onClose);
                }
            };
        }

        document.body.appendChild(overlay);
        document.body.style.overflow = 'hidden';

        return { overlay, modal, body };
    },

    /**
     * Close a modal
     */
    closeModal(overlay, onClose = null) {
        if (overlay) {
            overlay.style.animation = 'fadeOut 0.2s ease';
            setTimeout(() => {
                overlay.remove();
                document.body.style.overflow = '';
                if (onClose) onClose();
            }, 200);
        }
    },

    /**
     * Confirmation dialog
     */
    async confirm(message, title = 'Confirm') {
        return new Promise((resolve) => {
            const content = document.createElement('div');
            content.innerHTML = `
                <p style="margin-bottom:20px;color:#fff;white-space:pre-wrap;">${message}</p>
                <div style="display:flex;gap:10px;justify-content:flex-end;">
                    <button class="btn-cancel" style="padding:10px 20px;background:transparent;border:1px solid #666;color:#888;cursor:pointer;border-radius:4px;font-family:'JetBrains Mono',monospace;transition:all 0.3s;">Cancel</button>
                    <button class="btn-confirm" style="padding:10px 20px;background:transparent;border:1px solid #00ff41;color:#00ff41;cursor:pointer;border-radius:4px;font-family:'JetBrains Mono',monospace;transition:all 0.3s;">Confirm</button>
                </div>
            `;

            const { overlay } = this.showModal({ title, content, size: 'small' });

            const cancelBtn = content.querySelector('.btn-cancel');
            const confirmBtn = content.querySelector('.btn-confirm');

            // Add hover effects
            cancelBtn.onmouseenter = () => { cancelBtn.style.borderColor = '#ff4136'; cancelBtn.style.color = '#ff4136'; };
            cancelBtn.onmouseleave = () => { cancelBtn.style.borderColor = '#666'; cancelBtn.style.color = '#888'; };
            confirmBtn.onmouseenter = () => { confirmBtn.style.background = '#00ff41'; confirmBtn.style.color = '#010409'; confirmBtn.style.boxShadow = '0 0 15px #00ff41'; };
            confirmBtn.onmouseleave = () => { confirmBtn.style.background = 'transparent'; confirmBtn.style.color = '#00ff41'; confirmBtn.style.boxShadow = 'none'; };

            cancelBtn.onclick = () => {
                this.closeModal(overlay);
                resolve(false);
            };

            confirmBtn.onclick = () => {
                this.closeModal(overlay);
                resolve(true);
            };
        });
    },

    // ==================== LOADING ====================

    /**
     * Show loading spinner
     */
    showLoading(container, message = 'Loading...') {
        const loader = document.createElement('div');
        loader.className = 'loading-spinner';
        loader.style.cssText = 'text-align:center;padding:40px;';
        loader.innerHTML = `
            <div style="font-size:2rem;margin-bottom:15px;animation:pulse 1.5s infinite;">⏳</div>
            <div style="color:#00FFFF;opacity:0.8;">${message}</div>
        `;

        if (typeof container === 'string') {
            container = document.getElementById(container);
        }

        if (container) {
            container.innerHTML = '';
            container.appendChild(loader);
        }

        return loader;
    },

    /**
     * Show empty state
     */
    showEmpty(container, message = 'No items found', icon = '📭') {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.style.cssText = 'text-align:center;padding:40px;opacity:0.7;';
        empty.innerHTML = `
            <div style="font-size:2rem;margin-bottom:15px;">${icon}</div>
            <div style="color:#888;">${message}</div>
        `;

        if (typeof container === 'string') {
            container = document.getElementById(container);
        }

        if (container) {
            container.innerHTML = '';
            container.appendChild(empty);
        }

        return empty;
    },

    // ==================== FORMATTING ====================

    /**
     * Format date for display
     */
    formatDate(dateString) {
        if (!dateString) return 'N/A';
        const date = new Date(dateString);
        return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    },

    /**
     * Format relative time
     */
    formatRelativeTime(dateString) {
        if (!dateString) return 'N/A';
        const date = new Date(dateString);
        const now = new Date();
        const diff = now - date;

        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);

        if (minutes < 1) return 'Just now';
        if (minutes < 60) return `${minutes}m ago`;
        if (hours < 24) return `${hours}h ago`;
        if (days < 7) return `${days}d ago`;
        return this.formatDate(dateString);
    },

    /**
     * Get status color
     */
    getStatusColor(status) {
        const colors = {
            // New standard statuses
            pending: '#FFA500',
            approved: '#00FFFF',
            code_generating: '#FFFF00',
            generated: '#87CEEB',
            testing: '#FFA500',
            tested: '#90EE90',             // Light green - ready for deploy
            ready_for_review: '#00FFFF',
            deployed: '#00FF00',           // Bright green - fully deployed
            completed: '#00FF00',          // Same as deployed
            escalated: '#FF6B6B',
            rejected: '#FF0000',
            failed: '#FF0000',
            archived: '#666666',
            // Legacy statuses (CodeRabbit)
            proposed: '#FFA500',           // Maps to pending
            pending_approval: '#00FFFF'    // Maps to approved
        };
        return colors[status] || '#888888';
    },

    /**
     * Get status icon
     */
    getStatusIcon(status) {
        const icons = {
            // New standard statuses
            pending: '⏳',
            approved: '✅',
            code_generating: '🔄',
            generated: '📝',
            testing: '🧪',
            tested: '✔️',                  // Tests passed, ready for deploy
            ready_for_review: '👀',
            deployed: '🚀',                // Deployed to production
            completed: '🚀',               // Same as deployed
            escalated: '🔴',
            rejected: '❌',
            failed: '💥',
            archived: '📦',
            // Legacy statuses (CodeRabbit)
            proposed: '⏳',                // Maps to pending
            pending_approval: '✅'         // Maps to approved
        };
        return icons[status] || '❓';
    },

    /**
     * Get priority color
     */
    getPriorityColor(priority) {
        const colors = {
            critical: '#FF0000',
            high: '#FF6B6B',
            medium: '#FFA500',
            low: '#00FF00'
        };
        return colors[priority] || '#888888';
    },

    // ==================== INITIALIZATION ====================

    /**
     * Add CSS animations
     */
    init() {
        if (document.getElementById('improvements-ui-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'improvements-ui-styles';
        styles.textContent = `
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes slideOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            @keyframes fadeOut {
                from { opacity: 1; }
                to { opacity: 0; }
            }
            @keyframes slideUp {
                from { transform: translateY(20px); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
            }
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.3; }
            }
            .btn {
                padding: 0.75rem 1.5rem;
                border: 1px solid #00ff41;
                background: transparent;
                color: #00ff41;
                font-family: 'JetBrains Mono', monospace;
                cursor: pointer;
                border-radius: 4px;
                transition: all 0.3s;
                font-size: 0.9rem;
            }
            .btn:hover {
                background: #00ff41;
                color: #010409;
                box-shadow: 0 0 15px #00ff41;
            }
            .btn-primary {
                border-color: #00FFFF;
                color: #00FFFF;
            }
            .btn-primary:hover {
                background: #00FFFF;
                color: #010409;
                box-shadow: 0 0 15px #00FFFF;
            }
            .btn-danger {
                border-color: #ff4136;
                color: #ff4136;
            }
            .btn-danger:hover {
                background: #ff4136;
                color: #fff;
                box-shadow: 0 0 15px #ff4136;
            }
            .btn-warning {
                border-color: #FFAA00;
                color: #FFAA00;
            }
            .btn-warning:hover {
                background: #FFAA00;
                color: #010409;
                box-shadow: 0 0 15px #FFAA00;
            }
            .btn-small {
                padding: 0.5rem 1rem;
                font-size: 0.8rem;
            }
            .btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
        `;
        document.head.appendChild(styles);
    }
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => ImprovementsUI.init());

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ImprovementsUI;
}
