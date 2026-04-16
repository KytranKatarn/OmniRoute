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
var _profileJustOpened = false;
window.toggleProfileModal = function() {
    var modal = document.getElementById('globalProfileModal');
    if (modal) {
        var wasHidden = modal.classList.contains('archie-hidden');
        modal.classList.toggle('archie-hidden');
        if (wasHidden) {
            _profileJustOpened = true;
            setTimeout(function() { _profileJustOpened = false; }, 100);
        }
    }
};

// Close on click outside
document.addEventListener('click', function(e) {
    if (_profileJustOpened) return;
    var modal = document.getElementById('globalProfileModal');
    if (modal && !modal.classList.contains('archie-hidden') &&
        !modal.contains(e.target)) {
        modal.classList.add('archie-hidden');
    }
});

// Close on Escape
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        var modal = document.getElementById('globalProfileModal');
        if (modal) modal.classList.add('archie-hidden');
    }
});
