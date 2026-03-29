/**
 * AI Chat Overlay Module
 * Handles AI-powered code editing chat interface for the website builder
 */

const AIChatOverlay = (() => {
  let overlayEl = null;
  let messagesEl = null;
  let inputAreaEl = null;
  let inputEl = null;
  let projectId = null;
  let isOpen = false;

  /**
   * Initialize the chat overlay
   * @param {HTMLElement} el - The overlay container element
   * @param {string} pid - The project ID for API calls
   */
  function init(el, pid) {
    overlayEl = el;
    projectId = pid;

    // Find message container and input area
    messagesEl = overlayEl?.querySelector('.cm-ai-messages');
    inputAreaEl = overlayEl?.querySelector('.cm-ai-input-area');
    inputEl = inputAreaEl?.querySelector('textarea');

    if (!messagesEl || !inputEl) {
      console.warn('[AIChatOverlay] Missing message or input elements');
      return;
    }

    // Wire up Enter key (without Shift)
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  /**
   * Toggle overlay visibility
   */
  function toggle() {
    if (isOpen) {
      close();
    } else {
      open();
    }
  }

  /**
   * Open the overlay
   */
  function open() {
    if (!overlayEl) {
      console.warn('[AIChatOverlay] Overlay not initialized');
      return;
    }
    isOpen = true;
    overlayEl.classList.add('open');
    inputEl?.focus();
  }

  /**
   * Close the overlay
   */
  function close() {
    if (!overlayEl) return;
    isOpen = false;
    overlayEl.classList.remove('open');
  }

  /**
   * Send a message to the AI
   */
  async function sendMessage() {
    if (!inputEl || !projectId) {
      console.warn('[AIChatOverlay] Input or project ID missing');
      return;
    }

    const messageText = inputEl.value.trim();
    if (!messageText) return;

    // Clear input immediately
    inputEl.value = '';

    // Append user message
    _appendMessage('user', messageText);

    try {
      // Get file context from Monaco
      const fileId = window.MonacoSetup?.getActiveFileId?.();
      const openTabs = window.MonacoSetup?.getOpenTabs?.();

      let fileContent = '';
      if (fileId && openTabs) {
        const activeTab = openTabs.find((t) => t.id === fileId);
        if (activeTab) {
          fileContent = activeTab.content || '';
        }
      }

      // Build request
      const requestBody = {
        message: messageText,
        context: {
          file_path: fileId || null,
          file_content: fileContent,
        },
      };

      // POST to API
      const response = await fetch(
        `/plugins/website-builder/api/projects/${projectId}/ai/chat`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        }
      );

      if (!response.ok) {
        const errorText = await response.text();
        _appendMessage('error', `API Error: ${response.status} - ${errorText}`);
        return;
      }

      const data = await response.json();

      // Append AI response
      if (data.response) {
        _appendMessage('ai', data.response);
      }

      // Apply code update if provided
      if (data.code_update) {
        _applyCodeUpdate(data.code_update);
      }
    } catch (err) {
      _appendMessage('error', `Error: ${err.message}`);
    }
  }

  /**
   * Append a message to the chat
   * @param {string} role - 'user', 'ai', or 'error'
   * @param {string} text - Message text
   */
  function _appendMessage(role, text) {
    if (!messagesEl) return;

    const msgDiv = document.createElement('div');
    msgDiv.className = `cm-ai-message cm-ai-${role}`;

    // Use textContent for security (no HTML injection)
    msgDiv.textContent = text;

    // Apply styling based on role
    if (role === 'user') {
      msgDiv.style.cssText = `
        text-align: right;
        color: #00ffff;
        margin-bottom: 12px;
        padding: 8px 12px;
      `;
    } else if (role === 'error') {
      msgDiv.style.cssText = `
        color: #ff4444;
        margin-bottom: 12px;
        padding: 8px 12px;
      `;
    } else if (role === 'ai') {
      msgDiv.style.cssText = `
        background-color: rgba(139, 92, 246, 0.1);
        color: #d8b4fe;
        margin-bottom: 12px;
        padding: 8px 12px;
        border-radius: 4px;
      `;
    }

    messagesEl.appendChild(msgDiv);

    // Auto-scroll to bottom
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  /**
   * Apply a code update from the AI response
   * @param {object} update - Code update object {file_path, content, line_start, line_end}
   */
  function _applyCodeUpdate(update) {
    if (!update || !update.content) return;

    const editor = window.MonacoSetup?.getEditor?.();
    if (!editor) {
      console.warn('[AIChatOverlay] Editor not available');
      return;
    }

    try {
      // Build edit operation
      const edits = [];

      if (
        typeof update.line_start === 'number' &&
        typeof update.line_end === 'number'
      ) {
        // Replace lines
        edits.push({
          range: new monaco.Range(
            update.line_start + 1,
            1,
            update.line_end + 1,
            1
          ),
          text: update.content,
          forceMoveMarkers: true,
        });
      } else {
        // Append to end
        const model = editor.getModel();
        const endLine = model.getLineCount();
        edits.push({
          range: new monaco.Range(endLine + 1, 1, endLine + 1, 1),
          text: '\n' + update.content,
          forceMoveMarkers: true,
        });
      }

      // Apply edits
      editor.executeEdits('ai-chat', edits);

      _appendMessage('ai', '✓ Code updated in editor');
    } catch (err) {
      _appendMessage('error', `Failed to apply code update: ${err.message}`);
    }
  }

  // Public API
  return {
    init,
    toggle,
    open,
    close,
    sendMessage,
  };
})();
