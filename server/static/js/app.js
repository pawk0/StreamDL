function initApp() {
  // DOM Elements
  const statActive = document.getElementById('stat-active');
  const statActiveSpeed = document.getElementById('stat-active-speed');
  const statQueued = document.getElementById('stat-queued');
  const statCompleted = document.getElementById('stat-completed');
  const statConcurrency = document.getElementById('stat-concurrency');
  
  const countAll = document.getElementById('count-all');
  const countActive = document.getElementById('count-active');
  const countCompleted = document.getElementById('count-completed');
  
  const formDownload = document.getElementById('form-download');
  const inputUrl = document.getElementById('input-url');
  const selectQuality = document.getElementById('select-quality');
  const selectFormat = document.getElementById('select-format');
  
  const tasksContainer = document.getElementById('tasks-container');
  const emptyState = document.getElementById('empty-state');
  const tabBtns = document.querySelectorAll('.tab-btn');
  const btnClearCompleted = document.getElementById('btn-clear-completed');
  const btnOpenFolder = document.getElementById('btn-open-folder');
  
  // Settings Modal Elements
  const modalSettings = document.getElementById('modal-settings');
  const btnOpenSettings = document.getElementById('btn-open-settings');
  const btnCloseSettings = document.getElementById('btn-close-settings');
  const btnCancelSettings = document.getElementById('btn-cancel-settings');
  const formSettings = document.getElementById('form-settings');
  const settingConcurrency = document.getElementById('setting-concurrency');
  const valConcurrency = document.getElementById('val-concurrency');
  const settingProviderConcurrency = document.getElementById('setting-provider-concurrency');
  const valProviderConcurrency = document.getElementById('val-provider-concurrency');
  const providersList = document.getElementById('providers-list');
  const btnAddProvider = document.getElementById('btn-add-provider');
  const settingFolder = document.getElementById('setting-folder');
  const settingQuality = document.getElementById('setting-quality');
  const settingFormat = document.getElementById('setting-format');

  // Quick Map Provider Modal Elements
  const modalMapProvider = document.getElementById('modal-map-provider');
  const btnCloseMapProvider = document.getElementById('btn-close-map-provider');
  const mapProviderDomainVal = document.getElementById('map-provider-domain-val');
  const selectExistingProvider = document.getElementById('select-existing-provider');
  const btnSubmitAddDomain = document.getElementById('btn-submit-add-domain');
  const inputNewProviderName = document.getElementById('input-new-provider-name');
  const inputNewProviderPattern = document.getElementById('input-new-provider-pattern');
  const inputNewProviderLimit = document.getElementById('input-new-provider-limit');
  const btnSubmitNewProvider = document.getElementById('btn-submit-new-provider');

  let currentFilter = 'all';
  let isFetching = false;
  let currentProviders = [];
  let currentMapDomain = '';

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function sanitizeMediaUrl(url) {
    if (!url || typeof url !== 'string') return '';
    const trimmed = url.trim();
    try {
      const parsed = new URL(trimmed, window.location.origin);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:' || parsed.protocol === 'data:') {
        return escapeHtml(trimmed);
      }
    } catch (e) {
      // Invalid URL scheme
    }
    return '';
  }

  // Toast notification helper
  function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  // Fetch Queue & Update UI
  async function fetchQueue() {
    if (isFetching) return;
    isFetching = true;
    try {
      const res = await fetch('/api/queue');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      updateUI(data);
    } catch (err) {
      console.warn('Error fetching queue:', err);
    } finally {
      isFetching = false;
    }
  }

  function updateUI(data) {
    currentProviders = data.providers || [];
    const tasks = data.tasks || [];
    const maxConcurrent = data.max_concurrent || 3;

    // Calculate metrics
    let totalSpeedRaw = 0;
    let activeTasks = 0;
    let queuedTasks = 0;
    let completedTasks = 0;

    tasks.forEach(t => {
      if (t.status === 'downloading' || t.status === 'processing') {
        activeTasks++;
        totalSpeedRaw += (t.speed_raw || 0);
      } else if (t.status === 'queued') {
        queuedTasks++;
      } else if (t.status === 'completed') {
        completedTasks++;
      }
    });

    // Update Stats
    statActive.textContent = activeTasks;
    statQueued.textContent = queuedTasks;
    statCompleted.textContent = completedTasks;
    statConcurrency.textContent = maxConcurrent;

    statActiveSpeed.textContent = totalSpeedRaw > 0 
      ? `${formatSpeed(totalSpeedRaw)} total speed`
      : '0 B/s total speed';

    // Tab counts
    countAll.textContent = tasks.length;
    countActive.textContent = activeTasks + queuedTasks;
    countCompleted.textContent = completedTasks;

    // Filter tasks
    const filteredTasks = tasks.filter(t => {
      if (currentFilter === 'active') return t.status === 'downloading' || t.status === 'processing' || t.status === 'queued';
      if (currentFilter === 'completed') return t.status === 'completed';
      return true;
    });

    renderTasks(filteredTasks);
  }

  function formatSpeed(bytesPerSec) {
    if (bytesPerSec < 1024) return `${bytesPerSec.toFixed(0)} B/s`;
    if (bytesPerSec < 1024 * 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`;
    return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`;
  }

  function renderTasks(tasks) {
    if (!tasks.length) {
      emptyState.style.display = 'block';
      tasksContainer.innerHTML = '';
      tasksContainer.appendChild(emptyState);
      return;
    }

    emptyState.style.display = 'none';
    tasksContainer.innerHTML = '';

    let queuePositionCounter = 1;

    tasks.forEach(task => {
      const card = document.createElement('div');
      card.className = 'task-item';
      card.dataset.id = task.id;

      // Status badge and styling
      let statusBadgeClass = `badge-${escapeHtml(task.status)}`;
      let statusLabel = task.status;
      if (task.status === 'queued') {
        statusLabel = `Queued #${queuePositionCounter++}`;
      } else if (task.status === 'downloading') {
        statusLabel = 'Downloading';
      } else if (task.status === 'processing') {
        statusLabel = 'Processing';
      }

      // Thumbnail / icon
      const safeThumb = sanitizeMediaUrl(task.thumbnail);
      const thumbHtml = safeThumb
        ? `<img src="${safeThumb}" alt="Thumbnail" onerror="this.style.display='none'">`
        : `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>`;

      // Progress bar fill class
      let fillClass = '';
      if (task.status === 'completed') fillClass = 'completed';
      else if (task.status === 'failed') fillClass = 'failed';

      // Action buttons
      let actionButtons = '';
      if (task.status === 'downloading' || task.status === 'queued') {
        actionButtons = `
          <button class="btn btn-danger btn-sm btn-cancel" data-id="${escapeHtml(task.id)}" title="Cancel download">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            <span>Cancel</span>
          </button>
        `;
      } else if (task.status === 'completed') {
        actionButtons = `
          <button class="btn btn-secondary btn-sm btn-open-file" data-id="${escapeHtml(task.id)}" title="Open Video File">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            <span>Play</span>
          </button>
        `;
      }

      // Metrics display
      let metricsHtml = '';
      if (task.status === 'downloading') {
        metricsHtml = `
          <span>${escapeHtml(task.downloaded_str)} / ${escapeHtml(task.total_str)}</span>
          <span>⚡ ${escapeHtml(task.speed)}</span>
          <span>⏱️ ETA: ${escapeHtml(task.eta)}</span>
          <span>${typeof task.progress === 'number' ? task.progress.toFixed(1) : '0.0'}%</span>
        `;
      } else if (task.status === 'queued') {
        metricsHtml = `<span>Waiting in queue for next available slot...</span>`;
      } else if (task.status === 'completed') {
        metricsHtml = `<span>✅ ${escapeHtml(task.filename || 'Downloaded successfully')}</span>`;
      } else if (task.status === 'processing') {
        metricsHtml = `<span>⚡ Finalizing & muxing audio/video...</span>`;
      }

      const errorHtml = (task.status === 'failed' && task.error_message)
        ? `<div class="task-error-text">⚠️ ${escapeHtml(task.error_message)}</div>`
        : '';

      // Provider config status & map button
      const isConfigured = currentProviders.some(p => (p.id || '').toLowerCase() === (task.provider_id || '').toLowerCase());
      const isDirect = !task.provider_id || task.provider_id.toLowerCase() === 'direct';
      const showMapBtn = !isConfigured && !isDirect;
      const mapBtnHtml = showMapBtn
        ? `<button type="button" class="btn-map-provider" data-domain="${escapeHtml(task.provider_id || task.provider)}" title="Map ${escapeHtml(task.provider_id || task.provider)} to a provider" aria-label="Map ${escapeHtml(task.provider_id || task.provider)} to a provider">+</button>`
        : '';

      card.innerHTML = `
        <div class="task-top">
          <div class="task-info">
            <div class="task-thumb">${thumbHtml}</div>
            <div class="task-details">
              <div class="task-title" title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</div>
              <div class="task-url" title="${escapeHtml(task.url)}">${escapeHtml(task.url)}</div>
            </div>
          </div>
          <div class="task-badges">
            <span class="badge badge-provider" title="Streaming Provider / Host"><span>🌐 ${escapeHtml(task.provider || 'Direct')}</span>${mapBtnHtml}</span>
            <span class="badge badge-quality">${escapeHtml((task.quality || '').toUpperCase())} • ${escapeHtml((task.format || '').toUpperCase())}</span>
            <span class="badge ${escapeHtml(statusBadgeClass)}">${escapeHtml(statusLabel)}</span>
          </div>
        </div>

        <div class="progress-bar-wrap">
          <div class="progress-bar-fill ${fillClass}" style="width: ${task.status === 'completed' ? 100 : (task.progress || 0)}%;"></div>
        </div>

        <div class="task-bottom">
          <div class="task-metrics">${metricsHtml}</div>
          <div class="task-actions">${actionButtons}</div>
        </div>
        ${errorHtml}
      `;

      tasksContainer.appendChild(card);
    });

    // Attach event listeners to card action buttons
    document.querySelectorAll('.btn-cancel').forEach(btn => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        try {
          const res = await fetch(`/api/cancel/${id}`, { method: 'POST' });
          const json = await res.json();
          if (json.success) {
            showToast('Download cancelled', 'info');
            fetchQueue();
          }
        } catch (e) {
          showToast('Failed to cancel task', 'error');
        }
      };
    });

    document.querySelectorAll('.btn-open-file').forEach(btn => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        try {
          const res = await fetch(`/api/open-file/${id}`, { method: 'POST' });
          const json = await res.json();
          if (!json.success) {
            showToast(json.error || 'Could not open file', 'error');
          }
        } catch (e) {
          showToast('Failed to open file', 'error');
        }
      };
    });

    document.querySelectorAll('.btn-map-provider').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        openMapModal(btn.dataset.domain);
      };
    });
  }

  // Add Download Form
  formDownload.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = inputUrl.value.trim();
    if (!url) return;

    const payload = {
      url: url,
      quality: selectQuality.value,
      format: selectFormat.value
    };

    try {
      const res = await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.success) {
        showToast('Download queued successfully!', 'success');
        inputUrl.value = '';
        fetchQueue();
      } else {
        showToast(data.error || 'Failed to queue download', 'error');
      }
    } catch (err) {
      showToast('Error connecting to server', 'error');
    }
  });

  // Open Downloads Folder Button
  btnOpenFolder.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/open-folder', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        showToast('Opened downloads folder', 'info');
      } else {
        showToast(data.error || 'Could not open folder', 'error');
      }
    } catch (e) {
      showToast('Error communicating with server', 'error');
    }
  });

  // Clear Finished Button
  btnClearCompleted.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/clear', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        showToast('Cleared finished tasks', 'info');
        fetchQueue();
      }
    } catch (e) {
      showToast('Error clearing tasks', 'error');
    }
  });

  // Filter Tabs
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentFilter = btn.dataset.filter;
      fetchQueue();
    });
  });

  function renderProviderRows(providers) {
    providersList.innerHTML = '';
    (providers || []).forEach(p => {
      const card = document.createElement('div');
      card.className = 'provider-card';
      const patternsStr = Array.isArray(p.patterns) ? p.patterns.join(', ') : (p.patterns || '');
      card.innerHTML = `
        <div class="provider-card-header">
          <div class="provider-field flex-grow">
            <span class="provider-field-label">Provider Name</span>
            <input type="text" class="provider-name-input" placeholder="e.g. Doodstream" value="${escapeHtml(p.name || '')}">
          </div>
          <div class="provider-field limit-field">
            <span class="provider-field-label">Max Limit</span>
            <input type="number" class="provider-limit-input" min="1" max="10" value="${p.max_concurrent || 1}">
          </div>
          <div class="provider-field action-field">
            <span class="provider-field-label">&nbsp;</span>
            <button type="button" class="btn-remove-provider" title="Delete Provider">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            </button>
          </div>
        </div>
        <div class="provider-field full-width">
          <span class="provider-field-label">Domain Patterns (comma-separated wildcards)</span>
          <input type="text" class="provider-patterns-input" placeholder="e.g. *dood*, *cloudatacdn.com*" value="${escapeHtml(patternsStr)}">
        </div>
      `;

      card.querySelector('.btn-remove-provider').onclick = () => {
        card.remove();
      };

      providersList.appendChild(card);
    });
  }

  if (btnAddProvider) {
    btnAddProvider.addEventListener('click', () => {
      const card = document.createElement('div');
      card.className = 'provider-card';
      card.innerHTML = `
        <div class="provider-card-header">
          <div class="provider-field flex-grow">
            <span class="provider-field-label">Provider Name</span>
            <input type="text" class="provider-name-input" placeholder="e.g. Doodstream" value="">
          </div>
          <div class="provider-field limit-field">
            <span class="provider-field-label">Max Limit</span>
            <input type="number" class="provider-limit-input" min="1" max="10" value="1">
          </div>
          <div class="provider-field action-field">
            <span class="provider-field-label">&nbsp;</span>
            <button type="button" class="btn-remove-provider" title="Delete Provider">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            </button>
          </div>
        </div>
        <div class="provider-field full-width">
          <span class="provider-field-label">Domain Patterns (comma-separated wildcards)</span>
          <input type="text" class="provider-patterns-input" placeholder="e.g. *domain.com*, *keyword*" value="">
        </div>
      `;
      card.querySelector('.btn-remove-provider').onclick = () => card.remove();
      providersList.appendChild(card);
      card.querySelector('.provider-name-input').focus();
    });
  }

  // Settings Modal Events
  btnOpenSettings.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/settings');
      const data = await res.json();
      if (data.settings) {
        settingConcurrency.value = data.settings.max_concurrent || 3;
        valConcurrency.textContent = settingConcurrency.value;
        if (settingProviderConcurrency) {
          settingProviderConcurrency.value = data.settings.max_concurrent_per_provider || 1;
          valProviderConcurrency.textContent = settingProviderConcurrency.value;
        }
        settingFolder.value = data.settings.download_dir || '';
        settingQuality.value = data.settings.default_quality || 'best';
        settingFormat.value = data.settings.default_format || 'mp4';

        renderProviderRows(data.settings.providers || []);
      }
      modalSettings.classList.add('open');
    } catch (e) {
      showToast('Failed to load settings', 'error');
    }
  });

  function closeModal() {
    modalSettings.classList.remove('open');
  }

  btnCloseSettings.addEventListener('click', closeModal);
  btnCancelSettings.addEventListener('click', closeModal);
  modalSettings.addEventListener('click', (e) => {
    if (e.target === modalSettings) closeModal();
  });

  settingConcurrency.addEventListener('input', () => {
    valConcurrency.textContent = settingConcurrency.value;
  });

  if (settingProviderConcurrency) {
    settingProviderConcurrency.addEventListener('input', () => {
      valProviderConcurrency.textContent = settingProviderConcurrency.value;
    });
  }

  formSettings.addEventListener('submit', async (e) => {
    e.preventDefault();

    // Collect providers
    const providerCards = providersList.querySelectorAll('.provider-card, .provider-row');
    const providers = [];
    providerCards.forEach(card => {
      const name = card.querySelector('.provider-name-input').value.trim();
      const patternsRaw = card.querySelector('.provider-patterns-input').value.trim();
      const limit = parseInt(card.querySelector('.provider-limit-input').value, 10) || 1;
      if (name) {
        const patterns = patternsRaw.split(',').map(x => x.trim()).filter(Boolean);
        providers.push({
          id: name.toLowerCase().replace(/[^a-z0-9_-]/g, ''),
          name: name,
          patterns: patterns,
          max_concurrent: limit
        });
      }
    });

    const updated = {
      max_concurrent: parseInt(settingConcurrency.value, 10),
      max_concurrent_per_provider: settingProviderConcurrency ? parseInt(settingProviderConcurrency.value, 10) : 1,
      providers: providers,
      download_dir: settingFolder.value.trim(),
      default_quality: settingQuality.value,
      default_format: settingFormat.value
    };

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updated)
      });
      const data = await res.json();
      if (data.success) {
        showToast('Settings saved successfully!', 'success');
        closeModal();
        fetchQueue();
      } else {
        showToast('Failed to save settings', 'error');
      }
    } catch (e) {
      showToast('Error saving settings', 'error');
    }
  });

  // Quick Map Provider Modal Logic
  function openMapModal(domain) {
    if (!domain) return;
    currentMapDomain = domain;
    if (mapProviderDomainVal) {
      mapProviderDomainVal.textContent = domain;
    }

    // Option 1: Populate existing providers dropdown
    if (selectExistingProvider) {
      selectExistingProvider.innerHTML = '';
      if (!currentProviders || currentProviders.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'No existing providers configured';
        selectExistingProvider.appendChild(opt);
        if (btnSubmitAddDomain) btnSubmitAddDomain.disabled = true;
      } else {
        if (btnSubmitAddDomain) btnSubmitAddDomain.disabled = false;
        currentProviders.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = `${p.name} (limit: ${p.max_concurrent || 1})`;
          selectExistingProvider.appendChild(opt);
        });
      }
    }

    // Option 2: Pre-fill new provider inputs
    if (inputNewProviderName) {
      const baseName = domain.split('.')[0];
      inputNewProviderName.value = baseName.charAt(0).toUpperCase() + baseName.slice(1);
    }
    if (inputNewProviderPattern) {
      inputNewProviderPattern.value = `*${domain}*`;
    }
    if (inputNewProviderLimit) {
      inputNewProviderLimit.value = '1';
    }

    if (modalMapProvider) {
      modalMapProvider.classList.add('open');
    }
  }

  function closeMapModal() {
    if (modalMapProvider) {
      modalMapProvider.classList.remove('open');
    }
  }

  if (btnCloseMapProvider) {
    btnCloseMapProvider.addEventListener('click', closeMapModal);
  }
  if (modalMapProvider) {
    modalMapProvider.addEventListener('click', (e) => {
      if (e.target === modalMapProvider) closeMapModal();
    });
  }

  // Option 1: Add domain pattern to existing provider
  if (btnSubmitAddDomain) {
    btnSubmitAddDomain.addEventListener('click', async () => {
      const selectedId = selectExistingProvider ? selectExistingProvider.value : '';
      if (!selectedId) {
        showToast('Please select an existing provider', 'error');
        return;
      }
      const patternToAdd = `*${currentMapDomain}*`;

      try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        const settings = data.settings || {};
        const providers = settings.providers || [];

        const prov = providers.find(p => p.id === selectedId);
        if (!prov) {
          showToast('Selected provider not found in settings', 'error');
          return;
        }

        if (!Array.isArray(prov.patterns)) {
          prov.patterns = prov.patterns ? [prov.patterns] : [];
        }

        const alreadyExists = prov.patterns.some(pat => {
          const clean = pat.replace(/\*/g, '').toLowerCase();
          return clean === currentMapDomain.toLowerCase();
        });

        if (!alreadyExists) {
          prov.patterns.push(patternToAdd);
        }

        const saveRes = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(settings)
        });
        const saveData = await saveRes.json();
        if (saveData.success) {
          showToast(`Added ${patternToAdd} to ${prov.name}!`, 'success');
          closeMapModal();
          fetchQueue();
        } else {
          showToast('Failed to update provider', 'error');
        }
      } catch (err) {
        console.error(err);
        showToast('Error updating provider', 'error');
      }
    });
  }

  // Option 2: Create brand new provider
  if (btnSubmitNewProvider) {
    btnSubmitNewProvider.addEventListener('click', async () => {
      const name = inputNewProviderName ? inputNewProviderName.value.trim() : '';
      if (!name) {
        showToast('Please enter a provider name', 'error');
        if (inputNewProviderName) inputNewProviderName.focus();
        return;
      }

      const patternVal = (inputNewProviderPattern && inputNewProviderPattern.value.trim())
        ? inputNewProviderPattern.value.trim()
        : `*${currentMapDomain}*`;
      const patterns = patternVal.split(',').map(s => s.trim()).filter(Boolean);
      const limit = inputNewProviderLimit ? (parseInt(inputNewProviderLimit.value, 10) || 1) : 1;
      const genId = name.toLowerCase().replace(/[^a-z0-9_-]/g, '') || ('prov_' + Date.now());

      try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        const settings = data.settings || {};
        if (!settings.providers) settings.providers = [];

        const existing = settings.providers.find(p => p.id === genId);
        if (existing) {
          patterns.forEach(pat => {
            if (!existing.patterns.includes(pat)) existing.patterns.push(pat);
          });
          existing.max_concurrent = limit;
        } else {
          settings.providers.push({
            id: genId,
            name: name,
            patterns: patterns,
            max_concurrent: limit
          });
        }

        const saveRes = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(settings)
        });
        const saveData = await saveRes.json();
        if (saveData.success) {
          showToast(`Created provider "${name}"!`, 'success');
          closeMapModal();
          fetchQueue();
        } else {
          showToast('Failed to create provider', 'error');
        }
      } catch (err) {
        console.error(err);
        showToast('Error creating provider', 'error');
      }
    });
  }

  // Allow Enter key to submit inside Option 2 inputs
  [inputNewProviderName, inputNewProviderPattern, inputNewProviderLimit].forEach(inp => {
    if (inp) {
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          if (btnSubmitNewProvider) btnSubmitNewProvider.click();
        }
      });
    }
  });

  // Global escape key to close modals
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeModal();
      closeMapModal();
    }
  });

  // Poll loop
  fetchQueue();
  setInterval(fetchQueue, 1000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
