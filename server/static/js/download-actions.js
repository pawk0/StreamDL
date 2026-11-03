import { apiError } from './ui.js';
import { showToast } from './ui.js';

export function initDownloadActions({ refresh: fetchQueue, openMapModal, setFilter }) {
  const formDownload = document.getElementById('form-download');
  const inputUrl = document.getElementById('input-url');
  const selectQuality = document.getElementById('select-quality');
  const selectFormat = document.getElementById('select-format');

  const tasksContainer = document.getElementById('tasks-container');
  const tabBtns = document.querySelectorAll('.tab-btn');
  const btnClearCompleted = document.getElementById('btn-clear-completed');
  const btnOpenFolder = document.getElementById('btn-open-folder');

  // Delegated event listener for task cards (cancel, open file, map provider)
  tasksContainer.addEventListener('click', async (e) => {
    const clearBtn = e.target.closest('.btn-clear-task');
    if (clearBtn) {
      clearBtn.disabled = true;
      try {
        const res = await fetch(`/api/clear/${encodeURIComponent(clearBtn.dataset.id)}`, { method: 'POST' });
        const json = await res.json();
        if (!res.ok || !json.success) throw new Error(apiError(json, 'Failed to clear task'));
        showToast('Task cleared', 'info');
        fetchQueue();
      } catch (err) {
        showToast(err.message || 'Failed to clear task', 'error');
      } finally {
        clearBtn.disabled = false;
      }
      return;
    }
    const controlBtn = e.target.closest('.btn-pause, .btn-resume');
    if (controlBtn) {
      const action = controlBtn.classList.contains('btn-pause') ? 'pause' : 'resume';
      controlBtn.disabled = true;
      try {
        const res = await fetch(`/api/${action}/${encodeURIComponent(controlBtn.dataset.id)}`, { method: 'POST' });
        const json = await res.json();
        if (!res.ok || !json.success) throw new Error(apiError(json, `Failed to ${action} download`));
        showToast(action === 'pause' ? 'Pause requested' : 'Resume requested', 'info');
        fetchQueue();
      } catch (err) {
        showToast(err.message || `Failed to ${action} download`, 'error');
      } finally {
        controlBtn.disabled = false;
      }
      return;
    }
    const cancelBtn = e.target.closest('.btn-cancel');
    if (cancelBtn) {
      const id = cancelBtn.dataset.id;
      try {
        const res = await fetch(`/api/cancel/${id}`, { method: 'POST' });
        const json = await res.json();
        if (json.success) {
          showToast('Download cancelled', 'info');
          fetchQueue();
        }
      } catch (err) {
        showToast('Failed to cancel task', 'error');
      }
      return;
    }

    const openFileBtn = e.target.closest('.btn-open-file');
    if (openFileBtn) {
      const id = openFileBtn.dataset.id;
      try {
        const res = await fetch(`/api/open-file/${id}`, { method: 'POST' });
        const json = await res.json();
        if (!json.success) {
          showToast(apiError(json, 'Could not open file'), 'error');
        }
      } catch (err) {
        showToast('Failed to open file', 'error');
      }
      return;
    }

    const mapBtn = e.target.closest('.btn-map-provider');
    if (mapBtn) {
      e.stopPropagation();
      openMapModal(mapBtn.dataset.domain);
      return;
    }
  });

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
        showToast(apiError(data, 'Failed to queue download'), 'error');
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
        showToast(apiError(data, 'Could not open folder'), 'error');
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
      setFilter(btn.dataset.filter);
      fetchQueue();
    });
  });

}
