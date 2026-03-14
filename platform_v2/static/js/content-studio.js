/**
 * Content Studio — Writing Pipeline + AI Assist
 * External JS for new features added on top of existing inline scripts.
 */
(function () {
    'use strict';

    const API_BASE = '/tools/content-studio';
    let _writingSessionId = null;
    let _pollTimer = null;

    // ─── Helpers ─────────────────────────────────────────────────────────────

    async function api(method, path, body) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body !== undefined) opts.body = JSON.stringify(body);
        const res = await fetch(API_BASE + path, opts);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
    }

    function toast(msg) {
        const el = document.createElement('div');
        el.style.cssText =
            'position:fixed;bottom:1.5rem;right:1.5rem;z-index:99999;' +
            'background:#1a1a2e;border:1px solid var(--cs-accent,#a78bfa);' +
            'color:#aab;padding:0.5rem 1rem;border-radius:4px;font-size:0.7rem;' +
            'font-family:IBM Plex Mono,monospace;';
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 3000);
    }

    function clearEl(el) {
        while (el.firstChild) el.removeChild(el.firstChild);
    }

    // ─── Writing Wizard ───────────────────────────────────────────────────────

    function openWritingWizard() {
        const wizard = document.getElementById('csWritingWizard');
        if (!wizard) return;
        wizard.style.display = 'flex';
        document.getElementById('csWizardInput').style.display = 'block';
        document.getElementById('csWizardPipeline').style.display = 'none';
        document.getElementById('csWritingReview').style.display = 'none';
        const desc = document.getElementById('csWriteDesc');
        if (desc) desc.value = '';
    }

    function closeWritingWizard() {
        const wizard = document.getElementById('csWritingWizard');
        if (wizard) wizard.style.display = 'none';
        if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
        _writingSessionId = null;
    }

    async function startWriting() {
        const desc = document.getElementById('csWriteDesc').value.trim();
        const type = document.getElementById('csWriteType').value;
        const tone = document.getElementById('csWriteTone').value;

        if (!desc) { toast('Please describe what you want to write'); return; }

        document.getElementById('csWizardInput').style.display = 'none';
        document.getElementById('csWizardPipeline').style.display = 'block';

        const stages = ['research', 'outline', 'draft', 'edit', 'seo'];
        renderWritingPipeline(stages, 'research', 'running');

        try {
            const data = await api('POST', '/api/ai/write', { description: desc, type, tone });
            _writingSessionId = data.session_id || data.id || null;
            if (_writingSessionId) {
                pollWritingStatus(_writingSessionId);
            } else if (data.document_id) {
                completeWriting(data.document_id);
            } else {
                renderWritingPipeline(stages, 'seo', 'complete');
                toast('Writing complete');
            }
        } catch (e) {
            toast('Writing request failed: ' + e.message);
            renderWritingPipeline(stages, 'research', 'error');
        }
    }

    function pollWritingStatus(sessionId) {
        const stages = ['research', 'outline', 'draft', 'edit', 'seo'];
        _pollTimer = setInterval(async () => {
            try {
                const data = await api('GET', '/api/ai/write/' + sessionId);
                const stage = data.current_stage || stages[0];
                const status = data.status || 'running';
                renderWritingPipeline(stages, stage, status);

                if (status === 'checkpoint') {
                    clearInterval(_pollTimer); _pollTimer = null;
                    showWritingCheckpoint(data);
                } else if (status === 'complete' || status === 'done') {
                    clearInterval(_pollTimer); _pollTimer = null;
                    if (data.document_id) completeWriting(data.document_id);
                    else toast('Writing complete');
                } else if (status === 'error' || status === 'failed') {
                    clearInterval(_pollTimer); _pollTimer = null;
                    toast('Writing failed: ' + (data.error || 'unknown error'));
                }
            } catch (e) {
                clearInterval(_pollTimer); _pollTimer = null;
                toast('Poll error: ' + e.message);
            }
        }, 3000);
    }

    function renderWritingPipeline(stages, currentStage, status) {
        const container = document.getElementById('csWritingStages');
        if (!container) return;
        clearEl(container);

        const currentIdx = stages.indexOf(currentStage);

        stages.forEach((stage, idx) => {
            const stageEl = document.createElement('div');
            stageEl.className = 'cs-pipeline-stage';

            if (idx < currentIdx) {
                stageEl.classList.add('complete');
            } else if (idx === currentIdx) {
                stageEl.classList.add(status === 'checkpoint' ? 'checkpoint' : 'running');
            }

            const circle = document.createElement('div');
            circle.className = 'cs-pipeline-circle';

            const label = document.createElement('span');
            label.className = 'cs-pipeline-label';
            label.textContent = stage.toUpperCase();

            stageEl.appendChild(circle);
            stageEl.appendChild(label);
            container.appendChild(stageEl);
        });
    }

    function showWritingCheckpoint(data) {
        const reviewEl = document.getElementById('csWritingReview');
        if (!reviewEl) return;
        clearEl(reviewEl);
        reviewEl.style.display = 'block';

        const output = document.createElement('div');
        output.className = 'cs-build-output';
        output.textContent = data.stage_output || data.content || 'Stage complete — ready to continue';

        const approveBtn = document.createElement('button');
        approveBtn.className = 'cs-btn-primary';
        approveBtn.style.marginTop = '0.5rem';
        approveBtn.textContent = 'Approve & Continue';
        approveBtn.addEventListener('click', () => {
            clearEl(reviewEl);
            reviewEl.style.display = 'none';
            if (_writingSessionId) pollWritingStatus(_writingSessionId);
        });

        reviewEl.appendChild(output);
        reviewEl.appendChild(approveBtn);
    }

    async function completeWriting(sessionId) {
        try {
            const data = await api('POST', '/api/ai/write/' + sessionId + '/approve', {});
            closeWritingWizard();
            toast('Document ready!');
            if (data.document_id && typeof switchTab === 'function') {
                // Load in editor if the global switchTab function exists
                switchTab('editor');
            }
        } catch (e) {
            closeWritingWizard();
            toast('Writing complete');
        }
    }

    // ─── AI Assist Toolbar ────────────────────────────────────────────────────

    async function aiAssist(action) {
        const editorEl = document.getElementById('editorContent');
        if (!editorEl) { toast('No editor found'); return; }

        // Get selected text or fall back to full paragraph
        const selection = window.getSelection();
        let text = '';
        let useSelection = false;

        if (selection && selection.toString().trim()) {
            text = selection.toString().trim();
            useSelection = true;
        } else {
            // Walk up from caret to find paragraph
            const anchor = selection && selection.anchorNode;
            const para = anchor ? anchor.parentElement.closest('p,h1,h2,h3,li') : null;
            text = para ? para.textContent.trim() : editorEl.textContent.trim();
        }

        if (!text) { toast('Select some text first'); return; }

        toast('AI working on ' + action + '…');

        try {
            const data = await api('POST', '/api/ai/assist', { text, action });
            const result = data.result || data.text || '';
            if (!result) { toast('No result returned'); return; }

            if (useSelection && selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                range.deleteContents();
                const textNode = document.createTextNode(result);
                range.insertNode(textNode);
                selection.collapse(textNode, textNode.length);
            } else {
                const anchor = selection && selection.anchorNode;
                const para = anchor ? anchor.parentElement.closest('p,h1,h2,h3,li') : null;
                if (para) {
                    clearEl(para);
                    para.textContent = result;
                } else {
                    toast('Could not locate insertion point');
                }
            }

            // Trigger existing word count update if available
            if (typeof updateWordCount === 'function') updateWordCount();
            toast(action + ' applied');
        } catch (e) {
            toast('AI assist failed: ' + e.message);
        }
    }

    // ─── Template List ────────────────────────────────────────────────────────

    const TEMPLATES = [
        { id: 'article', label: 'Article', icon: 'file-text' },
        { id: 'blog_post', label: 'Blog Post', icon: 'rss' },
        { id: 'press_release', label: 'Press Release', icon: 'radio' },
        { id: 'product_review', label: 'Product Review', icon: 'star' },
        { id: 'how_to_guide', label: 'How-To Guide', icon: 'list-checks' },
        { id: 'newsletter', label: 'Newsletter', icon: 'mail' },
        { id: 'marketing_copy', label: 'Marketing Copy', icon: 'megaphone' },
        { id: 'book_chapter', label: 'Book Chapter', icon: 'book-open' },
    ];

    function renderTemplateList() {
        const container = document.getElementById('csTemplateGrid');
        if (!container) return;
        clearEl(container);

        TEMPLATES.forEach(tpl => {
            const card = document.createElement('div');
            card.className = 'cs-tpl-card';

            const icon = document.createElement('i');
            icon.setAttribute('data-lucide', tpl.icon);

            const label = document.createElement('span');
            label.textContent = tpl.label;

            card.appendChild(icon);
            card.appendChild(label);
            card.addEventListener('click', () => {
                const typeEl = document.getElementById('csWriteType');
                if (typeEl) typeEl.value = tpl.id;
                openWritingWizard();
            });

            container.appendChild(card);
        });

        // Re-init lucide icons if available
        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons({ nodes: [container] });
        }
    }

    // ─── Public API ───────────────────────────────────────────────────────────

    window.CS = {
        openWritingWizard,
        closeWritingWizard,
        startWriting,
        pollWritingStatus,
        renderWritingPipeline,
        showWritingCheckpoint,
        completeWriting,
        aiAssist,
        renderTemplateList,
    };

    // Close wizard on backdrop click
    document.addEventListener('DOMContentLoaded', () => {
        const wizard = document.getElementById('csWritingWizard');
        if (wizard) {
            wizard.addEventListener('click', e => {
                if (e.target === wizard) closeWritingWizard();
            });
        }
    });
})();
