/**
 * FileTree Module for Kytran Business Suite Website Builder
 * Manages hierarchical file tree UI with context menu operations
 */

const FileTree = (() => {
  let containerEl = null;
  let projectId = null;
  let files = [];
  let filterText = '';
  const collapsedFolders = new Set();

  const fileIcons = {
    html: '&#9671;',    // diamond - orange
    css: '&#9670;',     // filled diamond - pink
    js: '&#9654;',      // play - yellow
    json: '&#123;',     // brace - cyan
    md: '&#182;',       // pilcrow - green
    yaml: '&#8801;',    // triple bar - cyan
    yml: '&#8801;',     // triple bar - cyan
    default: '&#9724;'  // square - purple (images, etc)
  };

  const getFileIcon = (filename) => {
    const ext = filename.split('.').pop().toLowerCase();
    return fileIcons[ext] || fileIcons.default;
  };

  const getFileExtension = (filename) => {
    return filename.split('.').pop().toLowerCase();
  };

  const init = (el, id) => {
    containerEl = el;
    projectId = id;
    collapsedFolders.clear();
    refresh();
  };

  const refresh = async () => {
    try {
      const response = await fetch(
        `/plugins/website-builder/api/projects/${projectId}/files`
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      files = await response.json();
      render();
    } catch (err) {
      console.error('Failed to refresh file tree:', err);
      containerEl.textContent = 'Failed to load files';
    }
  };

  const buildTree = (flatFiles) => {
    const tree = {};

    flatFiles.forEach((file) => {
      const parts = file.path.split('/');
      let current = tree;

      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const isLast = i === parts.length - 1;

        if (!current[part]) {
          current[part] = isLast ? { __file: file } : {};
        } else if (isLast && !current[part].__file) {
          current[part].__file = file;
        }

        if (!isLast) {
          current = current[part];
        }
      }
    });

    return tree;
  };

  const renderNode = (parentEl, node, depth = 0, nodePath = '') => {
    const keys = Object.keys(node).sort();

    // Folders first, then files
    const folders = keys.filter((k) => !node[k].__file && k !== '__file');
    const fileKeys = keys.filter((k) => node[k].__file || k === '__file');

    [...folders, ...fileKeys].forEach((name) => {
      if (name === '__file') return;

      const item = node[name];
      const currentPath = nodePath ? `${nodePath}/${name}` : name;
      const isFolder = !item.__file;

      // Apply filter
      if (filterText && !currentPath.includes(filterText)) return;

      const div = document.createElement('div');
      div.className = `cm-tree-item ${isFolder ? 'cm-folder' : 'cm-file'}`;
      div.style.setProperty('--depth', depth);

      if (isFolder) {
        // Folder header
        const folderDiv = document.createElement('div');
        folderDiv.className = 'cm-folder-header';

        // Create toggle span with hardcoded icon
        const toggleSpan = document.createElement('span');
        toggleSpan.className = 'cm-tree-toggle';
        toggleSpan.innerHTML = collapsedFolders.has(currentPath) ? '&#9654;' : '&#9660;';

        // Create icon span
        const iconSpan = document.createElement('span');
        iconSpan.className = 'cm-tree-icon';
        iconSpan.textContent = '📁';

        // Create label span
        const labelSpan = document.createElement('span');
        labelSpan.className = 'cm-tree-label';
        labelSpan.textContent = name;

        folderDiv.appendChild(toggleSpan);
        folderDiv.appendChild(iconSpan);
        folderDiv.appendChild(labelSpan);

        // Toggle folder
        folderDiv.addEventListener('click', (e) => {
          e.stopPropagation();
          if (collapsedFolders.has(currentPath)) {
            collapsedFolders.delete(currentPath);
          } else {
            collapsedFolders.add(currentPath);
          }
          render();
        });

        // Context menu for folder
        folderDiv.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          showContextMenu(e, 'folder', { path: currentPath, name });
        });

        div.appendChild(folderDiv);

        // Children container
        if (!collapsedFolders.has(currentPath)) {
          const childrenDiv = document.createElement('div');
          childrenDiv.className = 'cm-tree-children';
          renderNode(childrenDiv, item, depth + 1, currentPath);
          div.appendChild(childrenDiv);
        }
      } else {
        // File item
        const fileDiv = document.createElement('div');
        fileDiv.className = 'cm-file-header';
        const ext = getFileExtension(item.__file.name);

        // Create icon span with file type icon
        const iconSpan = document.createElement('span');
        iconSpan.className = 'cm-tree-icon';
        iconSpan.style.color = `var(--color-${ext}, #999)`;
        iconSpan.innerHTML = getFileIcon(item.__file.name);

        // Create label span
        const labelSpan = document.createElement('span');
        labelSpan.className = 'cm-tree-label';
        labelSpan.textContent = name;

        fileDiv.appendChild(iconSpan);
        fileDiv.appendChild(labelSpan);

        // Open file on click
        fileDiv.addEventListener('click', (e) => {
          e.stopPropagation();
          const event = new CustomEvent('cm:open-file', {
            detail: item.__file,
          });
          containerEl.dispatchEvent(event);
        });

        // Context menu for file
        fileDiv.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          showContextMenu(e, 'file', {
            path: currentPath,
            name,
            file: item.__file,
          });
        });

        div.appendChild(fileDiv);
      }

      parentEl.appendChild(div);
    });
  };

  const showContextMenu = (e, type, data) => {
    // Remove existing menu
    const existing = containerEl.querySelector('.cm-context-menu');
    if (existing) existing.remove();

    const menu = document.createElement('div');
    menu.className = 'cm-context-menu';
    menu.style.left = e.clientX + 'px';
    menu.style.top = e.clientY + 'px';

    const items = [];

    if (type === 'folder') {
      items.push(['New File', () => createFileInFolder(data.path)]);
      items.push(['New Folder', () => createFolderInFolder(data.path)]);
      items.push(null); // divider
      items.push(['Delete Folder', () => deleteFolder(data.path)]);
    } else {
      items.push(['Rename', () => renameFile(data)]);
      items.push(['Duplicate', () => duplicateFile(data)]);
      items.push(null);
      items.push(['Delete', () => deleteFile(data)]);
    }

    items.forEach((item) => {
      if (!item) {
        const divider = document.createElement('div');
        divider.className = 'cm-context-divider';
        menu.appendChild(divider);
      } else {
        const btn = document.createElement('button');
        btn.textContent = item[0];
        btn.addEventListener('click', () => {
          item[1]();
          menu.remove();
        });
        menu.appendChild(btn);
      }
    });

    document.body.appendChild(menu);

    // Close menu on outside click
    setTimeout(() => {
      document.addEventListener(
        'click',
        () => {
          menu.remove();
        },
        { once: true }
      );
    }, 0);
  };

  const createFileInFolder = async (folderPath) => {
    const filename = prompt('New file name:');
    if (!filename) return;

    try {
      const response = await fetch(
        `/plugins/website-builder/api/projects/${projectId}/files`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            path: `${folderPath}/${filename}`,
            content: '',
          }),
        }
      );
      if (response.ok) {
        refresh();
      }
    } catch (err) {
      console.error('Failed to create file:', err);
    }
  };

  const createFolderInFolder = async (folderPath) => {
    const name = prompt('New folder name:');
    if (!name) return;

    try {
      const response = await fetch(
        `/plugins/website-builder/api/projects/${projectId}/files`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            path: `${folderPath}/${name}/.gitkeep`,
            content: '',
          }),
        }
      );
      if (response.ok) {
        refresh();
      }
    } catch (err) {
      console.error('Failed to create folder:', err);
    }
  };

  const renameFile = async (data) => {
    const newName = prompt(`Rename "${data.name}" to:`, data.name);
    if (!newName || newName === data.name) return;

    try {
      const response = await fetch(
        `/plugins/website-builder/api/projects/${projectId}/files`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            oldPath: data.path,
            newPath: data.path.replace(data.name, newName),
          }),
        }
      );
      if (response.ok) {
        refresh();
      }
    } catch (err) {
      console.error('Failed to rename file:', err);
    }
  };

  const duplicateFile = async (data) => {
    const ext = data.name.lastIndexOf('.')
      ? data.name.substring(data.name.lastIndexOf('.'))
      : '';
    const base = data.name.substring(0, data.name.lastIndexOf('.') || data.name.length);
    const newName = `${base}-copy${ext}`;

    try {
      const response = await fetch(
        `/plugins/website-builder/api/projects/${projectId}/files`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            path: data.path.replace(data.name, newName),
            content: data.file.content || '',
          }),
        }
      );
      if (response.ok) {
        refresh();
      }
    } catch (err) {
      console.error('Failed to duplicate file:', err);
    }
  };

  const deleteFile = async (data) => {
    if (!confirm(`Delete "${data.name}"? This cannot be undone.`)) return;

    try {
      const response = await fetch(
        `/plugins/website-builder/api/projects/${projectId}/files`,
        {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: data.path }),
        }
      );
      if (response.ok) {
        const event = new CustomEvent('cm:file-deleted', { detail: data });
        containerEl.dispatchEvent(event);
        refresh();
      }
    } catch (err) {
      console.error('Failed to delete file:', err);
    }
  };

  const deleteFolder = async (folderPath) => {
    if (!confirm(`Delete folder "${folderPath}"? This cannot be undone.`)) return;

    try {
      const response = await fetch(
        `/plugins/website-builder/api/projects/${projectId}/files`,
        {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: folderPath }),
        }
      );
      if (response.ok) {
        refresh();
      }
    } catch (err) {
      console.error('Failed to delete folder:', err);
    }
  };

  const render = () => {
    const treeBody = containerEl.querySelector('.cm-file-tree-body');
    if (!treeBody) return;

    treeBody.innerHTML = '';
    const tree = buildTree(files);
    renderNode(treeBody, tree);
  };

  const setFilter = (text) => {
    filterText = text;
    render();
  };

  return {
    init,
    refresh,
    render,
    setFilter,
  };
})();
