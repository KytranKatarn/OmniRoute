/**
 * LivePreview Module for Kytran Business Suite Website Builder
 * Manages iframe-based live preview with responsive device modes
 */

const LivePreview = (() => {
  let iframeEl = null;
  let projectId = null;
  let debounceTimer = null;
  const DEBOUNCE_DELAY = 500;
  const DEVICE_WIDTHS = {
    mobile: 375,
    tablet: 768,
    desktop: '100%'
  };

  const init = (iframe, id) => {
    iframeEl = iframe;
    projectId = id;

    // Listen for content changes
    document.addEventListener('cm:content-changed', () => {
      debounceRefresh();
    });

    // Initial load
    refreshPreview();
  };

  const debounceRefresh = () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      refreshPreview();
    }, DEBOUNCE_DELAY);
  };

  const refreshPreview = async () => {
    try {
      const response = await fetch(
        `/plugins/website-builder/api/projects/${projectId}/preview`
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();

      // Set preview content
      if (iframeEl.srcdoc !== data.html) {
        iframeEl.srcdoc = data.html;
      }
    } catch (err) {
      console.error('Failed to refresh preview:', err);
      iframeEl.srcdoc = '<div style="padding: 20px; color: #f00;">Failed to load preview</div>';
    }
  };

  const setDevice = (device) => {
    const width = DEVICE_WIDTHS[device];

    if (width === '100%') {
      iframeEl.style.width = '100%';
      iframeEl.style.margin = '0';
    } else {
      iframeEl.style.width = width + 'px';
      iframeEl.style.margin = '0 auto';
    }
  };

  const openInNewTab = () => {
    if (!iframeEl.srcdoc) {
      alert('No preview content available');
      return;
    }

    const blob = new Blob([iframeEl.srcdoc], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');

    // Cleanup URL after a delay
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 100);
  };

  return {
    init,
    refreshPreview,
    setDevice,
    openInNewTab,
  };
})();
