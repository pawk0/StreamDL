import { createTasksView } from './tasks-view.js';
import { createQueuePoller } from './queue.js';
import { initDownloadActions } from './download-actions.js';
import { initSettings } from './settings.js';
import { initProviderMapping } from './provider-mapping.js';

function initApp() {
  const view = createTasksView();
  const queue = createQueuePoller(data => {
    view.update(data);
    mapping.updateProviders(data.providers || []);
  });
  const settings = initSettings(queue);
  const mapping = initProviderMapping(queue);
  initDownloadActions({
    refresh: queue.refresh,
    openMapModal: mapping.open,
    setFilter: view.setFilter,
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      settings.close();
      mapping.close();
    }
  });

  // Retain the existing browser-test refresh hook.
  window.__testFetchQueue = queue.refresh;
  queue.start();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
