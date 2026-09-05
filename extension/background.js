// StreamDL Extension Service Worker
const SERVER_URL = "http://localhost:7921";
const streamsByTab = new Map();

// Helper to determine stream type & priority
function analyzeStreamUrl(url) {
  const lower = url.toLowerCase();
  
  // Exclude segment chunks
  if (lower.includes(".ts") || lower.includes(".m4s") || lower.includes(".aac") || lower.includes("segment-")) {
    return null;
  }

  let type = "other";
  let isMaster = false;

  if (lower.includes(".m3u8")) {
    type = "HLS (.m3u8)";
    if (lower.includes("master") || lower.includes("index") || lower.includes("playlist") || lower.includes("manifest")) {
      isMaster = true;
    }
  } else if (lower.includes(".mpd")) {
    type = "DASH (.mpd)";
    isMaster = true;
  } else if (lower.includes(".mp4")) {
    type = "MP4 Video";
  } else if (lower.includes(".webm")) {
    type = "WebM Video";
  } else {
    return null;
  }

  return { type, isMaster };
}

// Intercept network requests for media stream manifests and video URLs
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.tabId < 0) return;

    const streamInfo = analyzeStreamUrl(details.url);
    if (!streamInfo) return;

    let tabStreams = streamsByTab.get(details.tabId) || [];
    
    // Check if URL already recorded
    const exists = tabStreams.some((s) => s.url === details.url);
    if (!exists) {
      const streamObj = {
        url: details.url,
        type: streamInfo.type,
        isMaster: streamInfo.isMaster,
        timestamp: Date.now(),
        initiator: details.initiator || details.documentUrl || "",
      };

      // Place master playlists at the front of the list
      if (streamInfo.isMaster) {
        tabStreams.unshift(streamObj);
      } else {
        tabStreams.push(streamObj);
      }

      // Limit memory to 20 streams per tab
      if (tabStreams.length > 20) {
        tabStreams = tabStreams.slice(0, 20);
      }

      streamsByTab.set(details.tabId, tabStreams);
      updateBadge(details.tabId, tabStreams.length);
    }
  },
  {
    urls: [
      "*://*/*.m3u8*",
      "*://*/*.mpd*",
      "*://*/*.mp4*",
      "*://*/*.webm*"
    ]
  }
);

// Update badge count on extension icon
function updateBadge(tabId, count) {
  if (count > 0) {
    chrome.action.setBadgeText({ tabId, text: String(count) });
    chrome.action.setBadgeBackgroundColor({ tabId, color: "#6366f1" });
  } else {
    chrome.action.setBadgeText({ tabId, text: "" });
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

    await sendDownloadRequest({
      url: targetUrl,
      title: tab ? tab.title : undefined,
      referer: tab ? tab.url : undefined
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
      const streamInfo = analyzeStreamUrl(message.url);
      if (streamInfo) {
        let tabStreams = streamsByTab.get(tabId) || [];
        if (!tabStreams.some((s) => s.url === message.url)) {
          tabStreams.unshift({
            url: message.url,
            type: streamInfo.type,
            isMaster: streamInfo.isMaster,
            timestamp: Date.now()
          });
          streamsByTab.set(tabId, tabStreams);
          updateBadge(tabId, tabStreams.length);
        }
      }
    }
  }
});

// Send download command to local Flask server
async function sendDownloadRequest({ url, title, referer, quality = "best", format = "mp4" }) {
  try {
    const headers = {};
    if (referer) {
      headers["Referer"] = referer;
    }

    const res = await fetch(`${SERVER_URL}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        title,
        quality,
        format,
        headers
      })
    });

    if (!res.ok) {
      throw new Error(`Server returned status ${res.status}`);
    }

    const data = await res.json();
    return data;
  } catch (err) {
    console.error("Failed to connect to local server:", err);
    throw new Error(
      "Local server is offline or unreachable at http://localhost:7921. Make sure run_server.bat is running."
    );
  }
}
