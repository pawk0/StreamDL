import { apiError } from './ui.js';
import { escapeHtml, showToast } from './ui.js';

export function initSettings({ refresh: fetchQueue }) {
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
  const settingTlsMode = document.getElementById('setting-tls-mode');

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
            <button type="button" class="btn-remove-provider" title="Delete Provider" aria-label="Delete Provider">
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
            <button type="button" class="btn-remove-provider" title="Delete Provider" aria-label="Delete Provider">
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
        if (settingTlsMode) {
          settingTlsMode.value = data.settings.tls_mode || 'auto';
        }

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
      default_format: settingFormat.value,
      tls_mode: settingTlsMode ? settingTlsMode.value : 'auto'
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
        showToast(apiError(data, 'Failed to save settings'), 'error');
      }
    } catch (e) {
      showToast('Error saving settings', 'error');
    }
  });

  return { close: closeModal };
}
