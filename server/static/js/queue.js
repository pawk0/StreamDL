// One live subscription plus explicit action refreshes; stale HTTP reads cannot win.
export function createQueuePoller(onUpdate) {
  let source;
  let isFetching = false;
  let revision = 0;
  let hasConnected = false;
  const status = text => {
    const label = document.getElementById('server-status-text');
    const pill = document.getElementById('server-status-pill');
    if (label) label.textContent = text;
    if (pill) pill.classList.toggle('online', text === 'Connected');
  };
  async function fetchQueue() {
    if (isFetching) return;
    isFetching = true;
    const started = revision;
    try {
      const res = await fetch('/api/queue');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (started === revision) onUpdate(data);
    } catch (err) {
      console.warn('Error fetching queue:', err);
    } finally {
      isFetching = false;
    }
  }
  return {
    refresh: fetchQueue,
    start() {
      if (source) return;
      status(hasConnected ? 'Reconnecting' : 'Connecting');
      source = new EventSource('/api/events');
      const active = source;
      source.addEventListener('queue', event => {
        if (source !== active) return;
        try {
          const data = JSON.parse(event.data);
          if (!data || !Array.isArray(data.tasks) || !Array.isArray(data.providers)) return;
          revision++;
          onUpdate(data);
          hasConnected = true;
          status('Connected');
        } catch (err) {
          console.warn('Invalid queue event:', err);
        }
      });
      source.onerror = () => { if (source === active) status('Reconnecting'); };
    },
    stop() {
      revision++;
      if (source) source.close();
      source = undefined;
    },
  };
}
