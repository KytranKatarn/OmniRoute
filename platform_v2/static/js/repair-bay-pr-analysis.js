/* Repair Bay — explicit, per-request PR analysis choices. No work on open/cancel. */
(function () {
    'use strict';

    var active = null;

    function node(tag, className, text) {
        var item = document.createElement(tag);
        if (className) item.className = className;
        if (text) item.textContent = text;
        return item;
    }

    function select(id, choices) {
        var item = node('select');
        item.id = id;
        choices.forEach(function (choice) {
            var option = node('option', '', choice[1]);
            option.value = choice[0];
            item.appendChild(option);
        });
        return item;
    }

    function field(title, control) {
        var wrap = node('div', 'rb-pr-analysis-field');
        var label = node('label', '', title);
        label.htmlFor = control.id;
        wrap.appendChild(label);
        wrap.appendChild(control);
        return wrap;
    }

    function readJSON(response) {
        return response.json().catch(function () {
            throw new Error('HTTP ' + response.status + ': non-JSON response. Check PR status before retrying.');
        }).then(function (data) {
            if (!response.ok || !data || data.error || data.success === false || data.status === 'in_progress') {
                var message = data && (data.error || data.message);
                if (data && data.repos && data.repos.length) {
                    message = (message || 'Ambiguous PR number.') + ' Repositories: ' +
                        data.repos.join(', ') + '. Open the matching PR row.';
                }
                throw new Error(message || ('HTTP ' + response.status + ': request not accepted.'));
            }
            return data;
        });
    }

    function open(options) {
        options = options || {};
        if (active) {
            active.focus();
            return Promise.resolve(null);
        }
        var number = Number(options.prNumber);
        if (!Number.isSafeInteger(number) || number < 1) return Promise.reject(new Error('A valid PR number is required.'));
        var base = options.apiBase || '/tools/repair-bay/api';
        var previousFocus = document.activeElement;
        var scopeRead = new AbortController();
        var closed = false;
        var posting = false;
        var accepted = null;
        var ceiling = null;
        var defaults = null;

        return new Promise(function (resolve) {
            var overlay = node('div', 'bm-overlay active rb-pr-analysis');
            var shell = node('div', 'bm-shell');
            shell.setAttribute('role', 'dialog');
            shell.setAttribute('aria-modal', 'true');
            shell.setAttribute('aria-labelledby', 'rb-pr-analysis-title');
            shell.tabIndex = -1;
            active = shell;
            var frame = node('div', 'bm-frame');
            frame.setAttribute('aria-hidden', 'true');
            ['bm-frame-elbow-top', 'bm-frame-seg', 'bm-frame-seg dim', 'bm-frame-fill',
                'bm-frame-elbow-bottom'].forEach(function (name) { frame.appendChild(node('div', name)); });
            var form = node('form', 'bm-content');
            var header = node('div', 'bm-header');
            var title = node('span', 'bm-header-title', 'Choose PR analysis');
            title.id = 'rb-pr-analysis-title';
            var strip = node('div', 'bm-header-strip');
            var closeButton = node('button', 'bm-close', '×');
            closeButton.type = 'button';
            closeButton.setAttribute('aria-label', 'Close analysis choices');
            strip.appendChild(closeButton);
            header.appendChild(title);
            header.appendChild(strip);
            var body = node('div', 'bm-body');
            body.appendChild(node('p', 'rb-pr-analysis-context', 'PR #' + number + ' · ' +
                (options.repo || 'repository resolved by server; ambiguous numbers are refused')));
            var mode = select('rb-pr-analysis-mode', [
                ['full', 'Full diff — recommended'], ['scoped', 'Configured scope — may omit files']
            ]);
            var reviewer = select('rb-pr-analysis-reviewer', [
                ['F.O.R.G.E.', 'F.O.R.G.E. — merge review'], ['P.R.O.B.E.', 'P.R.O.B.E. — advisory QA'],
                ['CODEX', 'CODEX — CLI whole-diff review (queued on the host)']
            ]);
            if (options.reviewer === 'P.R.O.B.E.') reviewer.value = options.reviewer;
            var modeField = field('Analysis type', mode);
            body.appendChild(modeField);
            body.appendChild(field('Reviewer', reviewer));
            var reviewerNote = node('p', 'rb-pr-analysis-note');
            body.appendChild(reviewerNote);
            var scope = node('fieldset', 'rb-pr-analysis-scope');
            scope.appendChild(node('legend', '', 'This request only'));
            var plan = select('rb-pr-analysis-plan', [['per_file', 'Per file'], ['packed', 'Packed']]);
            var maxFiles = node('input');
            maxFiles.id = 'rb-pr-analysis-max-files';
            maxFiles.type = 'number';
            maxFiles.min = '1';
            maxFiles.step = '1';
            maxFiles.required = true;
            scope.appendChild(field('Review plan', plan));
            scope.appendChild(field('Maximum files', maxFiles));
            body.appendChild(scope);
            var summary = node('p', 'rb-pr-analysis-summary', 'Loading effective review limits…');
            summary.id = 'rb-pr-analysis-summary';
            body.appendChild(summary);
            body.appendChild(node('p', 'rb-pr-analysis-note',
                'No time-limit mode: the timer shows elapsed time. Coverage is measured from what was actually read. ' +
                'Opening or cancelling this dialog launches nothing and changes no global defaults.'));
            var status = node('p', 'rb-pr-analysis-status');
            status.setAttribute('role', 'status');
            status.setAttribute('aria-live', 'polite');
            body.appendChild(status);
            var footer = node('div', 'bm-footer');
            var cancel = node('button', 'rb-pr-analysis-cancel', 'Cancel');
            cancel.type = 'button';
            var submit = node('button', 'rb-pr-analysis-submit', 'Run analysis');
            submit.type = 'submit';
            submit.disabled = true;
            footer.appendChild(cancel);
            footer.appendChild(submit);
            form.appendChild(header);
            form.appendChild(body);
            form.appendChild(footer);
            shell.appendChild(frame);
            shell.appendChild(form);
            overlay.appendChild(shell);

            function close() {
                if (posting || closed) return;
                closed = true;
                scopeRead.abort();
                document.removeEventListener('keydown', onKey, true);
                overlay.remove();
                active = null;
                if (previousFocus && previousFocus.isConnected) previousFocus.focus();
                resolve(accepted);
            }

            function onKey(event) {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    close();
                } else if (event.key === 'Tab') {
                    var controls = Array.from(shell.querySelectorAll('button, input, select'))
                        .filter(function (item) { return !item.disabled && item.getClientRects().length; });
                    var first = controls[0];
                    var last = controls[controls.length - 1];
                    if (!controls.length) { event.preventDefault(); return; }
                    if (event.shiftKey && (document.activeElement === first || !shell.contains(document.activeElement))) {
                        event.preventDefault(); last.focus();
                    } else if (!event.shiftKey && (document.activeElement === last || !shell.contains(document.activeElement))) {
                        event.preventDefault(); first.focus();
                    }
                }
            }

            function update() {
                var codex = reviewer.value === 'CODEX';
                // CODEX is a host CLI job, not a dispatcher review: it always reads the whole diff,
                // so analysis type and scope do not apply and do not need the scope limits loaded.
                modeField.hidden = codex;
                scope.hidden = codex || mode.value !== 'scoped';
                scope.disabled = scope.hidden || posting || !!accepted;
                submit.textContent = posting ? 'Submitting…' : accepted ? 'Request accepted'
                    : (codex ? 'Queue CODEX review' : 'Run analysis');
                reviewerNote.textContent = codex
                    ? 'Runs as a CLI job on the host (not through the dispatcher): minutes of work. The result appears as a PR comment and this panel does not live-update.'
                    : reviewer.value === 'P.R.O.B.E.'
                        ? 'Advisory QA opinion only; this does not satisfy the F.O.R.G.E. merge-review gate.'
                        : 'F.O.R.G.E. owns the merge-review verdict; a request is not an approval.';
                if (codex) {
                    summary.textContent = 'CODEX reads the whole diff. Opening or cancelling this dialog queues nothing.';
                    submit.disabled = posting || !!accepted || typeof options.onCodex !== 'function';
                    return;
                }
                if (!defaults) return;
                var limit = mode.value === 'full' ? ceiling : Number(maxFiles.value);
                summary.textContent = mode.value === 'full'
                    ? 'Full-diff request · per file · up to ' + ceiling + ' files.'
                    : 'Configured request · ' + plan.value + ' · up to ' + limit + ' files; remaining files may not be read.';
                var count = Number(options.changedFiles);
                if (Number.isSafeInteger(count) && count > 0) {
                    summary.textContent += ' This PR has ' + count + ' changed files.';
                    if (count > limit) summary.textContent += ' This limit cannot cover all of them.';
                }
                submit.disabled = posting || !!accepted || (mode.value === 'scoped' && !maxFiles.checkValidity());
            }

            mode.addEventListener('change', update);
            reviewer.addEventListener('change', update);
            plan.addEventListener('change', update);
            maxFiles.addEventListener('input', update);
            cancel.addEventListener('click', close);
            closeButton.addEventListener('click', close);
            overlay.addEventListener('click', function (event) { if (event.target === overlay) close(); });
            form.addEventListener('submit', function (event) {
                event.preventDefault();
                if (reviewer.value === 'CODEX') {
                    if (submit.disabled || posting || typeof options.onCodex !== 'function') return;
                    // Reuse the proven queue path (it reports only what the server answered).
                    close();
                    options.onCodex(number, options.repo || null);
                    return;
                }
                if (submit.disabled || posting || !defaults) return;
                var request = {
                    repo: options.repo || null,
                    reviewer: reviewer.value,
                    wide: mode.value === 'full',
                    plan: mode.value === 'full' ? 'per_file' : plan.value,
                    max_files: mode.value === 'full' ? ceiling : Number(maxFiles.value)
                };
                posting = true;
                mode.disabled = reviewer.disabled = closeButton.disabled = cancel.disabled = true;
                submit.textContent = 'Submitting…';
                status.textContent = 'Submitting one review request…';
                status.classList.remove('rb-pr-analysis-error');
                update();
                fetch(base + '/forge/pr-reviews/' + number + '/analyze', {
                    method: 'POST', credentials: 'same-origin',
                    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(request)
                }).then(readJSON).then(function (data) {
                    accepted = {accepted: true, request: request, response: data};
                    status.textContent = 'Request accepted for ' + request.reviewer + '. Follow the PR review progress; ' +
                        'this does not mean the review has finished or been approved.';
                    submit.textContent = 'Request accepted';
                    cancel.textContent = 'Close';
                    if (typeof options.onAccepted === 'function') {
                        try { options.onAccepted(data); } catch (error) { console.error('[PR analysis refresh]', error); }
                    }
                }).catch(function (error) {
                    status.textContent = (error.message || 'Request outcome unknown.') +
                        ' Check PR status before submitting again. Nothing will be retried automatically.';
                    status.classList.add('rb-pr-analysis-error');
                    submit.textContent = 'Request not confirmed';
                }).finally(function () {
                    posting = false;
                    closeButton.disabled = cancel.disabled = false;
                    // Deliberately no resubmit after an uncertain network outcome.
                    submit.disabled = true;
                    cancel.focus();
                });
            });

            document.body.appendChild(overlay);
            document.addEventListener('keydown', onKey, true);
            mode.focus();
            update();
            fetch(base + '/forge/review-scope', {credentials: 'same-origin', signal: scopeRead.signal})
                .then(readJSON).then(function (data) {
                    if (closed) return;
                    ceiling = Number(data.max_files_ceiling);
                    var initial = options.scope || {};
                    var selectedPlan = initial.plan || data.plan;
                    var selectedFiles = Number(initial.max_files || data.max_files);
                    if (!Number.isInteger(ceiling) || ceiling < 1 || ceiling > 25 ||
                        !['per_file', 'packed'].includes(selectedPlan) || !Number.isInteger(selectedFiles)) {
                        throw new Error('Effective review settings are invalid; reload before starting a review.');
                    }
                    defaults = data;
                    plan.value = selectedPlan;
                    maxFiles.max = String(ceiling);
                    maxFiles.value = String(selectedFiles);
                    update();
                }).catch(function (error) {
                    if (closed) return;
                    status.textContent = 'Cannot load effective review limits: ' + error.message;
                    status.classList.add('rb-pr-analysis-error');
                    submit.disabled = true;
                });
        });
    }

    window.RepairBayPRAnalysis = {open: open};
}());
