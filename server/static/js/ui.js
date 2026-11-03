export function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function sanitizeMediaUrl(url) {
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
export function showToast(message, type = 'info') {
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


// FastAPI validation bodies may contain captured inputs; display only safe messages.
export function apiError(body, fallback) {
  if (!body || typeof body !== 'object') return fallback;
  if (typeof body.error === 'string') return body.error;
  if (typeof body.detail === 'string') return body.detail;
  if (Array.isArray(body.detail)) {
    const messages = body.detail.filter(item => item && typeof item.msg === 'string').map(item => {
      const location = Array.isArray(item.loc) ? item.loc.filter(part => typeof part === 'string' || typeof part === 'number').filter(part => part !== 'body').join('.') : '';
      return location ? `${location}: ${item.msg}` : item.msg;
    });
    return messages.length ? messages.join('; ') : fallback;
  }
  return fallback;
}
