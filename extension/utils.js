// StreamDL Extension Shared Utilities
const DEFAULT_SERVER_URL = "http://localhost:7921";

/**
 * Resolves the server base URL, checking chrome.storage.local for custom serverUrl or serverPort.
 * Falls back to DEFAULT_SERVER_URL.
 */
function getServerUrl() {
  return new Promise((resolve) => {
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
      try {
        chrome.storage.local.get(["serverUrl", "serverPort"], (res) => {
          if (chrome.runtime && chrome.runtime.lastError) {
            return resolve(DEFAULT_SERVER_URL);
          }
          if (res) {
            if (typeof res.serverUrl === "string" && res.serverUrl.trim()) {
              return resolve(res.serverUrl.trim().replace(/\/+$/, ""));
            }
            if (res.serverPort) {
              return resolve(`http://localhost:${res.serverPort}`);
            }
          }
          resolve(DEFAULT_SERVER_URL);
        });
        return;
      } catch (e) {
        // Fall back to default
      }
    }
    resolve(DEFAULT_SERVER_URL);
  });
}

/**
 * Saves a custom server URL or port into chrome.storage.local.
 */
function setServerUrl(urlOrPort) {
  return new Promise((resolve, reject) => {
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
      const payload = {};
      if (typeof urlOrPort === "number" || (typeof urlOrPort === "string" && /^\d+$/.test(urlOrPort.trim()))) {
        payload.serverPort = parseInt(urlOrPort, 10);
      } else if (typeof urlOrPort === "string" && urlOrPort.trim()) {
        payload.serverUrl = urlOrPort.trim().replace(/\/+$/, "");
      }
      chrome.storage.local.set(payload, () => {
        if (chrome.runtime && chrome.runtime.lastError) {
          return reject(chrome.runtime.lastError);
        }
        resolve();
      });
    } else {
      resolve();
    }
  });
}

/**
 * Extracts base stream directory key (protocol://host/path/without_filename) to group variant streams.
 */
function getStreamKey(url) {
  try {
    const u = new URL(url);
    const segments = u.pathname.split("/").filter(Boolean);
    segments.pop(); // remove filename
    return `${u.origin}/${segments.join("/")}`;
  } catch (e) {
    return url.split("?")[0];
  }
}

/**
 * Determines stream type, master vs variant status, and exclusions.
 */
function analyzeStreamUrl(url, typeHint = "", contentType = "") {
  if (!url || typeof url !== "string") return null;

  const lower = url.toLowerCase();
  const lowerCt = (contentType || "").toLowerCase();

  // Exclude segment chunks, transport streams, subtitles, images, styles
  if (
    lowerCt.includes("mp2t") ||
    lower.includes(".ts") ||
    lower.includes(".m4s") ||
    lower.includes(".aac") ||
    lower.includes("segment-") ||
    lower.includes("/seg-") ||
    lower.includes("/fragment") ||
    lower.endsWith(".jpg") ||
    lower.endsWith(".png") ||
    lower.endsWith(".gif") ||
    lower.endsWith(".svg") ||
    lower.endsWith(".vtt") ||
    lower.endsWith(".srt") ||
    lower.endsWith(".css") ||
    lower.endsWith(".js")
  ) {
    return null;
  }

  let type = "other";
  let isMaster = false;
  let isVariant = false;

  const pathname = url.split("?")[0].toLowerCase();
  const filename = pathname.split("/").pop() || "";

  // Doodstream detection (dood.re, dood.video, doodstream, etc.)
  if (
    lower.includes("dood.video") ||
    lower.includes("doodstream") ||
    lower.includes("dood.")
  ) {
    type = "Doodstream Video";
    isMaster = true;
  } else if (lower.includes("remote_control.php")) {
    type = "Direct MP4 Stream";
    isMaster = true;
  } else if (lower.includes(".m3u8") || lowerCt.includes("mpegurl")) {
    type = "HLS (.m3u8)";

    // Check if this is a variant/child playlist (e.g. index-f2-v1-a1.m3u8, 720p.m3u8, chunklist)
    if (
      /[-_][fva]\d+/i.test(filename) ||
      filename.includes("chunklist") ||
      filename.includes("rendition") ||
      filename.includes("tracks-") ||
      /\b(1080p|720p|480p|360p|240p)\.m3u8/i.test(filename)
    ) {
      isVariant = true;
      isMaster = false;
    } else if (
      filename === "master.m3u8" ||
      filename === "playlist.m3u8" ||
      filename === "manifest.m3u8" ||
      filename === "index.m3u8" ||
      filename === "main.m3u8" ||
      filename.includes("master") ||
      filename.includes("manifest")
    ) {
      isMaster = true;
    }
  } else if (lower.includes(".mpd") || lowerCt.includes("dash")) {
    type = "DASH (.mpd)";
    isMaster = true;
  } else if (lower.includes(".mp4") || lowerCt.includes("mp4")) {
    type = "MP4 Video";
    isMaster = true;
  } else if (lower.includes(".webm") || lowerCt.includes("webm")) {
    type = "WebM Video";
    isMaster = true;
  } else if (typeHint === "media" || lowerCt.startsWith("video/")) {
    type = "Direct Media Stream";
    isMaster = true;
  } else {
    return null;
  }

  return { type, isMaster, isVariant, filename };
}

/**
 * Extracts essential headers (Referer, Origin, User-Agent, Cookie) from Chrome requestHeaders array.
 */
function extractHeaders(requestHeaders) {
  const result = {};
  if (!Array.isArray(requestHeaders)) return result;
  for (const h of requestHeaders) {
    if (!h.name || !h.value) continue;
    const lower = h.name.toLowerCase();
    if (lower === "referer") {
      result["Referer"] = h.value;
    } else if (lower === "origin") {
      result["Origin"] = h.value;
    } else if (lower === "user-agent") {
      result["User-Agent"] = h.value;
    } else if (lower === "cookie") {
      result["Cookie"] = h.value;
    }
  }
  return result;
}

/**
 * Generically derives the Origin header from a Referer URL.
 */
function deriveOriginFromReferer(referer) {
  if (!referer || typeof referer !== "string") return "";
  try {
    const u = new URL(referer);
    return u.origin;
  } catch (e) {
    return "";
  }
}

/**
 * Wildcard pattern matcher matching backend provider definitions (*dood*, *remote_control.php*, etc.).
 */
function matchPattern(pattern, text) {
  if (!pattern || !text) return false;
  let p = pattern.trim().toLowerCase();
  if (!p) return false;
  if (!p.includes("*")) {
    p = `*${p}*`;
  }
  const regexStr = "^" + p.split("*").map((s) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$";
  return new RegExp(regexStr, "i").test(text);
}

/**
 * Matches candidate URLs/referers against configured providers from settings.json.
 */
function detectProvider(url, referer = "", configuredProviders = []) {
  const candidates = [url, referer].filter(Boolean);
  const providers = Array.isArray(configuredProviders) ? configuredProviders : [];
  for (const p of providers) {
    const patterns = Array.isArray(p.patterns) ? p.patterns : [];
    for (const pattern of patterns) {
      for (const candidate of candidates) {
        if (matchPattern(pattern, candidate)) {
          return p.name || p.id;
        }
      }
    }
  }
  try {
    const u = new URL(url);
    const parts = u.hostname.split(".");
    return parts.length >= 2 ? parts.slice(-2).join(".") : u.hostname;
  } catch (e) {
    return "";
  }
}

/**
 * Extracts a readable filename from a stream URL.
 */
function extractFilename(url) {
  if (!url || typeof url !== "string") return "stream";
  try {
    const u = new URL(url);
    const parts = u.pathname.split("/").filter(Boolean);
    return parts.pop() || "stream";
  } catch (e) {
    return url.split("?")[0].split("/").pop() || "stream";
  }
}

/**
 * Sanitizes page titles by stripping trailing site branding / suffixes.
 */
function cleanVideoTitle(rawTitle) {
  if (!rawTitle || typeof rawTitle !== "string") return "";
  let cleanTitle = rawTitle.trim();
  cleanTitle = cleanTitle.replace(/\s*[-–—|]\s*([^|–—-]+)$/i, (match, suffix) => {
    if (suffix.includes(".") || suffix.length < 25) return "";
    return match;
  }).trim();
  return cleanTitle || rawTitle.trim();
}

/**
 * Formats a display label for stream selector dropdowns.
 */
function formatStreamLabel(stream, configuredProviders = []) {
  if (!stream || !stream.url) return "Unknown stream";
  try {
    const u = new URL(stream.url);
    const fn = extractFilename(stream.url);
    const provider = detectProvider(stream.url, stream.referer, configuredProviders);
    const prefix = stream.isMaster ? "⭐ [Master] " : "";
    return `${prefix}${fn} (${provider || u.hostname})`;
  } catch (e) {
    return stream.url.substring(0, 45) + "...";
  }
}

// Global exposure for browser contexts (ServiceWorker / Window)
if (typeof globalThis !== "undefined") {
  globalThis.StreamDLUtils = {
    DEFAULT_SERVER_URL,
    getServerUrl,
    setServerUrl,
    getStreamKey,
    analyzeStreamUrl,
    extractHeaders,
    deriveOriginFromReferer,
    matchPattern,
    detectProvider,
    extractFilename,
    cleanVideoTitle,
    formatStreamLabel,
  };
}

// Node / CommonJS test environment export
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    DEFAULT_SERVER_URL,
    getServerUrl,
    setServerUrl,
    getStreamKey,
    analyzeStreamUrl,
    extractHeaders,
    deriveOriginFromReferer,
    matchPattern,
    detectProvider,
    extractFilename,
    cleanVideoTitle,
    formatStreamLabel,
  };
}
