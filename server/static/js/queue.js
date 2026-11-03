// Serializes queue refreshes so polling and user actions cannot overlap.
export function createQueuePoller(onUpdate) {
  let isFetching = false;
  let timer;
  // Fetch Queue & Update UI
  async function fetchQueue() {
    if (isFetching) return;
    isFetching = true;
    try {
      const res = await fetch('/api/queue');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      onUpdate(data);
    } catch (err) {
      console.warn('Error fetching queue:', err);
    } finally {
      isFetching = false;
    }
  }

  return {
    refresh: fetchQueue,
    start() {
      if (timer !== undefined) return;
      fetchQueue();
      timer = setInterval(fetchQueue, 1000);
    },
    stop() {
      clearInterval(timer);
      timer = undefined;
    },
  };
}
