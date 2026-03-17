/**
 * base.js — Core UI behaviors loaded on every page
 * Flash message auto-dismiss, Lucide icons init, profile modal
 */

// Auto-hide flash messages after 5 seconds
setTimeout(function() {
    var flashes = document.querySelectorAll('.flash');
    flashes.forEach(function(flash) {
        flash.style.opacity = '0';
        flash.style.transition = 'opacity 0.3s';
        setTimeout(function() { flash.remove(); }, 300);
    });
}, 5000);

// Initialize Lucide icons on page load
document.addEventListener('DOMContentLoaded', function() {
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
});

// ═══════════════════════════════════════════════════════════════════════
// GLOBAL PROFILE MODAL
// ═══════════════════════════════════════════════════════════════════════
window.toggleProfileModal = function() {
    var modal = document.getElementById('globalProfileModal');
    if (modal) {
        modal.style.display = modal.style.display === 'none' ? '' : 'none';
    }
};

// Close on click outside
document.addEventListener('click', function(e) {
    var modal = document.getElementById('globalProfileModal');
    var btn = document.getElementById('globalProfileBtn');
    if (modal && modal.style.display !== 'none' &&
        btn && !modal.contains(e.target) && !btn.contains(e.target)) {
        modal.style.display = 'none';
    }
});

// Close on Escape
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        var modal = document.getElementById('globalProfileModal');
        if (modal) modal.style.display = 'none';
    }
});
