/**
 * Improvements Lab Main Application
 * State management and initialization
 */

const ImprovementsApp = {
    // Application state
    state: {
        proposals: [],
        currentProposal: null,
        currentSandbox: null,
        filters: {
            status: 'all',
            category: 'all',
            priority: 'all'
        },
        queue: {
            current: null,
            waiting: []
        },
        stats: {
            total: 0,
            pending: 0,
            testing: 0,
            deployed: 0,
            escalated: 0
        }
    },

    // ==================== INITIALIZATION ====================

    async init() {
        console.log('🚀 Initializing Improvements Lab...');

        // Initialize UI utilities
        ImprovementsUI.init();

        // Setup event listeners
        this.setupEventListeners();

        // Load initial data
        await this.loadProposals();
        await this.loadQueueStatus();
        await this.loadStats();

        // Start auto-refresh
        this.startAutoRefresh();

        console.log('✅ Improvements Lab initialized');
    },

    setupEventListeners() {
        // Filter changes
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.handleFilterClick(e));
        });

        // Category filter
        const categorySelect = document.getElementById('category-filter');
        if (categorySelect) {
            categorySelect.addEventListener('change', (e) => {
                this.state.filters.category = e.target.value;
                this.renderProposals();
            });
        }

        // New proposal button
        const newProposalBtn = document.getElementById('new-proposal-btn');
        if (newProposalBtn) {
            newProposalBtn.addEventListener('click', () => this.openNewProposalModal());
        }
    },

    startAutoRefresh() {
        // Refresh every 30 seconds
        setInterval(() => {
            this.loadQueueStatus();
            this.loadStats();
        }, 30000);
    },

    // ==================== DATA LOADING ====================

    async loadProposals() {
        const container = document.getElementById('proposals-container');
        if (container) {
            ImprovementsUI.showLoading(container, 'Loading proposals...');
        }

        try {
            const data = await ImprovementsAPI.getProposals();

            if (data.success) {
                this.state.proposals = data.proposals || [];
                this.renderProposals();
            } else {
                ImprovementsUI.error('Failed to load proposals: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error loading proposals: ' + error.message);
            if (container) {
                ImprovementsUI.showEmpty(container, 'Failed to load proposals', '❌');
            }
        }
    },

    async loadQueueStatus() {
        try {
            const data = await ImprovementsAPI.getQueueStatus();
            if (data.success) {
                this.state.queue = {
                    current: data.active_proposal_id,
                    waiting: data.queue || [],
                    size: data.queue_size || 0
                };
                this.renderQueueStatus();
            }
        } catch (error) {
            console.error('Failed to load queue status:', error);
        }
    },

    async loadStats() {
        try {
            const data = await ImprovementsAPI.getStats();
            if (data.success) {
                this.state.stats = data.stats || {};
                this.renderStats();
            }
        } catch (error) {
            console.error('Failed to load stats:', error);
        }
    },

    // ==================== RENDERING ====================

    renderProposals() {
        const container = document.getElementById('proposals-container');
        if (!container) return;

        // Apply filters
        let filtered = this.state.proposals;

        // Status filter with legacy status support
        // Maps legacy statuses to their modern equivalents for filtering
        if (this.state.filters.status !== 'all') {
            const statusFilter = this.state.filters.status;
            // Group legacy and modern statuses together
            const statusGroups = {
                'pending': ['pending', 'proposed'],
                'approved': ['approved', 'pending_approval'],
                'tested': ['tested', 'ready_for_review'],
                'deployed': ['deployed', 'completed']
            };
            const matchStatuses = statusGroups[statusFilter] || [statusFilter];
            filtered = filtered.filter(p => matchStatuses.includes(p.status));
        }

        if (this.state.filters.category !== 'all') {
            filtered = filtered.filter(p => p.category === this.state.filters.category);
        }

        if (this.state.filters.priority !== 'all') {
            filtered = filtered.filter(p => p.priority === this.state.filters.priority);
        }

        if (filtered.length === 0) {
            ImprovementsUI.showEmpty(container, 'No proposals match your filters', '📭');
            return;
        }

        container.innerHTML = filtered.map(proposal => this.renderProposalCard(proposal)).join('');
    },

    renderProposalCard(proposal) {
        const statusColor = ImprovementsUI.getStatusColor(proposal.status);
        const statusIcon = ImprovementsUI.getStatusIcon(proposal.status);
        const priorityColor = ImprovementsUI.getPriorityColor(proposal.priority);

        const retryInfo = proposal.test_retry_count > 0
            ? `<span style="color:#FFA500;">Retries: ${proposal.test_retry_count}/3</span>`
            : '';

        const escalationBadge = proposal.escalation_status === 'contractor_consulting'
            ? '<span style="background:rgba(255,0,0,0.2);padding:2px 8px;border-radius:4px;color:#FF6B6B;font-size:0.75rem;">ESCALATED</span>'
            : '';

        // Parse metadata for multi-agent analysis
        let metadata = proposal.metadata || {};
        if (typeof metadata === 'string') {
            try { metadata = JSON.parse(metadata); } catch (e) { metadata = {}; }
        }

        const multiAgentBadge = metadata.multi_agent_analysis
            ? `<span style="background:rgba(139,92,246,0.2);padding:2px 8px;border-radius:4px;color:#8B5CF6;font-size:0.75rem;">🤖 MULTI-AGENT (${metadata.multi_agent_analysis.agents_consulted || 0})</span>`
            : '';

        const recommendedAgent = metadata.recommended_assignee
            ? `<div style="margin-top:8px;padding:8px;background:rgba(139,92,246,0.1);border-radius:4px;font-size:0.8rem;">
                <span style="color:#8B5CF6;">👤 Recommended:</span>
                <span style="color:#fff;">${metadata.recommended_assignee.name}</span>
                <span style="color:#666;"> (${metadata.recommended_assignee.tier})</span>
               </div>`
            : '';

        return `
            <div class="proposal-card" data-id="${proposal.id}" onclick="ImprovementsApp.openProposalDetail(${proposal.id})" style="
                border: 1px solid ${statusColor}40;
                background: ${statusColor}10;
                padding: 15px;
                border-radius: 8px;
                cursor: pointer;
                transition: all 0.2s;
                margin-bottom: 10px;
            ">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
                    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                        <span style="color:#666;font-size:0.9rem;">#${proposal.id}</span>
                        <span style="color:${statusColor};font-weight:bold;">${statusIcon} ${proposal.status.toUpperCase()}</span>
                        ${escalationBadge}
                        ${multiAgentBadge}
                    </div>
                    <span style="color:${priorityColor};font-size:0.8rem;text-transform:uppercase;">${proposal.priority}</span>
                </div>

                <h3 style="margin:0 0 10px 0;color:#fff;font-size:1rem;">${proposal.title}</h3>

                <div style="display:flex;gap:15px;font-size:0.85rem;color:#888;">
                    <span>📂 ${proposal.category}</span>
                    ${retryInfo}
                    <span>📅 ${ImprovementsUI.formatRelativeTime(proposal.proposed_at)}</span>
                </div>

                ${recommendedAgent}

                ${proposal.contractor_agent_id ? `
                    <div style="margin-top:10px;padding-top:10px;border-top:1px solid #333;font-size:0.85rem;color:#FF6B6B;">
                        🤝 Contractor assigned - awaiting response
                    </div>
                ` : ''}
            </div>
        `;
    },

    renderQueueStatus() {
        const container = document.getElementById('queue-status');
        if (!container) return;

        const { current, size } = this.state.queue;

        container.innerHTML = `
            <div style="display:flex;align-items:center;gap:15px;">
                <span style="font-size:1.2rem;">📋</span>
                <div>
                    <div style="color:#00FFFF;font-weight:bold;">Queue Status</div>
                    <div style="font-size:0.85rem;color:#888;">
                        ${current ? `Testing: Proposal #${current}` : 'No active testing'}
                        ${size > 0 ? ` | ${size} waiting` : ''}
                    </div>
                </div>
            </div>
        `;
    },

    renderStats() {
        const stats = this.state.stats;

        // Update individual stat elements by ID
        const statTotal = document.getElementById('stat-total');
        const statPending = document.getElementById('stat-pending');
        const statApproved = document.getElementById('stat-approved');
        const statTested = document.getElementById('stat-tested');
        const statDeployed = document.getElementById('stat-deployed');

        if (statTotal) statTotal.textContent = stats.total || 0;
        if (statPending) statPending.textContent = stats.pending || 0;
        if (statApproved) statApproved.textContent = stats.approved || 0;
        if (statTested) statTested.textContent = stats.tested || 0;
        if (statDeployed) statDeployed.textContent = stats.deployed || 0;
    },

    // ==================== FILTERS ====================

    handleFilterClick(e) {
        const btn = e.target.closest('.filter-btn');
        if (!btn) return;

        const filterType = btn.dataset.filterType || 'status';
        const filterValue = btn.dataset.filter;

        // Update active state
        document.querySelectorAll(`.filter-btn[data-filter-type="${filterType}"]`).forEach(b => {
            b.classList.remove('active');
        });
        btn.classList.add('active');

        // Update filter and re-render
        this.state.filters[filterType] = filterValue;
        this.renderProposals();
    },

    // ==================== PROPOSAL DETAIL ====================

    async openProposalDetail(proposalId) {
        ImprovementsUI.info('Loading proposal details...');

        try {
            // Fetch proposal and sandbox in parallel
            const [proposalData, sandboxData, retryData] = await Promise.all([
                ImprovementsAPI.getProposal(proposalId),
                ImprovementsAPI.getSandbox(proposalId).catch(() => ({ success: false })),
                ImprovementsAPI.getRetryStatus(proposalId).catch(() => ({ success: false }))
            ]);

            if (!proposalData.success) {
                ImprovementsUI.error('Failed to load proposal');
                return;
            }

            this.state.currentProposal = proposalData.proposal;
            this.state.currentSandbox = sandboxData.success ? sandboxData.sandbox : null;

            const retryStatus = retryData.success ? retryData : null;

            this.showProposalDetailModal(proposalData.proposal, this.state.currentSandbox, retryStatus);

        } catch (error) {
            ImprovementsUI.error('Error loading proposal: ' + error.message);
        }
    },

    showProposalDetailModal(proposal, sandbox, retryStatus) {
        const content = document.createElement('div');
        content.innerHTML = this.buildProposalDetailHTML(proposal, sandbox, retryStatus);

        ImprovementsUI.showModal({
            title: `Proposal #${proposal.id}: ${proposal.title}`,
            content,
            size: 'large'
        });

        // If escalated, load chat history
        if (proposal.escalation_status === 'contractor_consulting') {
            this.loadChatHistory(proposal.id);
        }
    },

    buildProposalDetailHTML(proposal, sandbox, retryStatus) {
        const statusColor = ImprovementsUI.getStatusColor(proposal.status);

        return `
            <div style="display:grid;gap:20px;">
                <!-- Proposal Info -->
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
                    <div style="border:1px solid #00FFFF;border-radius:8px;padding:15px;background:rgba(0,255,255,0.05);">
                        <h4 style="margin:0 0 15px 0;color:#00FFFF;">📋 Details</h4>
                        <div style="display:grid;gap:8px;font-size:0.9rem;">
                            <div><span style="color:#888;">Status:</span> <span style="color:${statusColor};font-weight:bold;">${proposal.status.toUpperCase()}</span></div>
                            <div><span style="color:#888;">Category:</span> <span style="color:#fff;">${proposal.category}</span></div>
                            <div><span style="color:#888;">Priority:</span> <span style="color:${ImprovementsUI.getPriorityColor(proposal.priority)};">${proposal.priority}</span></div>
                            <div><span style="color:#888;">Created:</span> <span style="color:#fff;">${ImprovementsUI.formatDate(proposal.proposed_at)}</span></div>
                        </div>
                    </div>

                    <!-- Sandbox Info -->
                    <div style="border:1px solid #FFA500;border-radius:8px;padding:15px;background:rgba(255,165,0,0.05);">
                        <h4 style="margin:0 0 15px 0;color:#FFA500;">🧪 Sandbox</h4>
                        ${sandbox ? `
                            <div style="display:grid;gap:8px;font-size:0.9rem;">
                                <div><span style="color:#888;">ID:</span> <span style="color:#fff;">#${sandbox.id}</span></div>
                                <div><span style="color:#888;">Type:</span> <span style="color:#fff;">${sandbox.sandbox_type}</span></div>
                                <div><span style="color:#888;">Status:</span> <span style="color:#00FF00;">${sandbox.status}</span></div>
                            </div>
                            <div style="margin-top:15px;display:flex;gap:10px;">
                                <button class="btn btn-primary" onclick="ImprovementsApp.runTests(${sandbox.id}, ${proposal.id})">▶️ Run Tests</button>
                                <button class="btn" onclick="ImprovementsApp.viewLogs(${sandbox.id}, ${proposal.id})">📄 Logs</button>
                                <button class="btn btn-danger" onclick="ImprovementsApp.destroySandbox(${sandbox.id})">🗑️ Destroy</button>
                            </div>
                        ` : `
                            <p style="color:#888;margin:0 0 15px 0;">No sandbox created yet</p>
                            <button class="btn btn-primary" onclick="ImprovementsApp.createSandbox(${proposal.id})">🧪 Create Sandbox</button>
                        `}
                    </div>
                </div>

                <!-- Retry Status -->
                ${retryStatus ? `
                    <div style="border:1px solid #FF6B6B;border-radius:8px;padding:15px;background:rgba(255,107,107,0.05);">
                        <h4 style="margin:0 0 15px 0;color:#FF6B6B;">🔄 Retry Status</h4>
                        <div style="display:flex;align-items:center;gap:20px;">
                            <div style="font-size:1.5rem;">
                                ${'●'.repeat(retryStatus.retry_count)}${'○'.repeat(3 - retryStatus.retry_count)}
                            </div>
                            <div>
                                <div style="font-size:0.9rem;color:#fff;">Attempts: ${retryStatus.retry_count} / ${retryStatus.max_retries}</div>
                                <div style="font-size:0.85rem;color:#888;">Escalation: ${retryStatus.escalation_status || 'none'}</div>
                            </div>
                            ${retryStatus.retry_count > 0 ? `
                                <button class="btn btn-warning" onclick="ImprovementsApp.resetRetries(${proposal.id})">🔄 Reset Retries</button>
                            ` : ''}
                        </div>
                    </div>
                ` : ''}

                <!-- Test Results -->
                ${sandbox && sandbox.test_results ? `
                    <div style="border:1px solid #00FF00;border-radius:8px;padding:15px;background:rgba(0,255,0,0.05);">
                        <h4 style="margin:0 0 15px 0;color:#00FF00;">🔬 Test Results</h4>
                        <div style="display:flex;gap:20px;margin-bottom:15px;">
                            <div><span style="color:#00FF00;font-size:1.2rem;font-weight:bold;">${sandbox.test_results.passed || 0}</span> <span style="color:#888;">Passed</span></div>
                            <div><span style="color:#FF0000;font-size:1.2rem;font-weight:bold;">${sandbox.test_results.failed || 0}</span> <span style="color:#888;">Failed</span></div>
                            <div><span style="color:#888;">${sandbox.test_results.duration || 0}s</span></div>
                        </div>
                    </div>
                ` : ''}

                <!-- Escalation / Chat Panel -->
                ${proposal.escalation_status === 'contractor_consulting' ? `
                    <div style="border:2px solid #FF6B6B;border-radius:8px;padding:15px;background:rgba(255,107,107,0.05);">
                        <h4 style="margin:0 0 15px 0;color:#FF6B6B;">💬 Contractor Consultation</h4>
                        <div id="chat-messages" style="max-height:300px;overflow-y:auto;margin-bottom:15px;padding:10px;background:rgba(0,0,0,0.3);border-radius:4px;">
                            <div style="color:#888;text-align:center;">Loading chat history...</div>
                        </div>
                        <div style="display:flex;gap:10px;">
                            <input type="text" id="chat-input" placeholder="Type your message..." style="flex:1;padding:10px;background:rgba(0,0,0,0.3);border:1px solid #444;border-radius:4px;color:#fff;">
                            <button class="btn btn-primary" onclick="ImprovementsApp.sendChatMessage(${proposal.id})">Send</button>
                        </div>
                        <div style="margin-top:15px;display:flex;gap:10px;">
                            <button class="btn btn-primary" onclick="ImprovementsApp.applyContractorFix(${proposal.id})">✅ Apply Fix</button>
                            <button class="btn btn-warning" onclick="ImprovementsApp.tryAnotherContractor(${proposal.id})">🔄 Try Another</button>
                            <button class="btn btn-danger" onclick="ImprovementsApp.escalateToHumanOnly(${proposal.id})">⚠️ Human Only</button>
                        </div>
                    </div>
                ` : ''}

                <!-- Actions -->
                <div style="border-top:1px solid #333;padding-top:15px;display:flex;gap:10px;flex-wrap:wrap;">
                    ${['pending', 'proposed'].includes(proposal.status) ? `
                        <button class="btn btn-primary" onclick="ImprovementsApp.approveProposal(${proposal.id})">✅ Approve</button>
                        <button class="btn btn-danger" onclick="ImprovementsApp.rejectProposal(${proposal.id})">❌ Reject</button>
                    ` : ''}
                    ${['approved', 'pending_approval'].includes(proposal.status) ? `
                        <button class="btn btn-primary" onclick="ImprovementsApp.testInSandbox(${proposal.id})">🧪 Test in Sandbox</button>
                    ` : ''}
                    ${['tested', 'ready_for_review'].includes(proposal.status) ? `
                        <button class="btn btn-primary" onclick="ImprovementsApp.deployProposal(${proposal.id})">🚀 Deploy to Production</button>
                    ` : ''}
                    ${['pending', 'proposed', 'approved', 'pending_approval'].includes(proposal.status) ? `
                        <button class="btn btn-warning" onclick="ImprovementsApp.regeneratePlan(${proposal.id})">🔄 Regenerate Plan</button>
                    ` : ''}
                    <button class="btn btn-danger" onclick="ImprovementsApp.deleteProposal(${proposal.id})">🗑️ Delete</button>
                </div>
            </div>
        `;
    },

    // ==================== ACTIONS ====================

    async runTests(sandboxId, proposalId) {
        ImprovementsUI.info('Running tests...');

        try {
            const data = await ImprovementsAPI.runSandboxTests(sandboxId, proposalId);

            if (data.success) {
                const results = data.test_results || {};
                if (results.passed === results.total && results.total > 0) {
                    ImprovementsUI.success(`✅ All tests passed! ${results.passed}/${results.total}`);
                } else {
                    ImprovementsUI.warning(`Tests completed: ${results.passed || 0}/${results.total || 0} passed`);
                }
                // Refresh proposal detail
                this.openProposalDetail(proposalId);
            } else {
                ImprovementsUI.error('Tests failed: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error running tests: ' + error.message);
        }
    },

    async viewLogs(sandboxId, proposalId = null) {
        ImprovementsUI.info('Loading logs...');

        try {
            const data = await ImprovementsAPI.getSandboxLogs(sandboxId);

            if (data.success) {
                const logs = data.logs || 'No logs available';

                // Check if there are errors in the logs
                const hasErrors = logs.includes('❌') || logs.includes('FAILED') || logs.includes('Error:');

                // Build content with optional Request Fix button
                let content = `<pre style="background:#0a0a1a;padding:15px;border-radius:4px;overflow:auto;max-height:50vh;white-space:pre-wrap;word-wrap:break-word;font-size:12px;color:#00FF00;">${logs.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>`;

                if (hasErrors) {
                    content += `
                        <div style="margin-top:15px;padding:15px;background:#2a1a1a;border:1px solid #ff4444;border-radius:4px;">
                            <p style="color:#ff6666;margin:0 0 10px 0;"><strong>⚠️ Errors detected in logs</strong></p>
                            <button class="btn btn-warning" onclick="ImprovementsApp.requestFix(${sandboxId}, ${proposalId || 'null'})">
                                🔧 Request Fix from Team
                            </button>
                            <button class="btn" onclick="ImprovementsApp.clearOldTestResults(${sandboxId})" style="margin-left:10px;">
                                🗑️ Clear Old Results
                            </button>
                        </div>`;
                }

                ImprovementsUI.showModal({
                    title: `📄 Sandbox #${sandboxId} Logs`,
                    content: content,
                    size: 'large'
                });
            } else {
                ImprovementsUI.error('Failed to load logs: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error loading logs: ' + error.message);
        }
    },

    async createSandbox(proposalId) {
        ImprovementsUI.info('Creating sandbox...');

        try {
            const data = await ImprovementsAPI.createSandbox(proposalId);

            if (data.success) {
                ImprovementsUI.success('Sandbox created successfully');
                this.openProposalDetail(proposalId);
            } else {
                ImprovementsUI.error('Failed to create sandbox: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error creating sandbox: ' + error.message);
        }
    },

    async destroySandbox(sandboxId) {
        const confirmed = await ImprovementsUI.confirm('Are you sure you want to destroy this sandbox?', 'Destroy Sandbox');
        if (!confirmed) return;

        ImprovementsUI.info('Destroying sandbox...');

        try {
            const data = await ImprovementsAPI.destroySandbox(sandboxId);

            if (data.success) {
                ImprovementsUI.success('Sandbox destroyed');
                this.loadProposals();
            } else {
                ImprovementsUI.error('Failed to destroy sandbox: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error destroying sandbox: ' + error.message);
        }
    },

    async approveProposal(proposalId) {
        const confirmed = await ImprovementsUI.confirm('Approve this proposal?', 'Approve Proposal');
        if (!confirmed) return;

        try {
            const data = await ImprovementsAPI.approveProposal(proposalId);
            if (data.success) {
                ImprovementsUI.success('Proposal approved');
                this.loadProposals();
                // Close all modals (confirmation may still be animating out)
                document.querySelectorAll('.modal-overlay').forEach(m => m.remove());
                document.body.style.overflow = '';
            } else {
                ImprovementsUI.error('Failed to approve: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async rejectProposal(proposalId) {
        const confirmed = await ImprovementsUI.confirm('Reject this proposal?', 'Reject Proposal');
        if (!confirmed) return;

        try {
            const data = await ImprovementsAPI.rejectProposal(proposalId);
            if (data.success) {
                ImprovementsUI.success('Proposal rejected');
                this.loadProposals();
                // Close all modals (confirmation may still be animating out)
                document.querySelectorAll('.modal-overlay').forEach(m => m.remove());
                document.body.style.overflow = '';
            } else {
                ImprovementsUI.error('Failed to reject: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async executeProposal(proposalId) {
        const confirmed = await ImprovementsUI.confirm('Execute this proposal? This will create a sandbox and apply changes.', 'Execute Proposal');
        if (!confirmed) return;

        ImprovementsUI.info('Executing proposal...');

        try {
            const data = await ImprovementsAPI.executeProposal(proposalId);
            if (data.success) {
                ImprovementsUI.success('Proposal execution started');
                this.openProposalDetail(proposalId);
            } else {
                ImprovementsUI.error('Failed to execute: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async testInSandbox(proposalId) {
        const confirmed = await ImprovementsUI.confirm(
            'Test this proposal in sandbox? This will:\n1. Create a sandbox environment\n2. Apply changes safely\n3. Run automated tests\n\nAfter tests pass, you can deploy to production.',
            'Test in Sandbox'
        );
        if (!confirmed) return;

        ImprovementsUI.info('Setting up sandbox testing...');

        try {
            // Step 1: Check if sandbox exists, create if needed
            let sandboxData = await ImprovementsAPI.getSandbox(proposalId).catch(() => ({ success: false }));

            if (!sandboxData.success || !sandboxData.sandbox) {
                ImprovementsUI.info('Creating sandbox environment...');
                const createResult = await ImprovementsAPI.createSandbox(proposalId);
                if (!createResult.success) {
                    ImprovementsUI.error('Failed to create sandbox: ' + (createResult.error || 'Unknown error'));
                    return;
                }
                sandboxData = { success: true, sandbox: createResult.sandbox };
                ImprovementsUI.success('Sandbox created');
            }

            const sandboxId = sandboxData.sandbox?.id;
            if (!sandboxId) {
                ImprovementsUI.error('Could not get sandbox ID');
                return;
            }

            // Step 2: Run tests
            ImprovementsUI.info('Running tests in sandbox...');
            const testResult = await ImprovementsAPI.runSandboxTests(sandboxId, proposalId);

            if (testResult.success) {
                const results = testResult.test_results || {};
                const allPassed = results.passed === results.total && results.total > 0;

                if (allPassed) {
                    ImprovementsUI.success(`All tests passed! (${results.passed}/${results.total}) - Ready for deployment`);
                } else {
                    ImprovementsUI.warning(`Tests completed: ${results.passed || 0}/${results.total || 0} passed. Review results before deploying.`);
                }
            } else {
                ImprovementsUI.error('Test run failed: ' + (testResult.error || 'Unknown error'));
            }

            // Refresh proposal detail to show updated status
            this.openProposalDetail(proposalId);
            this.loadProposals();

        } catch (error) {
            ImprovementsUI.error('Error during sandbox testing: ' + error.message);
        }
    },

    async deployProposal(proposalId) {
        const confirmed = await ImprovementsUI.confirm('Deploy this proposal to production?', 'Deploy to Production');
        if (!confirmed) return;

        ImprovementsUI.info('Deploying to production...');

        try {
            const data = await ImprovementsAPI.deployToProduction(proposalId);

            // Close all modals (confirmation may still be animating out)
            document.querySelectorAll('.modal-overlay').forEach(m => m.remove());
            document.body.style.overflow = '';

            if (data.success) {
                // Show deployment result with diff
                this.showDeploymentResult(data);
                this.loadProposals();
            } else {
                ImprovementsUI.error('Failed to deploy: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    showDeploymentResult(data) {
        const filesCount = data.files_modified || 0;
        const restartRequired = data.restart_required || false;
        const deploymentLog = data.deployment_log || [];

        // Format the deployment log as HTML
        const logHtml = deploymentLog.map(line => {
            if (line.includes('✅')) return `<div style="color:#00FF00;">${line}</div>`;
            if (line.includes('❌')) return `<div style="color:#FF4444;">${line}</div>`;
            if (line.includes('⚠️')) return `<div style="color:#FFA500;">${line}</div>`;
            if (line.includes('OLD:')) return `<div style="color:#FF6B6B;background:rgba(255,0,0,0.1);padding:2px 5px;margin:2px 0;">- ${line}</div>`;
            if (line.includes('NEW:')) return `<div style="color:#00FF00;background:rgba(0,255,0,0.1);padding:2px 5px;margin:2px 0;">+ ${line}</div>`;
            return `<div style="color:#888;">${line}</div>`;
        }).join('');

        const content = `
            <div style="padding:20px;">
                <h3 style="color:#00FF00;margin:0 0 15px 0;">✅ Deployment Successful</h3>
                <div style="margin-bottom:15px;">
                    <strong>Files Modified:</strong> ${filesCount}
                </div>
                ${restartRequired ? `
                    <div style="background:rgba(255,165,0,0.2);border:1px solid #FFA500;padding:15px;border-radius:8px;margin-bottom:15px;">
                        <strong style="color:#FFA500;">⚠️ Restart Required</strong>
                        <p style="margin:10px 0 0 0;color:#ccc;">Python files were modified. The platform needs to restart for changes to take effect.</p>
                        <button class="btn btn-warning" onclick="ImprovementsApp.restartPlatform()" style="margin-top:10px;">
                            🔄 Restart Platform Now
                        </button>
                    </div>
                ` : ''}
                <div style="margin-top:15px;">
                    <strong>Deployment Log:</strong>
                    <div style="background:#111;border:1px solid #333;border-radius:4px;padding:10px;margin-top:10px;max-height:300px;overflow-y:auto;font-family:monospace;font-size:0.85rem;">
                        ${logHtml}
                    </div>
                </div>
            </div>
        `;

        ImprovementsUI.showModal({
            title: 'Deployment Complete',
            content: content,
            size: 'large',
            closable: true
        });
    },

    async restartPlatform() {
        const confirmed = await ImprovementsUI.confirm('Restart the platform? This will briefly interrupt service.', 'Restart Platform');
        if (!confirmed) return;

        ImprovementsUI.info('Restarting platform...');

        try {
            const response = await fetch('/tools/improvements-lab/restart-platform', { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                ImprovementsUI.success('Platform restart initiated. Page will reload in 5 seconds...');
                setTimeout(() => window.location.reload(), 5000);
            } else {
                ImprovementsUI.error('Failed to restart: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Restart failed: ' + error.message);
        }
    },

    async deleteProposal(proposalId) {
        const confirmed = await ImprovementsUI.confirm('Are you sure you want to delete this proposal? This cannot be undone.', 'Delete Proposal');
        if (!confirmed) return;

        try {
            const data = await ImprovementsAPI.deleteProposal(proposalId);
            if (data.success) {
                ImprovementsUI.success('Proposal deleted');
                this.loadProposals();
                // Close all modals (confirmation may still be animating out)
                document.querySelectorAll('.modal-overlay').forEach(m => m.remove());
                document.body.style.overflow = '';
            } else {
                ImprovementsUI.error('Failed to delete: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async resetRetries(proposalId) {
        const confirmed = await ImprovementsUI.confirm('Reset retry count to 0?', 'Reset Retries');
        if (!confirmed) return;

        try {
            const data = await ImprovementsAPI.resetRetries(proposalId);
            if (data.success) {
                ImprovementsUI.success('Retries reset');
                this.openProposalDetail(proposalId);
            } else {
                ImprovementsUI.error('Failed to reset: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async regeneratePlan(proposalId) {
        const confirmed = await ImprovementsUI.confirm('Regenerate implementation plan for this proposal? This will use AI to create a new plan based on the proposal description.', 'Regenerate Plan');
        if (!confirmed) return;

        ImprovementsUI.info('Regenerating implementation plan...');

        try {
            const data = await ImprovementsAPI.regeneratePlan(proposalId);
            if (data.success) {
                ImprovementsUI.success(data.message || 'Implementation plan regenerated successfully');
                // Refresh the proposal detail to show the new plan
                this.openProposalDetail(proposalId);
            } else {
                ImprovementsUI.error('Failed to regenerate plan: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async requestFix(sandboxId, proposalId) {
        // Show team member selection dialog
        ImprovementsUI.info('Loading team members...');

        try {
            // Get available team members
            const teamData = await ImprovementsAPI.getAvailableAgents();

            if (!teamData.success || !teamData.agents || teamData.agents.length === 0) {
                ImprovementsUI.error('No team members available');
                return;
            }

            // Build selection dialog
            const agentOptions = teamData.agents.map(agent =>
                `<option value="${agent.id}">${agent.name} (${agent.role || agent.department || 'General'})</option>`
            ).join('');

            const content = `
                <div style="padding: 10px;">
                    <p style="margin-bottom: 15px;">Select a team member to fix the test errors:</p>
                    <select id="fix-agent-select" class="form-control" style="width:100%;padding:10px;margin-bottom:15px;">
                        <option value="">-- Select Team Member --</option>
                        <option value="auto">🤖 Auto-assign (Best Match)</option>
                        ${agentOptions}
                    </select>
                    <textarea id="fix-notes" class="form-control" placeholder="Additional notes for the assignee..."
                        style="width:100%;height:80px;padding:10px;margin-bottom:15px;"></textarea>
                    <button class="btn btn-primary" onclick="ImprovementsApp.submitFixRequest(${sandboxId}, ${proposalId})">
                        📤 Submit Fix Request
                    </button>
                </div>
            `;

            ImprovementsUI.showModal({
                title: '🔧 Request Fix from Team',
                content: content,
                size: 'medium'
            });

        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async submitFixRequest(sandboxId, proposalId) {
        const agentSelect = document.getElementById('fix-agent-select');
        const notesInput = document.getElementById('fix-notes');

        if (!agentSelect || !agentSelect.value) {
            ImprovementsUI.error('Please select a team member');
            return;
        }

        const agentId = agentSelect.value === 'auto' ? null : parseInt(agentSelect.value);
        const notes = notesInput ? notesInput.value : '';

        ImprovementsUI.info('Submitting fix request...');

        try {
            const data = await ImprovementsAPI.requestFix(sandboxId, proposalId, agentId, notes);

            if (data.success) {
                ImprovementsUI.success(data.message || 'Fix request submitted successfully');
                ImprovementsUI.closeModal();

                // Refresh proposal if we have the ID
                if (proposalId) {
                    this.openProposalDetail(proposalId);
                }
            } else {
                ImprovementsUI.error('Failed to submit: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async clearOldTestResults(sandboxId) {
        const confirmed = await ImprovementsUI.confirm('Clear old test results? This will remove historical test data and keep only the most recent run.', 'Clear Results');
        if (!confirmed) return;

        ImprovementsUI.info('Clearing old test results...');

        try {
            const data = await ImprovementsAPI.clearTestResults(sandboxId);

            if (data.success) {
                ImprovementsUI.success(data.message || 'Old test results cleared');
                ImprovementsUI.closeModal();
            } else {
                ImprovementsUI.error('Failed to clear: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    // ==================== CHAT ====================

    async loadChatHistory(proposalId) {
        const container = document.getElementById('chat-messages');
        if (!container) return;

        try {
            const data = await ImprovementsAPI.getChatHistory(proposalId);

            if (data.success && data.messages && data.messages.length > 0) {
                container.innerHTML = data.messages.map(msg => this.renderChatMessage(msg)).join('');
                container.scrollTop = container.scrollHeight;
            } else {
                container.innerHTML = '<div style="color:#888;text-align:center;">No messages yet</div>';
            }
        } catch (error) {
            container.innerHTML = '<div style="color:#FF6B6B;text-align:center;">Failed to load chat</div>';
        }
    },

    renderChatMessage(msg) {
        const colors = {
            human: '#00FFFF',
            contractor: '#FF6B6B',
            agent: '#FFA500',
            system: '#888'
        };

        const color = colors[msg.sender?.type] || '#888';
        const name = msg.sender?.name || msg.sender?.type || 'Unknown';

        return `
            <div style="margin-bottom:10px;padding:10px;background:rgba(255,255,255,0.05);border-radius:4px;border-left:3px solid ${color};">
                <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
                    <span style="color:${color};font-weight:bold;">${name}</span>
                    <span style="color:#666;font-size:0.75rem;">${ImprovementsUI.formatRelativeTime(msg.created_at)}</span>
                </div>
                <div style="color:#fff;white-space:pre-wrap;">${msg.content}</div>
            </div>
        `;
    },

    async sendChatMessage(proposalId) {
        const input = document.getElementById('chat-input');
        if (!input || !input.value.trim()) return;

        const message = input.value.trim();
        input.value = '';

        ImprovementsUI.info('Sending message...');

        try {
            const data = await ImprovementsAPI.sendChatMessage(proposalId, message);

            if (data.success) {
                ImprovementsUI.success('Message sent');
                this.loadChatHistory(proposalId);
            } else {
                ImprovementsUI.error('Failed to send: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async applyContractorFix(proposalId) {
        const confirmed = await ImprovementsUI.confirm('Apply the contractor\'s proposed fix?', 'Apply Fix');
        if (!confirmed) return;

        ImprovementsUI.info('Applying fix...');

        try {
            const data = await ImprovementsAPI.applyContractorFix(proposalId);
            if (data.success) {
                ImprovementsUI.success('Fix applied, re-testing...');
                this.loadProposals();
                // Close all modals (confirmation may still be animating out)
                document.querySelectorAll('.modal-overlay').forEach(m => m.remove());
                document.body.style.overflow = '';
            } else {
                ImprovementsUI.error('Failed to apply: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async tryAnotherContractor(proposalId) {
        const confirmed = await ImprovementsUI.confirm('Try a different AI contractor?', 'Change Contractor');
        if (!confirmed) return;

        try {
            const data = await ImprovementsAPI.tryAnotherContractor(proposalId);
            if (data.success) {
                ImprovementsUI.success('Switched to new contractor');
                this.openProposalDetail(proposalId);
            } else {
                ImprovementsUI.error('Failed: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    },

    async escalateToHumanOnly(proposalId) {
        const confirmed = await ImprovementsUI.confirm('Mark this as too complex for AI? It will require manual human investigation.', 'Human Only');
        if (!confirmed) return;

        try {
            const data = await ImprovementsAPI.escalateToHumanOnly(proposalId);
            if (data.success) {
                ImprovementsUI.warning('Marked for human investigation');
                this.loadProposals();
                // Close all modals (confirmation may still be animating out)
                document.querySelectorAll('.modal-overlay').forEach(m => m.remove());
                document.body.style.overflow = '';
            } else {
                ImprovementsUI.error('Failed: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            ImprovementsUI.error('Error: ' + error.message);
        }
    }
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => ImprovementsApp.init());
