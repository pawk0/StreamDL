import { escapeHtml, sanitizeMediaUrl } from './ui.js';

// Owns task rendering, filtering, and DOM reconciliation.
export function createTasksView() {
  // DOM Elements
  const statActive = document.getElementById('stat-active');
  const statActiveSpeed = document.getElementById('stat-active-speed');
  const statQueued = document.getElementById('stat-queued');
  const statCompleted = document.getElementById('stat-completed');
  const statConcurrency = document.getElementById('stat-concurrency');

  const countAll = document.getElementById('count-all');
  const countActive = document.getElementById('count-active');
  const countCompleted = document.getElementById('count-completed');

  const tasksContainer = document.getElementById('tasks-container');
  const emptyState = document.getElementById('empty-state');
  let currentFilter = 'all';
  let currentProviders = [];

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
      if (['downloading', 'processing', 'pausing', 'resuming'].includes(t.status)) {
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
    countActive.textContent = activeTasks + queuedTasks + tasks.filter(t => t.status === 'paused').length;
    countCompleted.textContent = completedTasks;

    // Filter tasks
    const filteredTasks = tasks.filter(t => {
      if (currentFilter === 'active') return ['downloading', 'processing', 'pausing', 'resuming'].includes(t.status) || t.status === 'queued' || t.status === 'paused';
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

  function updateTaskCard(card, html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    if (!card._renderedSections) {
      card.innerHTML = html;
      card._renderedSections = {};
    }

    // Compare rendered markup, not live DOM: buttons may be disabled while
    // their request is pending. Progress refreshes must preserve those nodes.
    for (const selector of ['.task-top', '.task-metrics', '.task-actions']) {
      const nextHtml = template.content.querySelector(selector).innerHTML;
      if (card._renderedSections[selector] !== nextHtml) {
        card.querySelector(selector).innerHTML = nextHtml;
        card._renderedSections[selector] = nextHtml;
      }
    }
    const progress = card.querySelector('.progress-bar-fill');
    const nextProgress = template.content.querySelector('.progress-bar-fill');
    progress.className = nextProgress.className;
    progress.style.width = nextProgress.style.width;

    const error = card.querySelector('.task-error-text');
    const nextError = template.content.querySelector('.task-error-text');
    if (nextError && error) {
      if (error.textContent !== nextError.textContent) error.textContent = nextError.textContent;
    } else if (nextError) {
      card.appendChild(nextError);
    } else if (error) {
      error.remove();
    }
  }

  function renderTasks(tasks) {
    if (!tasks.length) {
      emptyState.style.display = 'block';
      const existingCards = tasksContainer.querySelectorAll('.task-item');
      existingCards.forEach(card => card.remove());
      if (!tasksContainer.contains(emptyState)) {
        tasksContainer.appendChild(emptyState);
      }
      return;
    }

    emptyState.style.display = 'none';

    const currentTaskIds = new Set(tasks.map(t => String(t.id)));

    // Remove cards that are no longer in the task list
    const existingCards = tasksContainer.querySelectorAll('.task-item');
    existingCards.forEach(card => {
      if (!currentTaskIds.has(card.dataset.id)) {
        card.remove();
      }
    });

    let queuePositionCounter = 1;
    let previousCard = null;
    const selection = window.getSelection();

    tasks.forEach(task => {
      const taskId = String(task.id);
      let card = tasksContainer.querySelector(`.task-item[data-id="${taskId}"]`);
      if (!card) {
        card = document.createElement('div');
        card.className = 'task-item';
        card.dataset.id = taskId;
      }

      // Status badge and styling
      let statusBadgeClass = `badge-${escapeHtml(task.status)}`;
      let statusLabel = task.status.charAt(0).toUpperCase() + task.status.slice(1);
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
      if (['downloading', 'queued', 'processing', 'pausing', 'paused', 'resuming'].includes(task.status)) {
        actionButtons = `
          <button class="btn btn-danger btn-sm btn-cancel" data-id="${escapeHtml(task.id)}" title="Cancel download" aria-label="Cancel download">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            <span>Cancel</span>
          </button>
        `;
      } else if (task.status === 'completed') {
        actionButtons = `
          <button class="btn btn-secondary btn-sm btn-open-file" data-id="${escapeHtml(task.id)}" title="Open Video File" aria-label="Open Video File">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            <span>Play</span>
          </button>
        `;
      }

      if (['downloading', 'queued', 'processing'].includes(task.status)) {
        actionButtons = `<button class="btn btn-secondary btn-sm btn-pause" data-id="${escapeHtml(task.id)}" aria-label="Pause download">Pause</button>` + actionButtons;
      } else if (['paused', 'pausing'].includes(task.status)) {
        actionButtons = `<button class="btn btn-secondary btn-sm btn-resume" data-id="${escapeHtml(task.id)}" aria-label="Resume download">Resume</button>` + actionButtons;
      }

      if (['completed', 'failed', 'cancelled'].includes(task.status)) {
        actionButtons += `<button class="btn btn-ghost btn-sm btn-clear-task" data-id="${escapeHtml(task.id)}" title="Clear task from list" aria-label="Clear task">Clear</button>`;
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
      } else if (task.status === 'paused') {
        metricsHtml = `<span>Paused - partial download saved</span>`;
      } else if (task.status === 'pausing') {
        metricsHtml = `<span>Stopping download safely...</span>`;
      } else if (task.status === 'resuming') {
        metricsHtml = `<span>Resuming as soon as the previous worker stops...</span>`;
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

      const progressWidth = task.status === 'completed' ? 100 : (task.progress || 0);

      const cardInnerHtml = `
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
          <div class="progress-bar-fill ${fillClass}" style="width: ${progressWidth}%;"></div>
        </div>

        <div class="task-bottom">
          <div class="task-metrics">${metricsHtml}</div>
          <div class="task-actions">${actionButtons}</div>
        </div>
        ${errorHtml}
      `;

      // Keep selected text nodes alive until the user finishes copying.
      const hasSelection = selection && !selection.isCollapsed
        && selection.containsNode(card, true);
      if (!hasSelection && card._lastHtml !== cardInnerHtml) {
        updateTaskCard(card, cardInnerHtml);
        card._lastHtml = cardInnerHtml;
      }

      // Re-inserting even an unchanged card clears the browser's selection.
      const nextCard = previousCard
        ? previousCard.nextElementSibling
        : tasksContainer.querySelector('.task-item');
      if (card !== nextCard) {
        tasksContainer.insertBefore(card, nextCard);
      }
      previousCard = card;
    });
  }

  return { update: updateUI, setFilter(filter) { currentFilter = filter; } };
}
