/**
 * Improvements Lab API Module
 * Centralized API calls for the Improvements Lab
 *
 * All API calls go through this module for consistency
 */

const ImprovementsAPI = {
    baseUrl: '/tools/improvements-lab',

    /**
     * Generic fetch wrapper with error handling
     */
    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin'
        };

        try {
            const response = await fetch(url, { ...defaultOptions, ...options });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }

            return data;
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            throw error;
        }
    },

    // ==================== PROPOSALS ====================

    /**
     * Get all proposals with optional filters
     */
    async getProposals(filters = {}) {
        const params = new URLSearchParams();
        if (filters.status) params.append('status', filters.status);
        if (filters.category) params.append('category', filters.category);
        if (filters.priority) params.append('priority', filters.priority);
        if (filters.limit) params.append('limit', filters.limit);

        const queryString = params.toString();
        return this.request(`/proposals${queryString ? '?' + queryString : ''}`);
    },

    /**
     * Get single proposal by ID
     */
    async getProposal(proposalId) {
        return this.request(`/proposals/${proposalId}`);
    },

    /**
     * Approve a proposal
     */
    async approveProposal(proposalId) {
        return this.request(`/proposals/${proposalId}/approve`, { method: 'POST' });
    },

    /**
     * Reject a proposal
     */
    async rejectProposal(proposalId, reason = '') {
        return this.request(`/proposals/${proposalId}/reject`, {
            method: 'POST',
            body: JSON.stringify({ reason })
        });
    },

    /**
     * Delete a proposal
     */
    async deleteProposal(proposalId) {
        return this.request(`/proposals/${proposalId}`, { method: 'DELETE' });
    },

    /**
     * Execute a proposal (create sandbox and apply changes)
     */
    async executeProposal(proposalId) {
        return this.request(`/proposals/${proposalId}/execute`, {
            method: 'POST',
            body: JSON.stringify({})
        });
    },

    /**
     * Regenerate implementation plan for a proposal
     */
    async regeneratePlan(proposalId) {
        return this.request(`/proposals/${proposalId}/regenerate-plan`, {
            method: 'POST',
            body: JSON.stringify({})
        });
    },

    // ==================== RETRY & ESCALATION ====================

    /**
     * Trigger manual retry for a proposal
     */
    async retryProposal(proposalId) {
        return this.request(`/proposals/${proposalId}/retry`, { method: 'POST' });
    },

    /**
     * Get retry status for a proposal
     */
    async getRetryStatus(proposalId) {
        return this.request(`/proposals/${proposalId}/retry-status`);
    },

    /**
     * Reset retries for a proposal
     */
    async resetRetries(proposalId) {
        return this.request(`/proposals/${proposalId}/reset-retries`, { method: 'POST' });
    },

    /**
     * Get list of escalated proposals
     */
    async getEscalatedProposals() {
        return this.request('/proposals/escalated');
    },

    /**
     * Escalate to human-only investigation
     */
    async escalateToHumanOnly(proposalId) {
        return this.request(`/proposals/${proposalId}/escalate-to-human-only`, { method: 'POST' });
    },

    /**
     * Try another contractor
     */
    async tryAnotherContractor(proposalId) {
        return this.request(`/proposals/${proposalId}/try-another-contractor`, { method: 'POST' });
    },

    /**
     * Apply contractor's fix
     */
    async applyContractorFix(proposalId) {
        return this.request(`/proposals/${proposalId}/apply-contractor-fix`, { method: 'POST' });
    },

    // ==================== CHAT ====================

    /**
     * Send message to contractor
     */
    async sendChatMessage(proposalId, message) {
        return this.request(`/proposals/${proposalId}/contractor-chat`, {
            method: 'POST',
            body: JSON.stringify({ message })
        });
    },

    /**
     * Get chat history for a proposal
     */
    async getChatHistory(proposalId, limit = 50) {
        return this.request(`/proposals/${proposalId}/chat-history?limit=${limit}`);
    },

    // ==================== SANDBOX ====================

    /**
     * Get sandbox for a proposal
     */
    async getSandbox(proposalId) {
        return this.request(`/proposals/${proposalId}/sandbox`);
    },

    /**
     * Create sandbox for a proposal
     */
    async createSandbox(proposalId, sandboxType = 'schema_separation') {
        return this.request(`/proposals/${proposalId}/sandbox/create`, {
            method: 'POST',
            body: JSON.stringify({ sandbox_type: sandboxType })
        });
    },

    /**
     * Run tests in sandbox
     */
    async runSandboxTests(sandboxId, proposalId) {
        return this.request(`/sandboxes/${sandboxId}/test`, {
            method: 'POST',
            body: JSON.stringify({ proposal_id: proposalId })
        });
    },

    /**
     * Get sandbox logs
     */
    async getSandboxLogs(sandboxId) {
        return this.request(`/sandboxes/${sandboxId}/logs`);
    },

    /**
     * Destroy a sandbox
     */
    async destroySandbox(sandboxId) {
        return this.request(`/sandboxes/${sandboxId}`, { method: 'DELETE' });
    },

    /**
     * Get list of all sandboxes
     */
    async getSandboxes() {
        return this.request('/sandboxes');
    },

    // ==================== QUEUE ====================

    /**
     * Get queue status
     */
    async getQueueStatus() {
        return this.request('/queue/status');
    },

    /**
     * Get sandbox queue status (legacy endpoint)
     */
    async getSandboxQueueStatus() {
        return this.request('/sandbox/queue-status');
    },

    // ==================== DEPLOYMENT ====================

    /**
     * Deploy proposal to production
     */
    async deployToProduction(proposalId) {
        return this.request(`/proposals/${proposalId}/deploy-to-production`, { method: 'POST' });
    },

    /**
     * Check if proposal can be deployed
     */
    async canDeploy(proposalId) {
        return this.request(`/proposals/${proposalId}/can-deploy`);
    },

    // ==================== STATS ====================

    /**
     * Get dashboard statistics
     */
    async getStats() {
        return this.request('/stats');
    },

    // ==================== TEAM & FIX REQUESTS ====================

    /**
     * Get available team members/agents for assignment
     */
    async getAvailableAgents() {
        return this.request('/agents/available');
    },

    /**
     * Request a fix from a team member
     */
    async requestFix(sandboxId, proposalId, agentId, notes) {
        return this.request('/request-fix', {
            method: 'POST',
            body: JSON.stringify({
                sandbox_id: sandboxId,
                proposal_id: proposalId,
                agent_id: agentId,
                notes: notes
            })
        });
    },

    /**
     * Clear old test results for a sandbox
     */
    async clearTestResults(sandboxId) {
        return this.request(`/sandboxes/${sandboxId}/clear-results`, {
            method: 'POST',
            body: JSON.stringify({})
        });
    }
};

// Export for module systems, but also make global
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ImprovementsAPI;
}
