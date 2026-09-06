// StreamDL Extension Service Worker / Background Script
if (typeof importScripts === "function") {
  importScripts("utils.js");
}

const streamsByTab = new Map();

function registerStream(tabId, url, typeHint = "", contentType = "", referer = "", pageTitle = "", headers = {}) {
  if (tabId < 0 || !url || !url.startsWith("http")) return;

  const streamInfo = analyzeStreamUrl(url, typeHint, contentType);
  if (!streamInfo) return;

  let tabStreams = streamsByTab.get(tabId) || [];
  const baseKey = getStreamKey(url);

  // Check if we already have this exact URL
  const exactIndex = tabStreams.findIndex((s) => s.url === url);
  if (exactIndex !== -1) {
    if (referer && !tabStreams[exactIndex].referer) {
      tabStreams[exactIndex].referer = referer;
    }
    if (headers && Object.keys(headers).length > 0) {
      tabStreams[exactIndex].headers = { ...(tabStreams[exactIndex].headers || {}), ...headers };
    }
    return;
  }

  // Check if we already have a stream from this exact video directory
  const existingIndex = tabStreams.findIndex((s) => getStreamKey(s.url) === baseKey);

  if (existingIndex !== -1) {
    const existing = tabStreams[existingIndex];
    if (streamInfo.isMaster && !existing.isMaster) {
      tabStreams[existingIndex] = {
        url: url,
        type: streamInfo.type,
        isMaster: true,
        filename: streamInfo.filename,
        referer: referer || existing.referer || "",
        headers: { ...(existing.headers || {}), ...(headers || {}) },
        title: pageTitle || existing.title || "",
        timestamp: Date.now(),
      };
    } else {
      return;
    }
  } else {
    const streamObj = {
      url: url,
      type: streamInfo.type,
      isMaster: streamInfo.isMaster,
      filename: streamInfo.filename,
      referer: referer,
      headers: headers || {},
      title: pageTitle,
      timestamp: Date.now(),
    };

    if (streamInfo.isMaster) {
      tabStreams.unshift(streamObj);
    } else {
      tabStreams.push(streamObj);
    }
  }

  if (tabStreams.length > 20) {
    tabStreams = tabStreams.slice(0, 20);
  }

  streamsByTab.set(tabId, tabStreams);
  updateBadge(tabId, tabStreams.length);
}

// 1. Intercept all requests marked as media type (catches Doodstream, HTML5 players, MSE)
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.tabId < 0) return;
    registerStream(
      details.tabId,
      details.url,
      details.type,
      "",
      details.initiator || details.originUrl || details.documentUrl || ""
    );
  },
  {
    urls: ["<all_urls>"],
    types: ["media"]
  }
);

// 2. Intercept requests to known streaming patterns and Doodstream domains
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.tabId < 0) return;
    registerStream(
      details.tabId,
      details.url,
      details.type,
      "",
      details.initiator || details.originUrl || details.documentUrl || ""
    );
  },
  {
    urls: [
      "*://*/*.m3u8*",
      "*://*/*.mpd*",
      "*://*/*.mp4*",
      "*://*/*.webm*",
      "*://*/remote_control.php*",
      "*://*.doodstream.com/*",
      "*://*.dood.video/*",
      "*://*.dood.re/*",
      "*://*.dood.to/*",
      "*://*.dood.so/*",
      "*://*.dood.cx/*",
      "*://*.dood.la/*",
      "*://*.dood.ws/*",
      "*://*.dood.sh/*",
      "*://*.dood.wf/*",
      "*://*.dood.pm/*"
    ],
    types: ["xmlhttprequest", "other"]
  }
);

// 3. Intercept response headers to detect any video Content-Type (even extension-less URLs)
chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.tabId < 0) return;
    const headers = details.responseHeaders || [];
    const ctHeader = headers.find((h) => h.name.toLowerCase() === "content-type");
    const contentType = ctHeader ? ctHeader.value.toLowerCase() : "";

    if (
      contentType.startsWith("video/") ||
      contentType.includes("application/vnd.apple.mpegurl") ||
      contentType.includes("application/x-mpegurl") ||
      contentType.includes("application/dash+xml")
    ) {
      registerStream(
        details.tabId,
        details.url,
        details.type,
        contentType,
        details.initiator || details.originUrl || details.documentUrl || ""
      );
    }
  },
  {
    urls: ["<all_urls>"],
    types: ["media", "xmlhttprequest", "other"]
  },
  ["responseHeaders"]
);

// 4. Intercept request headers to capture Referer, Origin, User-Agent, Cookie for streams
const sendHeadersOptions = ["requestHeaders"];
if (
  typeof chrome !== "undefined" &&
  chrome.webRequest &&
  chrome.webRequest.OnBeforeSendHeadersOptions &&
  chrome.webRequest.OnBeforeSendHeadersOptions.hasOwnProperty("EXTRA_HEADERS")
) {
  sendHeadersOptions.push("extraHeaders");
}

chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    if (details.tabId < 0 || !details.url) return;
    const captured = extractHeaders(details.requestHeaders);
    if (Object.keys(captured).length === 0) return;

    const tabStreams = streamsByTab.get(details.tabId);
    if (!tabStreams) return;

    const baseKey = getStreamKey(details.url);
    for (const s of tabStreams) {
      if (s.url === details.url || getStreamKey(s.url) === baseKey) {
        s.headers = { ...(s.headers || {}), ...captured };
        if (captured["Referer"] && !s.referer) {
          s.referer = captured["Referer"];
        }
      }
    }
  },
  {
    urls: ["<all_urls>"]
  },
  sendHeadersOptions
);

// Update badge count on extension icon
function updateBadge(tabId, count) {
  const actionApi = (typeof chrome !== "undefined" && chrome.action) || (typeof browser !== "undefined" && browser.action);
  if (!actionApi) return;
  if (count > 0) {
    actionApi.setBadgeText({ tabId, text: String(count) });
    actionApi.setBadgeBackgroundColor({ tabId, color: "#6366f1" });
  } else {
    actionApi.setBadgeText({ tabId, text: "" });
  }
}

// Clean up streams when tab is closed or navigated
chrome.tabs.onRemoved.addListener((tabId) => {
  streamsByTab.delete(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    streamsByTab.delete(tabId);
    updateBadge(tabId, 0);
  }
});

// Setup Context Menu
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "streamdl-download",
    title: "Download with yt-dlp",
    contexts: ["page", "video", "link"]
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "streamdl-download") {
    const targetUrl = info.srcUrl || info.linkUrl || info.pageUrl || (tab && tab.url);
    if (!targetUrl) return;

    let streamHeaders = {};
    if (tab && tab.id) {
      const tabStreams = streamsByTab.get(tab.id) || [];
      const matched = tabStreams.find((s) => s.url === targetUrl);
      if (matched && matched.headers) {
        streamHeaders = matched.headers;
      }
    }

    await sendDownloadRequest({
      url: targetUrl,
      title: tab ? tab.title : undefined,
      referer: tab ? tab.url : undefined,
      headers: streamHeaders
    });
  }
});

// Handle messages from Popup or Content Script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "GET_TAB_STREAMS") {
    const tabId = message.tabId;
    const streams = streamsByTab.get(tabId) || [];
    sendResponse({ streams });
    return true;
  } else if (message.action === "SEND_DOWNLOAD") {
    sendDownloadRequest(message.payload)
      .then((res) => sendResponse(res))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true;
  } else if (message.action === "REGISTER_DOM_MEDIA") {
    const tabId = sender.tab ? sender.tab.id : null;
    if (tabId) {
      registerStream(
        tabId,
        message.url,
        "media",
        "",
        message.referer || (sender.tab ? sender.tab.url : ""),
        message.title || ""
      );
    }
  }
});

// Send download command to local Flask server
async function sendDownloadRequest({ url, title, referer, headers: customHeaders, provider, quality = "best", format = "mp4" }) {
  const serverUrl = await getServerUrl();
  const headers = { ...(customHeaders || {}) };
  if (referer && !headers["Referer"] && !headers["referer"]) {
    headers["Referer"] = referer;
  }
  const refVal = headers["Referer"] || headers["referer"];
  if (refVal && !headers["Origin"] && !headers["origin"]) {
    const derivedOrigin = deriveOriginFromReferer(refVal);
    if (derivedOrigin) {
      headers["Origin"] = derivedOrigin;
    }
  }

  let res;
  try {
    res = await fetch(`${serverUrl}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        title,
        quality,
        format,
        headers,
        provider
      })
    });
  } catch (netErr) {
    console.error("Failed to connect to local server:", netErr);
    throw new Error(
      `Local server is offline or unreachable at ${serverUrl}. Make sure run_server.bat is running.`
    );
  }

  let data = null;
  try {
    data = await res.json();
  } catch (jsonErr) {
    data = null;
  }

  if (!res.ok) {
    const serverErrMsg = data && (data.error || data.message);
    if (serverErrMsg) {
      throw new Error(serverErrMsg);
    }
    throw new Error(`Server returned status ${res.status}`);
  }

  return data;
}
