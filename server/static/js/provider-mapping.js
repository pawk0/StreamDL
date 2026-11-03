import { showToast } from './ui.js';

export function initProviderMapping({ refresh: fetchQueue }) {
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

  let currentProviders = [];
  let currentMapDomain = '';

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

  return {
    open: openMapModal,
    close: closeMapModal,
    updateProviders(providers) { currentProviders = providers; },
  };
}
