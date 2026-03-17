(function() {
    'use strict';

    // ═══════════════════════════════════════════════════════════════════════
    // Stardate Calculator
    // ═══════════════════════════════════════════════════════════════════════
    function calcStardate() {
        var now = new Date();
        var y = now.getFullYear();
        var start = new Date(y, 0, 1);
        var diff = now - start;
        var dayOfYear = Math.floor(diff / 86400000);
        // TNG-era stardate: (year - 1947) * 1000 + day fraction
        var sd = ((y - 1947) * 1000 + dayOfYear * (1000 / 365.25)).toFixed(1);
        return 'SD ' + sd;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Boot Animation
    // ═══════════════════════════════════════════════════════════════════════
    var frame = document.getElementById('signupFrame');
    var stardateEl = document.getElementById('signupStardate');
    var BOOT_KEY = 'archie-signup-booted';
    var skipBoot = sessionStorage.getItem(BOOT_KEY) === '1';

    function finishBoot() {
        frame.classList.remove('boot-hidden');
        frame.classList.add('frame-build');
        sessionStorage.setItem(BOOT_KEY, '1');
        // Set real stardate after brief easter egg
        if (stardateEl) {
            stardateEl.textContent = 'THREAT LEVEL MIDNIGHT';
            setTimeout(function() {
                stardateEl.textContent = calcStardate();
            }, 500);
        }
    }

    if (skipBoot) {
        // Skip animation, show immediately
        frame.classList.remove('boot-hidden');
        frame.classList.add('frame-build');
        if (stardateEl) stardateEl.textContent = calcStardate();
    } else {
        // Slight delay then trigger boot sequence
        setTimeout(finishBoot, 150);

        // Click or keypress to skip boot animation
        var skipHandler = function() {
            frame.classList.remove('boot-hidden');
            frame.classList.add('frame-build');
            sessionStorage.setItem(BOOT_KEY, '1');
            if (stardateEl) stardateEl.textContent = calcStardate();
            document.removeEventListener('click', skipHandler);
            document.removeEventListener('keypress', skipHandler);
        };
        document.addEventListener('click', skipHandler);
        document.addEventListener('keypress', skipHandler);
    }

    // ═══════════════════════════════════════════════════════════════════════
    // i18n Helper — safe wrapper
    // ═══════════════════════════════════════════════════════════════════════
    function t(key, fallback) {
        return (typeof archieI18n !== 'undefined') ? archieI18n.t(key, fallback) : fallback;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Step Navigation
    // ═══════════════════════════════════════════════════════════════════════
    var currentStep = 1;
    var totalSteps = 3;

    var stepPills = document.querySelectorAll('.signup-step');
    var stepPanels = document.querySelectorAll('.signup-step-panel');
    var stepBackBtn = document.getElementById('stepBackBtn');
    var stepNextBtn = document.getElementById('stepNextBtn');
    var signupBtn = document.getElementById('signupBtn');

    function goToStep(step) {
        // Validate before advancing
        if (step > currentStep && !validateStep(currentStep)) return;

        var direction = step > currentStep ? 1 : -1;
        currentStep = step;

        // Update step panels with slide transition
        stepPanels.forEach(function(panel) {
            var panelStep = parseInt(panel.getAttribute('data-step'));
            panel.classList.remove('active', 'exit-left');
            if (panelStep === currentStep) {
                // Set initial position based on direction
                if (direction > 0) {
                    panel.style.transform = 'translateX(30px)';
                } else {
                    panel.style.transform = 'translateX(-30px)';
                }
                panel.classList.add('active');
                // Trigger reflow then animate to center
                panel.offsetHeight;
                panel.style.transform = '';
            }
        });

        // Update header step pills
        stepPills.forEach(function(pill) {
            var pillStep = parseInt(pill.getAttribute('data-step'));
            pill.classList.remove('active', 'completed');
            if (pillStep === currentStep) {
                pill.classList.add('active');
            } else if (pillStep < currentStep) {
                pill.classList.add('completed');
            }
        });

        // Update nav buttons
        stepBackBtn.style.display = currentStep === 1 ? 'none' : '';
        stepNextBtn.style.display = currentStep === totalSteps ? 'none' : '';
        signupBtn.style.display = currentStep === totalSteps ? '' : 'none';

        // Populate review on step 3
        if (currentStep === 3) {
            var uname = document.getElementById('username').value;
            var em = document.getElementById('email').value;
            var pw = document.getElementById('password').value;
            document.getElementById('reviewUsername').textContent = uname;
            document.getElementById('reviewEmail').textContent = em;
            document.getElementById('reviewPassword').textContent = '\u2022'.repeat(Math.min(pw.length, 16));
        }

        // Focus first input of new step
        var activePanel = document.querySelector('.signup-step-panel.active');
        if (activePanel) {
            var firstInput = activePanel.querySelector('input');
            if (firstInput) setTimeout(function() { firstInput.focus(); }, 100);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Step Validation
    // ═══════════════════════════════════════════════════════════════════════
    function validateStep(step) {
        clearErrors();

        if (step === 1) {
            var username = document.getElementById('username');
            var email = document.getElementById('email');
            var valid = true;

            if (!username.value || username.value.trim().length < 3) {
                showError('usernameError', t('signup.error_username_min', 'Username must be at least 3 characters'));
                username.classList.add('input-error');
                valid = false;
            }

            if (!email.value || !isValidEmail(email.value)) {
                showError('emailError', t('signup.error_email_invalid', 'Please enter a valid email address'));
                email.classList.add('input-error');
                valid = false;
            }

            return valid;
        }

        if (step === 2) {
            var password = document.getElementById('password');
            var confirm = document.getElementById('confirm_password');
            var valid = true;

            if (!password.value || password.value.length < 8) {
                showError('passwordError', t('signup.error_password_min', 'Password must be at least 8 characters'));
                password.classList.add('input-error');
                valid = false;
            }

            if (password.value !== confirm.value) {
                showError('confirmError', t('signup.error_passwords_mismatch', 'Passwords do not match'));
                confirm.classList.add('input-error');
                valid = false;
            }

            return valid;
        }

        return true;
    }

    function isValidEmail(email) {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    }

    function showError(id, msg) {
        var el = document.getElementById(id);
        if (el) {
            el.textContent = msg;
            el.classList.add('visible');
        }
    }

    function clearErrors() {
        document.querySelectorAll('.field-error').forEach(function(el) {
            el.classList.remove('visible');
            el.textContent = '';
        });
        document.querySelectorAll('.input-error').forEach(function(el) {
            el.classList.remove('input-error');
        });
    }

    // Clear errors on input
    document.querySelectorAll('.signup-form-input').forEach(function(input) {
        input.addEventListener('input', function() {
            this.classList.remove('input-error');
            var errorEl = this.closest('.signup-form-group').querySelector('.field-error');
            if (errorEl) {
                errorEl.classList.remove('visible');
                errorEl.textContent = '';
            }
        });
    });

    // Button handlers
    stepNextBtn.addEventListener('click', function() {
        if (currentStep < totalSteps) goToStep(currentStep + 1);
    });

    stepBackBtn.addEventListener('click', function() {
        if (currentStep > 1) goToStep(currentStep - 1);
    });

    // Allow clicking step pills to navigate (only to completed/current steps)
    stepPills.forEach(function(pill) {
        pill.addEventListener('click', function() {
            var target = parseInt(this.getAttribute('data-step'));
            if (target < currentStep) {
                goToStep(target);
            } else if (target === currentStep + 1) {
                goToStep(target);
            }
        });
    });

    // ═══════════════════════════════════════════════════════════════════════
    // Form Submit — Loading State
    // ═══════════════════════════════════════════════════════════════════════
    document.getElementById('signupForm').addEventListener('submit', function(e) {
        if (!validateStep(1) || !validateStep(2)) {
            e.preventDefault();
            return;
        }
        var btn = document.getElementById('signupBtn');
        btn.classList.add('loading');
        btn.textContent = t('signup.registering', 'REGISTERING...');
    });

    // ═══════════════════════════════════════════════════════════════════════
    // Password Visibility Toggle
    // ═══════════════════════════════════════════════════════════════════════
    function createSvgIcon(pathData) {
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '16');
        svg.setAttribute('height', '16');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        pathData.forEach(function(d) {
            var el;
            if (d.tag === 'circle') {
                el = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                el.setAttribute('cx', d.cx); el.setAttribute('cy', d.cy); el.setAttribute('r', d.r);
            } else if (d.tag === 'line') {
                el = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                el.setAttribute('x1', d.x1); el.setAttribute('y1', d.y1);
                el.setAttribute('x2', d.x2); el.setAttribute('y2', d.y2);
            } else {
                el = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                el.setAttribute('d', d.d);
            }
            svg.appendChild(el);
        });
        return svg;
    }

    var eyeOpenPaths = [
        {d: 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'},
        {tag: 'circle', cx: '12', cy: '12', r: '3'}
    ];
    var eyeClosedPaths = [
        {d: 'M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24'},
        {tag: 'line', x1: '1', y1: '1', x2: '23', y2: '23'}
    ];

    document.querySelectorAll('.password-toggle').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var input = document.getElementById(this.dataset.target);
            var isHidden = input.type === 'password';
            input.type = isHidden ? 'text' : 'password';
            this.replaceChildren(createSvgIcon(isHidden ? eyeClosedPaths : eyeOpenPaths));
            this.title = isHidden
                ? t('signup.hide_password', 'Hide password')
                : t('signup.show_password', 'Show password');
        });
    });

    // ═══════════════════════════════════════════════════════════════════════
    // Password Strength Checker
    // ═══════════════════════════════════════════════════════════════════════
    var strengthColors = ['#ff4444', '#ff8800', '#ffbb00', '#88cc00', '#00cc44'];
    var strengthLabels = [
        t('signup.strength_very_weak', 'Very weak'),
        t('signup.strength_weak', 'Weak'),
        t('signup.strength_fair', 'Fair'),
        t('signup.strength_strong', 'Strong'),
        t('signup.strength_very_strong', 'Very strong')
    ];
    var passwordInput = document.getElementById('password');
    var strengthBar = document.getElementById('strengthBar');
    var strengthFill = document.getElementById('strengthFill');
    var strengthNote = document.getElementById('strengthNote');

    function calcStrength(pw) {
        var score = 0;
        if (pw.length >= 8) score++;
        if (pw.length >= 12) score++;
        if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
        if (/\d/.test(pw)) score++;
        if (/[^a-zA-Z0-9]/.test(pw)) score++;
        return Math.min(score, 5);
    }

    passwordInput.addEventListener('input', function() {
        var pw = this.value;
        if (pw.length === 0) {
            strengthBar.classList.remove('visible');
            strengthNote.textContent = t('signup.password_hint', 'Minimum 8 characters');
            strengthNote.style.color = '';
            return;
        }
        var score = calcStrength(pw);
        var idx = Math.max(0, score - 1);
        var color = strengthColors[idx];
        var pct = (score / 5) * 100;

        strengthBar.classList.add('visible');
        strengthFill.style.width = pct + '%';
        strengthFill.style.background = color;
        strengthNote.textContent = strengthLabels[idx];
        strengthNote.style.color = color;
    });

    // ═══════════════════════════════════════════════════════════════════════
    // Language Dropdown
    // ═══════════════════════════════════════════════════════════════════════
    var LANG_LABELS = { en: 'EN', fr: 'FR', es: 'ES', pt: 'PT', de: 'DE', zh: '\u4e2d\u6587', ar: '\u0639\u0631', he: '\u05e2\u05d1' };
    var langBtn = document.getElementById('langToggle');
    var langMenu = document.getElementById('langMenu');

    function syncLangUI(lang) {
        if (langBtn) {
            var span = langBtn.querySelector('span');
            if (span) span.textContent = LANG_LABELS[lang] || lang.toUpperCase();
        }
        if (langMenu) {
            langMenu.querySelectorAll('.lang-dropdown-item').forEach(function(o) {
                o.classList.toggle('active', o.getAttribute('data-lang') === lang);
            });
        }
    }

    if (langMenu) {
        langMenu.querySelectorAll('.lang-dropdown-item').forEach(function(opt) {
            opt.addEventListener('click', function() {
                var lang = opt.getAttribute('data-lang');
                if (window.archieI18n) archieI18n.switchLanguage(lang);
                syncLangUI(lang);
                langMenu.classList.add('hidden');
            });
        });
    }

    // Close dropdown on outside click
    document.addEventListener('click', function(e) {
        if (langMenu && !langMenu.classList.contains('hidden') &&
            !langMenu.contains(e.target) && e.target !== langBtn && !langBtn.contains(e.target)) {
            langMenu.classList.add('hidden');
        }
    });

    // ═══════════════════════════════════════════════════════════════════════
    // i18n Init
    // ═══════════════════════════════════════════════════════════════════════
    if (typeof archieI18n !== 'undefined') {
        archieI18n.init();
        setTimeout(function() { syncLangUI(archieI18n.getCurrentLanguage()); }, 500);
    }
})();
