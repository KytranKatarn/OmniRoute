/**
 * MonacoSetup — IIFE module for Monaco editor integration with LCARS theme
 * Handles editor creation, file tab management, and custom theming
 */

const MonacoSetup = (() => {
  let editor = null;
  let openTabs = new Map(); // fileId -> {path, model, viewState, unsaved}

  // Language mapping from file extension
  const languageMap = {
    html: 'html',
    htm: 'html',
    css: 'css',
    scss: 'css',
    js: 'javascript',
    mjs: 'javascript',
    json: 'json',
    md: 'markdown',
    yaml: 'yaml',
    yml: 'yaml',
    xml: 'xml',
    svg: 'xml',
    txt: 'plaintext',
  };

  /**
   * Loads Monaco editor from CDN
   * @returns {Promise<void>}
   */
  async function load() {
    return new Promise((resolve, reject) => {
      // Load the require module
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs/loader.min.js';
      script.onload = () => {
        require.config({
          paths: {
            vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs',
          },
        });

        require(['vs/editor/editor.main'], () => {
          _defineTheme();
          resolve();
        });
      };
      script.onerror = () => reject(new Error('Failed to load Monaco editor'));
      document.head.appendChild(script);
    });
  }

  /**
   * Defines the LCARS dark theme for Monaco
   */
  function _defineTheme() {
    monaco.editor.defineTheme('lcars-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'comment', foreground: '6b7280', fontStyle: 'italic' },
        { token: 'keyword', foreground: '00e5ff' },
        { token: 'string', foreground: 'a3e635' },
        { token: 'number', foreground: 'fbbf24' },
        { token: 'tag', foreground: 'f97316' },
        { token: 'attribute.name', foreground: '8b5cf6' },
        { token: 'attribute.value', foreground: 'a3e635' },
      ],
      colors: {
        'editor.background': '#0a0a1a',
        'editor.foreground': '#e0e0e0',
        'editor.lineHighlightBackground': '#1a1a3a',
        'editor.selectionBackground': '#2a2a5a',
        'editorCursor.foreground': '#00e5ff',
        'editorLineNumber.foreground': '#4a4a6a',
        'editorLineNumber.activeForeground': '#00e5ff',
      },
    });
  }

  /**
   * Creates and initializes the Monaco editor
   * @param {HTMLElement} containerEl - Container for the editor
   * @returns {monaco.editor.IStandaloneCodeEditor}
   */
  function createEditor(containerEl) {
    editor = monaco.editor.create(containerEl, {
      theme: 'lcars-dark',
      fontFamily: 'IBM Plex Mono',
      fontSize: 14,
      minimap: { enabled: true },
      automaticLayout: true,
      tabSize: 2,
      wordWrap: 'on',
      'bracketPairColorization.enabled': true,
    });

    // Ctrl+S keybinding for save
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      const activeFileId = getActiveFileId();
      if (activeFileId) {
        const event = new CustomEvent('cm:save-file', { detail: { fileId: activeFileId } });
        document.dispatchEvent(event);
      }
    });

    return editor;
  }

  /**
   * Opens a file in a new tab or switches to existing tab
   * @param {string} fileId - Unique file identifier
   * @param {string} path - File path (for display and language detection)
   * @param {string} content - File content
   */
  function openFile(fileId, path, content) {
    // If tab already open, switch to it
    if (openTabs.has(fileId)) {
      const tab = openTabs.get(fileId);
      editor.setModel(tab.model);
      editor.restoreViewState(tab.viewState);
      return;
    }

    // Detect language from file extension
    const ext = path.split('.').pop().toLowerCase();
    const language = languageMap[ext] || 'plaintext';

    // Create model
    const model = monaco.editor.createModel(content, language, monaco.Uri.file(path));

    // Track content changes
    model.onDidChangeContent(() => {
      const tab = openTabs.get(fileId);
      if (tab) {
        tab.unsaved = true;
        const changeEvent = new CustomEvent('cm:content-changed', {
          detail: { fileId, content: model.getValue() },
        });
        document.dispatchEvent(changeEvent);

        const tabEvent = new CustomEvent('cm:tab-changed', {
          detail: { fileId, unsaved: true },
        });
        document.dispatchEvent(tabEvent);
      }
    });

    // Store tab info
    openTabs.set(fileId, {
      path,
      model,
      viewState: null,
      unsaved: false,
    });

    // Set as active model
    editor.setModel(model);
  }

  /**
   * Closes a tab and disposes its model
   * @param {string} fileId - File identifier to close
   */
  function closeTab(fileId) {
    if (!openTabs.has(fileId)) return;

    const tab = openTabs.get(fileId);
    tab.model.dispose();
    openTabs.delete(fileId);

    // Switch to next tab or clear editor
    if (openTabs.size > 0) {
      const nextFileId = openTabs.keys().next().value;
      const nextTab = openTabs.get(nextFileId);
      editor.setModel(nextTab.model);
    } else {
      editor.setModel(null);
    }
  }

  /**
   * Gets the content of a file
   * @param {string} fileId - File identifier
   * @returns {string|null} File content or null if not open
   */
  function getContent(fileId) {
    const tab = openTabs.get(fileId);
    return tab ? tab.model.getValue() : null;
  }

  /**
   * Marks a file as saved
   * @param {string} fileId - File identifier
   */
  function markSaved(fileId) {
    const tab = openTabs.get(fileId);
    if (tab) {
      tab.unsaved = false;
      const event = new CustomEvent('cm:tab-changed', {
        detail: { fileId, unsaved: false },
      });
      document.dispatchEvent(event);
    }
  }

  /**
   * Gets the ID of the currently active file
   * @returns {string|null} Active file ID or null
   */
  function getActiveFileId() {
    if (!editor) return null;
    const currentModel = editor.getModel();
    if (!currentModel) return null;

    for (const [fileId, tab] of openTabs.entries()) {
      if (tab.model === currentModel) {
        return fileId;
      }
    }
    return null;
  }

  /**
   * Gets the map of open tabs
   * @returns {Map} Open tabs map (fileId -> {path, model, viewState, unsaved})
   */
  function getOpenTabs() {
    return openTabs;
  }

  /**
   * Gets the Monaco editor instance
   * @returns {monaco.editor.IStandaloneCodeEditor|null}
   */
  function getEditor() {
    return editor;
  }

  /**
   * Disposes all models and the editor
   */
  function dispose() {
    for (const tab of openTabs.values()) {
      tab.model.dispose();
    }
    openTabs.clear();

    if (editor) {
      editor.dispose();
      editor = null;
    }
  }

  // Public API
  return {
    load,
    createEditor,
    openFile,
    closeTab,
    getContent,
    markSaved,
    getActiveFileId,
    getOpenTabs,
    getEditor,
    dispose,
  };
})();
